import json
import csv
from datetime import datetime
import re
from prophet import Prophet
import pandas as pd
import numpy as np
from app.models.prediction import Prediction
from app.models.file import File
from app.extensions import db
from transformers import GPT2LMHeadModel, GPT2Tokenizer
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "gpt2")
tokenizer = GPT2Tokenizer.from_pretrained(MODEL_PATH)
model = GPT2LMHeadModel.from_pretrained(MODEL_PATH)
model.config.pad_token_id = model.config.eos_token_id
status = True


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
        
        generated_text = ""
        if not status:
            prompt = f"""
            Here is the sales forecasting data for a product:

                Product Name: {product}
            - % Change from Previous Year: {round(percent_change, 2) if percent_change != "N/A" else "N/A"}%
            - Forecast: {round(sum_forecast_now)}
            - Last Year Actual Sales: {round(actual_last_year_sales)}
            - Duration: {forecast_start_date} - {end_date.date()}

            Please provide a short summary that highlights the key trends in sales forecasts, including notable changes in forecasted sales and product performance.
            """
            input_ids = tokenizer.encode(prompt, return_tensors="pt")
            attention_mask = (input_ids != model.config.pad_token_id).type(
                input_ids.dtype
            )

            # Generate the output with parameters to control repetition and randomness
            output = model.generate(
                input_ids,
                attention_mask=attention_mask,  # Pass attention mask
                num_return_sequences=1,
                do_sample=True,  # Enable sampling
                temperature=0.9,  # Lower temperature for more focused output
                max_length=1500,  # Shorter max length for concise output
                top_p=0.9,  # Nucleus sampling for more diverse outputs
                top_k=50,  # Limit the pool of possible next tokens
                no_repeat_ngram_size=2,  # Avoid repeating n-grams
                pad_token_id=model.config.pad_token_id,  # Ensure padding token is eos token
            )

            # Decode the generated output
            generated_text = tokenizer.decode(output[0], skip_special_tokens=True)
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
