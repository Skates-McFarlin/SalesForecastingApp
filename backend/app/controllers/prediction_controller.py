import json
import csv
from datetime import datetime
import re
import threading
import time
from prophet import Prophet
import pandas as pd
import numpy as np
import torch
from app.models.prediction import Prediction
from app.models.file import File
from app.extensions import db
from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig
from huggingface_hub import snapshot_download
import os

ENABLE_AI_SUMMARY = True

QWEN_REPO_ID = "Qwen/Qwen2.5-1.5B-Instruct"

# Persistent, always-writable location (survives reinstalls, works regardless
# of install-dir permissions) - same pattern as the SQLite DB path.
_appdata = os.getenv("LOCALAPPDATA")
MODEL_PATH = (
    os.path.join(_appdata, "Insighta", "models", "qwen2_5")
    if _appdata
    else os.path.join(os.path.dirname(__file__), "..", "models", "qwen2_5")
)

tokenizer = None
model = None
model_status = {"status": "starting", "ready": False, "error": None}


def _model_already_present():
    """Check whether a complete model already sits at MODEL_PATH.

    Checks both a config file and the weights (not just one file) and
    retries briefly: a freshly-installed, unsigned exe's first filesystem
    access can be transiently delayed (e.g. antivirus scanning), which can
    make a single os.path.exists() check falsely report "missing" and
    trigger an unnecessary multi-minute Hub verification pass.
    """
    config_path = os.path.join(MODEL_PATH, "config.json")
    weights_path = os.path.join(MODEL_PATH, "model.safetensors")
    for _ in range(5):
        if os.path.isfile(config_path) and os.path.isfile(weights_path):
            return True
        time.sleep(1)
    return False


def _load_model():
    """Download (first run only) and load the Qwen model in the background.

    Runs off the main thread so Flask can start serving immediately and
    report real progress via /api/health instead of blocking startup.
    """
    global tokenizer, model
    try:
        if not _model_already_present():
            model_status["status"] = "downloading_model"
            os.makedirs(MODEL_PATH, exist_ok=True)
            snapshot_download(
                repo_id=QWEN_REPO_ID,
                local_dir=MODEL_PATH,
                ignore_patterns=["*.bin", "*.gguf", "*.onnx", "*.msgpack", "*.h5"],
            )

        model_status["status"] = "loading_model"
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForCausalLM.from_pretrained(MODEL_PATH, torch_dtype=torch.bfloat16)
        model.config.pad_token_id = tokenizer.pad_token_id
        model.eval()

        model_status["status"] = "ready"
        model_status["ready"] = True
    except Exception as exc:  # noqa: BLE001 - surface any failure via /api/health
        model_status["status"] = "error"
        model_status["error"] = str(exc)


threading.Thread(target=_load_model, daemon=True).start()


def _chat(messages, generation_config):
    """Run one chat-formatted generation through the local Qwen model."""
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt")

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            generation_config=generation_config,
            pad_token_id=tokenizer.pad_token_id
        )

    generated_ids = output_ids[0][inputs.input_ids.shape[1]:]
    return tokenizer.decode(generated_ids, skip_special_tokens=True).strip()


def classify_product(product_name):
    """Zero-shot classify a product's seasonality and category from its name alone.

    This is a stand-in for real product context until an actual data source
    (a category taxonomy, tariff schedule, etc.) is wired in via RAG later.
    """
    prompt = f"""Classify this product for a sales forecasting report.

Product Name: {product_name}

Respond with ONLY a JSON object in this exact format, no other text:
{{"seasonality": "<winter|spring|summer|fall|holiday|year-round|unknown>", "category": "<short 2-4 word category description>"}}
"""
    messages = [
        {"role": "system", "content": "You are a product classification assistant. Respond only with valid JSON, no explanation."},
        {"role": "user", "content": prompt}
    ]

    generation_config = GenerationConfig(
        max_new_tokens=64,
        do_sample=False,
    )

    raw = _chat(messages, generation_config)

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        tags = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        tags = {}

    return {
        "seasonality": tags.get("seasonality", "unknown"),
        "category": tags.get("category", "unknown"),
    }


def generate_summary(product, percent_change, forecast, last_year_sales, duration, tags):
    """Generate a natural language inventory-flow summary using Qwen2.5-1.5B-Instruct.

    Frames the forecast as inventory movement: units forecasted to go OUT (sales)
    versus the units that should come IN (restock) to cover that demand, grounded
    in the product's inferred category/seasonality so the LLM can flag whether a
    trend looks like normal seasonal movement or an actual demand shift.
    """
    prompt = f"""You are an expert inventory and sales forecasting analyst.

Based on the data below, write a concise, professional summary (3-5 sentences) covering:
1. Outbound inventory: how many units of this product are forecasted to leave inventory (be sold) over the period
2. Inbound inventory: how many units should be restocked/received to cover that forecasted demand without stocking out
3. How this period compares to the same period last year (trend direction and % change), and whether that looks like normal seasonal movement for this product's category or an actual demand shift
4. Any actionable recommendation for purchasing or replenishment planning

Data:
- Product Name: {product}
- Product Category: {tags['category']}
- Seasonality: {tags['seasonality']}
- Forecast Period: {duration} month(s)
- Forecasted Units Out (Sales): {forecast}
- Last Year Actual Units Out (Sales): {last_year_sales}
- % Change from Previous Year: {percent_change}%

Write the summary in a clear, professional tone suitable for a business inventory report.
"""

    messages = [
        {"role": "system", "content": "You are a professional inventory and sales analyst. Provide concise, data-driven insights."},
        {"role": "user", "content": prompt}
    ]

    generation_config = GenerationConfig(
        max_new_tokens=512,
        temperature=0.7,
        top_p=0.95,
        do_sample=True,
        repetition_penalty=1.1
    )

    return _chat(messages, generation_config)


def predict_sales_forecasting(data, start_date, duration):

    file_data = data.read()

    file_record = File(filename=data.filename, filedata=file_data)
    db.session.add(file_record)
    db.session.commit()

    json_data = preprocess_data(data)
    forecast_periods = duration
    forecast_start_date = start_date
    forecast_last_start_date = (
        str(int(forecast_start_date[:4]) - 1) + forecast_start_date[4:]
    )

    df = pd.DataFrame(json_data)

    # Ensure the date column is in datetime format
    df["ds"] = pd.to_datetime(df["ds"], format="%Y-%m-%d")

    # Get unique products
    products = df["product_name"].unique()

    # Define forecast duration

    # Prepare forecast results storage
    forecast_results = []

    # Forecast separately for each product
    for product in products:
        # Filter dataset for the current product
        df_product = df[df["product_name"] == product]

        # Initialize Prophet Model
        m = Prophet()
        m.fit(df_product[["ds", "y"]])

        # Generate Future Dates for Forecasting (starting from custom date)
        future = pd.date_range(
            start=forecast_start_date, periods=forecast_periods, freq="MS"
        ).to_frame(index=False, name="ds")

        # Ensure the end date is the last day of the forecasted month
        end_date = future["ds"].max() + pd.offsets.MonthEnd(0)

        # Make Predictions for the Future
        forecast = m.predict(future)

        sum_forecast_now = forecast["yhat"].sum()

        selected_months = (
            df_product["ds"]
            .dt.strftime("%Y-%m")
            .isin(
                pd.date_range(
                    start=forecast_last_start_date, periods=forecast_periods, freq="MS"
                ).strftime("%Y-%m")
            )
        )

        actual_sales_values = df_product.loc[selected_months, "y"].tolist()
        actual_last_year_sales = (
            sum(actual_sales_values) if len(actual_sales_values) > 0 else 0
        )

        # Calculate percentage change correctly
        percent_change = (
            ((sum_forecast_now - actual_last_year_sales) / abs(actual_last_year_sales))
            * 100
            if actual_last_year_sales != 0
            else "N/A"
        )
        
        if ENABLE_AI_SUMMARY:
            product_tags = classify_product(product)
            generated_text = generate_summary(
                product,
                percent_change,
                round(sum_forecast_now),
                round(actual_last_year_sales),
                duration,
                product_tags,
            )
        else:
            generated_text = "N/A"

        # Store the result in the required format
        forecast_results.append(
            {
                "ProductName": product,
                "Duration": f"{forecast_start_date} - {end_date.date()}",
                "Forecast": round(sum_forecast_now),
                "Last Year Actual Sales": round(actual_last_year_sales),
                "% Change from Previous Year": (
                    round(percent_change, 2) if percent_change != "N/A" else "N/A"
                ),
                "Summary": generated_text,
            }
        )

        prediction = Prediction(
            file_id=file_record.id,
            product_name=product,
            duration=f"{forecast_start_date} - {end_date.date()}",
            forecast=str(round(sum_forecast_now)),
            actual_sales=str(round(actual_last_year_sales)),
            percent_change=str(
                (round(percent_change, 2) if percent_change != "N/A" else "N/A")
            ),
        )
        db.session.add(prediction)
        db.session.commit()

    return json.dumps(forecast_results, indent=4)


def preprocess_data(data):
    json_data = []
    data.stream.seek(0)  # Ensure reading from the start
    reader = csv.DictReader(data.stream.read().decode("utf-8").splitlines())

    headers = reader.fieldnames

    # Identify columns related to sales data (e.g., "Quantity Sold Jan 2016")
    sales_columns = [
        header for header in headers if re.match(r"Quantity Sold \w+ \d{4}", header)
    ]

    # Extract years from the column names (e.g., from "Quantity Sold Jan 2016")
    years = set()
    for col in sales_columns:
        match = re.match(r"Quantity Sold \w+ (\d{4})", col)
        if match:
            years.add(int(match.group(1)))

    # Dictionary to store aggregated sales
    aggregated_data = {}

    # Loop through each row in the CSV
    for row in reader:
        product_name = row["Product Name"]

        # Loop through the years and months dynamically
        for year in range(min(years), max(years) + 1):
            for month in range(1, 13):
                # Create the header for this specific month and year (e.g., "Quantity Sold Jan 2016")
                month_name = datetime(year=year, month=month, day=1).strftime(
                    "%b %Y"
                )  # e.g., "Jan 2016"
                column_name = f"Quantity Sold {month_name}"

                # Check if this column exists in the CSV for this product
                if column_name in row:
                    quantity_sold = row[column_name]

                    # Only add valid data (non-empty, non-null values)
                    if quantity_sold and quantity_sold.strip().isdigit():
                        # Format the date for the 'ds' field in the required format (YYYY-MM-DD)
                        date_str = datetime(year=year, month=month, day=1).strftime(
                            "%Y-%m-%d"
                        )

                        # **Aggregate Sales for Each Product and Date**
                        key = (product_name, date_str)
                        if key in aggregated_data:
                            aggregated_data[key]["y"] += int(quantity_sold)
                        else:
                            aggregated_data[key] = {
                                "ds": date_str,
                                "y": int(quantity_sold),
                                "product_name": product_name,
                            }

    # Convert aggregated data dictionary to a list
    json_data = list(aggregated_data.values())

    return json_data


def calculate_error_metrics(data, start_date, duration):
    json_data = preprocess_data(data)
    forecast_periods = duration
    forecast_start_date = start_date  # e.g., "2024-03-01"
    training_cutoff = pd.to_datetime(
        forecast_start_date
    )  # use data strictly before forecast start

    # Full data DataFrame
    full_df = pd.DataFrame(json_data)
    full_df["ds"] = pd.to_datetime(full_df["ds"], format="%Y-%m-%d")
    products = full_df["product_name"].unique()
    error_results = []

    for product in products:
        # Use only data before forecast_start_date for training
        training_df = full_df[
            (full_df["product_name"] == product) & (full_df["ds"] < training_cutoff)
        ].sort_values("ds")
        if training_df.empty:
            # Skip product if no training data is available
            continue

        m = Prophet()
        m.fit(training_df[["ds", "y"]])

        # Create forecast for the specified period
        future = pd.date_range(
            start=forecast_start_date, periods=forecast_periods, freq="MS"
        ).to_frame(index=False, name="ds")
        end_date = future["ds"].max() + pd.offsets.MonthEnd(0)
        forecast = m.predict(future)
        yhat = forecast["yhat"].values

        # Now get actual sales from the full data for the forecast period
        actual_range = pd.date_range(
            start=forecast_start_date, periods=forecast_periods, freq="MS"
        )
        actual_sales = []
        for d in actual_range:
            d_str = d.strftime("%Y-%m")
            row = full_df[
                (full_df["product_name"] == product)
                & (full_df["ds"].dt.strftime("%Y-%m") == d_str)
            ]
            if not row.empty:
                actual_sales.append(row.iloc[0]["y"])
            else:
                actual_sales.append(0)
        yhat_arr = np.array(yhat)
        actual_arr = np.array(actual_sales)

        # Calculate error metrics
        mae = np.mean(np.abs(yhat_arr - actual_arr))
        rmse = np.sqrt(np.mean((yhat_arr - actual_arr) ** 2))
        with np.errstate(divide="ignore", invalid="ignore"):
            mape = (
                np.mean(
                    np.where(
                        actual_arr != 0, np.abs((yhat_arr - actual_arr) / actual_arr), 0
                    )
                )
                * 100
            )

        sum_forecast = yhat_arr.sum()
        sum_actual = actual_arr.sum()

        error_results.append(
            {
                "ProductName": product,
                "Duration": f"{forecast_start_date} - {end_date.date()}",
                "Forecast": float(round(sum_forecast, 2)),
                "Actual Sales": float(round(sum_actual, 2)),
                "Error Metrics": {
                    "MAE": float(round(mae, 2)),
                    "RMSE": float(round(rmse, 2)),
                    "MAPE": f"{float(round(mape, 2))}%",
                },
            }
        )
    return json.dumps(error_results, indent=4)
