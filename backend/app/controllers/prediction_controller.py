import json
import io
from datetime import datetime
import re
import threading
import time
import subprocess
import atexit
import sys
from concurrent.futures import ThreadPoolExecutor
import requests
from prophet import Prophet
import pandas as pd
import numpy as np
from app.models.prediction import Prediction
from app.models.file import File
from app.extensions import db
from huggingface_hub import hf_hub_download
import os

GGUF_REPO_ID = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
GGUF_FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"

LLAMA_SERVER_HOST = "127.0.0.1"
LLAMA_SERVER_PORT = 8081
LLAMA_SERVER_BASE_URL = f"http://{LLAMA_SERVER_HOST}:{LLAMA_SERVER_PORT}"

# Persistent, always-writable location (survives reinstalls, works regardless
# of install-dir permissions) - same pattern as the SQLite DB path.
_appdata = os.getenv("LOCALAPPDATA")
MODEL_DIR = (
    os.path.join(_appdata, "Insighta", "models", "qwen2_5_gguf")
    if _appdata
    else os.path.join(os.path.dirname(__file__), "..", "models", "qwen2_5_gguf")
)
MODEL_FILE = os.path.join(MODEL_DIR, GGUF_FILENAME)

llama_process = None
model_status = {"status": "starting", "ready": False, "error": None}


def _llama_server_exe():
    """Resolve llama-server.exe, bundled alongside this backend (not
    downloaded - it's a small, versioned build dependency, unlike the
    model). Same frozen-vs-dev path resolution pattern as run.exe/backend
    resolution elsewhere in this app."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.join(os.path.dirname(__file__), "..", "..")
    return os.path.join(base, "llamacpp", "llama-server.exe")


def _model_already_present():
    """Check whether the GGUF model already sits at MODEL_FILE.

    A freshly-installed, unsigned exe's first filesystem access can be
    delayed for tens of seconds (antivirus scanning the new binary),
    making a naive isfile() check falsely report "missing" and trigger a
    pointless ~1.1GB re-download. Observed in practice: first launch after
    install re-downloaded, while relaunching the same (now-scanned) binary
    found the file instantly.

    So: only wait when a previous download plausibly happened (the model
    directory already exists). On a genuine first run the directory is
    absent and we skip straight to downloading with no added delay.
    """
    if os.path.isfile(MODEL_FILE):
        return True
    if not os.path.isdir(MODEL_DIR):
        return False

    for _ in range(60):
        time.sleep(1)
        if os.path.isfile(MODEL_FILE):
            return True
    return False


def _stop_llama_server():
    global llama_process
    if llama_process and llama_process.poll() is None:
        llama_process.terminate()
        try:
            llama_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            llama_process.kill()
    llama_process = None


atexit.register(_stop_llama_server)


def _load_model():
    """Download (first run only) the GGUF model and start llama-server in
    the background, so Flask can start serving immediately and report real
    progress via /api/health instead of blocking startup.
    """
    global llama_process
    try:
        if not _model_already_present():
            model_status["status"] = "downloading_model"
            os.makedirs(MODEL_DIR, exist_ok=True)
            hf_hub_download(
                repo_id=GGUF_REPO_ID,
                filename=GGUF_FILENAME,
                local_dir=MODEL_DIR,
            )

        model_status["status"] = "loading_model"
        server_exe = _llama_server_exe()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        llama_process = subprocess.Popen(
            [
                server_exe,
                "--model", MODEL_FILE,
                "--host", LLAMA_SERVER_HOST,
                "--port", str(LLAMA_SERVER_PORT),
                "--parallel", "8",
            ],
            cwd=os.path.dirname(server_exe),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        for _ in range(120):
            try:
                if requests.get(f"{LLAMA_SERVER_BASE_URL}/health", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("llama-server did not become ready in time")

        model_status["status"] = "ready"
        model_status["ready"] = True
    except Exception as exc:  # noqa: BLE001 - surface any failure via /api/health
        model_status["status"] = "error"
        model_status["error"] = str(exc)


threading.Thread(target=_load_model, daemon=True).start()


def _chat(messages, max_tokens, temperature=0.0, top_p=1.0):
    """Run one chat-formatted generation through llama-server.

    llama-server applies the GGUF's embedded Qwen chat template itself -
    no manual tokenization/padding needed here, unlike the old
    transformers-based path.
    """
    resp = requests.post(
        f"{LLAMA_SERVER_BASE_URL}/v1/chat/completions",
        json={"messages": messages, "max_tokens": max_tokens, "temperature": temperature, "top_p": top_p},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _classification_messages(product_name):
    prompt = f"""Classify this product for a sales forecasting report.

Product Name: {product_name}

Respond with ONLY a JSON object in this exact format, no other text:
{{"seasonality": "<winter|spring|summer|fall|holiday|year-round|unknown>", "category": "<short 2-4 word category description>"}}
"""
    return [
        {"role": "system", "content": "You are a product classification assistant. Respond only with valid JSON, no explanation."},
        {"role": "user", "content": prompt}
    ]


def _extract_tags(raw):
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        tags = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        tags = {}
    return {
        "seasonality": tags.get("seasonality", "unknown"),
        "category": tags.get("category", "unknown"),
    }


def classify_products_batch(product_names, max_workers=8):
    """Zero-shot classify many products' seasonality/category concurrently.

    llama-server's --parallel slots do real server-side continuous batching;
    the client just needs to fire concurrent requests to use it - a real
    throughput win, not just deferred cost (empirically ~0.3s/item at 8
    concurrent workers vs ~5.3s/item sequential). This is a stand-in for
    real product context until an actual data source (a category taxonomy,
    tariff schedule, etc.) is wired in via RAG later.
    """
    def classify_one(name):
        raw = _chat(_classification_messages(name), max_tokens=64, temperature=0.0)
        return name, _extract_tags(raw)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return dict(executor.map(classify_one, product_names))


def generate_summary(product, percent_change, forecast, last_year_sales, duration, tags, portfolio_context=None):
    """Generate a natural language inventory-flow summary using Qwen2.5-1.5B-Instruct.

    Frames the forecast as inventory movement: units forecasted to go OUT (sales)
    versus the units that should come IN (restock) to cover that demand, grounded
    in the product's inferred category/seasonality so the LLM can flag whether a
    trend looks like normal seasonal movement or an actual demand shift. When
    portfolio_context is given (this product's standing relative to the rest of
    the uploaded dataset), the LLM can also say whether it's leading or lagging
    its peers, not just its own history.
    """
    portfolio_block = f"\n- Portfolio Context: {portfolio_context}" if portfolio_context else ""

    prompt = f"""You are an expert inventory and sales forecasting analyst.

Based on the data below, write a concise, professional summary (3-5 sentences) covering:
1. Outbound inventory: how many units of this product are forecasted to leave inventory (be sold) over the period
2. Inbound inventory: how many units should be restocked/received to cover that forecasted demand without stocking out
3. How this period compares to the same period last year (trend direction and % change), and whether that looks like normal seasonal movement for this product's category or an actual demand shift
4. If portfolio context is provided, how this product is performing relative to the rest of its category in this dataset
5. Any actionable recommendation for purchasing or replenishment planning

Data:
- Product Name: {product}
- Product Category: {tags['category']}
- Seasonality: {tags['seasonality']}
- Forecast Period: {duration}
- Forecasted Units Out (Sales): {forecast}
- Last Year Actual Units Out (Sales): {last_year_sales}
- % Change from Previous Year: {percent_change}%{portfolio_block}

Write the summary in a clear, professional tone suitable for a business inventory report.
"""

    messages = [
        {"role": "system", "content": "You are a professional inventory and sales analyst. Provide concise, data-driven insights."},
        {"role": "user", "content": prompt}
    ]

    return _chat(messages, max_tokens=512, temperature=0.7, top_p=0.95)


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

    # Classify all products up front in batches (real throughput win, not
    # just deferred cost - see classify_products_batch). The narrative
    # summary itself stays on-demand per product via /api/predictions/<id>/summary.
    tags_by_product = classify_products_batch(list(products))

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
        
        product_tags = tags_by_product.get(product, {"seasonality": "unknown", "category": "unknown"})

        prediction = Prediction(
            file_id=file_record.id,
            product_name=product,
            duration=f"{forecast_start_date} - {end_date.date()}",
            forecast=str(round(sum_forecast_now)),
            actual_sales=str(round(actual_last_year_sales)),
            percent_change=str(
                (round(percent_change, 2) if percent_change != "N/A" else "N/A")
            ),
            category=product_tags["category"],
            seasonality=product_tags["seasonality"],
        )
        db.session.add(prediction)
        db.session.commit()

        # Store the result in the required format
        forecast_results.append(
            {
                "PredictionId": prediction.id,
                "ProductName": product,
                "Duration": f"{forecast_start_date} - {end_date.date()}",
                "Forecast": round(sum_forecast_now),
                "Last Year Actual Sales": round(actual_last_year_sales),
                "% Change from Previous Year": (
                    round(percent_change, 2) if percent_change != "N/A" else "N/A"
                ),
                "Category": product_tags["category"],
                "Seasonality": product_tags["seasonality"],
            }
        )

    return json.dumps(forecast_results, indent=4)


def _portfolio_context(prediction):
    """Cheap, deterministic (no LLM) aggregate stats for this product's
    category within the same uploaded dataset, to ground its summary in
    how it's doing relative to its peers, not just its own history."""
    siblings = Prediction.query.filter_by(
        file_id=prediction.file_id, category=prediction.category
    ).all()

    changes = []
    for p in siblings:
        try:
            changes.append(float(p.percent_change))
        except (TypeError, ValueError):
            continue

    if len(changes) < 2:
        return None

    up = sum(1 for c in changes if c > 0)
    down = sum(1 for c in changes if c < 0)
    avg = sum(changes) / len(changes)
    return (
        f"Within the '{prediction.category}' category in this dataset, "
        f"{len(changes)} products have a comparable prior-year figure: "
        f"{up} trending up, {down} trending down, averaging {avg:.1f}% change."
    )


def get_or_generate_summary(prediction):
    """Return prediction.summary, generating and caching it on first request."""
    if prediction.summary:
        return prediction.summary

    tags = {
        "category": prediction.category or "unknown",
        "seasonality": prediction.seasonality or "unknown",
    }

    summary = generate_summary(
        prediction.product_name,
        prediction.percent_change,
        prediction.forecast,
        prediction.actual_sales,
        prediction.duration,
        tags,
        _portfolio_context(prediction),
    )

    prediction.summary = summary
    db.session.commit()
    return summary


def _read_rows(data):
    """Read an uploaded CSV or Excel file into a list of string-keyed row dicts.

    Detects format from the filename, falling back to sniffing the ZIP
    signature all xlsx/xls files start with (in case the extension lies).
    """
    data.stream.seek(0)
    raw = data.stream.read()
    filename = (data.filename or "").lower()

    if filename.endswith((".xlsx", ".xls")) or raw[:2] == b"PK":
        df = pd.read_excel(io.BytesIO(raw))
    else:
        df = pd.read_csv(io.BytesIO(raw))

    df = df.fillna("")
    return df.astype(str).to_dict(orient="records"), [str(c) for c in df.columns]


def preprocess_data(data):
    json_data = []
    rows, headers = _read_rows(data)

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

    # Loop through each row
    for row in rows:
        product_name = row["Product Name"]

        # Loop through the years and months dynamically
        for year in range(min(years), max(years) + 1):
            for month in range(1, 13):
                # Create the header for this specific month and year (e.g., "Quantity Sold Jan 2016")
                month_name = datetime(year=year, month=month, day=1).strftime(
                    "%b %Y"
                )  # e.g., "Jan 2016"
                column_name = f"Quantity Sold {month_name}"

                # Check if this column exists for this product
                if column_name in row:
                    # Excel-sourced values stringify as e.g. "19.0", so parse
                    # via float rather than the CSV-only str.isdigit() check.
                    try:
                        quantity_sold = int(float(row[column_name]))
                    except (TypeError, ValueError):
                        continue

                    # Format the date for the 'ds' field in the required format (YYYY-MM-DD)
                    date_str = datetime(year=year, month=month, day=1).strftime(
                        "%Y-%m-%d"
                    )

                    # **Aggregate Sales for Each Product and Date**
                    key = (product_name, date_str)
                    if key in aggregated_data:
                        aggregated_data[key]["y"] += quantity_sold
                    else:
                        aggregated_data[key] = {
                            "ds": date_str,
                            "y": quantity_sold,
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
