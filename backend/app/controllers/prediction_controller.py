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
from scipy.stats import norm
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


def _trend_sentence(percent_change, forecast, last_year_sales):
    """Spell out the year-over-year direction in words for the prompt."""
    try:
        pct = float(percent_change)
    except (TypeError, ValueError):
        return (
            "No comparable prior-year period exists in this data, so there is no "
            "year-over-year change to report. Do not invent a percentage."
        )

    if pct > 0:
        return (
            f"Forecasted sales are HIGHER than last year - an INCREASE of "
            f"{abs(pct):.1f}% ({forecast} units forecast vs {last_year_sales} last year)."
        )
    if pct < 0:
        return (
            f"Forecasted sales are LOWER than last year - a DECREASE of "
            f"{abs(pct):.1f}% ({forecast} units forecast vs {last_year_sales} last year)."
        )
    return f"Forecasted sales are FLAT versus last year ({forecast} units, unchanged)."


_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")

# Dates are restated constantly ("2025-12-31", "December 31, 2025") and their
# parts would otherwise read as sales figures. Strip them before counting.
_DATE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|(?:January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4}",
    re.IGNORECASE,
)


def _numbers_in(text):
    values = set()
    for raw in _NUMBER_RE.findall(_DATE_RE.sub(" ", text)):
        try:
            values.add(abs(float(raw.replace(",", ""))))
        except ValueError:
            continue
    return values


def _unsupported_numbers(text, prompt):
    """Numbers the model wrote that aren't traceable to the prompt.

    Anything the model states that isn't in - or trivially derived from - the
    figures it was given is fabricated, however plausible it sounds. Pairwise
    differences and sums are allowed because "18 more units than last year" is
    a legitimate restatement, not an invention.
    """
    given = sorted(_numbers_in(prompt))
    supported = set(given)
    # Snapshot first: deriving from the growing set instead cascades into
    # sums of sums, which covers so much of the number line that nothing
    # ever looks fabricated.
    for i, a in enumerate(given):
        for b in given[i:]:
            supported.add(abs(a - b))
            supported.add(a + b)
    supported |= {round(v, 1) for v in list(supported)}

    unsupported = []
    for value in _numbers_in(text):
        # Ignore small integers and years: these are calendar references
        # ("3-4 sentences", "January 2025"), not factual claims about sales.
        if value <= 12 or (1900 <= value <= 2100):
            continue
        # Tolerance covers rounding, e.g. "7.21" restated as "7.2".
        if any(abs(value - s) <= max(0.15, s * 0.01) for s in supported):
            continue
        if any(abs(value - s) <= max(0.15, s * 0.01) for s in supported):
            continue
        unsupported.append(value)
    return unsupported


def _build_summary_prompt(
    product, percent_change, forecast, last_year_sales, duration, tags,
    portfolio_context=None, forecast_low=None, forecast_high=None, seasonality_note=None,
):
    """Assemble the summary prompt.

    Every line here is a fact computed from the data. The prompt deliberately
    does NOT ask for anything the data can't answer - notably a restock
    quantity, which this app has no inventory figures for, and which the model
    used to satisfy by echoing the forecast back as if it were advice.
    """
    # Direction in words rather than a signed number: a small model reads
    # "7.21%" against a larger forecast and still writes "a decrease of 7.21%"
    # a fair share of the time.
    lines = [
        f"- Product Name: {product}",
        f"- Product Category: {tags['category']}",
        f"- Forecast Period: {duration}",
        f"- Forecasted Units Sold: {forecast}",
    ]

    if forecast_low is not None and forecast_high is not None:
        lines.append(
            f"- Forecast Uncertainty Range: between {forecast_low} and {forecast_high} units "
            f"(the model's own confidence interval - the single figure above is the midpoint)"
        )

    lines.append(f"- Last Year Actual Units Sold: {last_year_sales}")
    lines.append(
        f"- Year-over-year comparison: "
        f"{_trend_sentence(percent_change, forecast, last_year_sales)}"
    )

    # Seasonality measured from this product's own sales history, not guessed
    # from its name. The name-derived tag is a label for grouping, not evidence.
    if seasonality_note:
        lines.append(f"- Observed seasonality (from this product's sales history): {seasonality_note}")

    if portfolio_context:
        lines.append(f"- Category comparison: {portfolio_context}")
        peer_rule = (
            "Comment on how this product compares with others in its category, "
            "using only the category comparison line above."
        )
    else:
        peer_rule = (
            "No category comparison is available for this product. Do not comment on "
            "how it compares with other products, and do not claim it is performing "
            "above or below average."
        )

    data_block = "\n".join(lines)

    return f"""You are an expert inventory and sales forecasting analyst.

Using only the data below, write a concise summary of 3-4 sentences covering:
1. How many units are forecasted to sell over the period, and how confident that figure is
2. How this compares with the same period last year
3. Whether the observed seasonality explains that change, or whether it looks like a real shift in demand
4. One practical implication for purchasing or replenishment planning

Rules:
- Use only the figures given below. Do not introduce any other numbers.
- State the direction of change exactly as given. Never describe an increase as a decrease, or a decrease as an increase.
- {peer_rule}
- Do not recommend a specific restock quantity: no inventory or stock-on-hand data is available here.

Data:
{data_block}

Write in a clear, professional tone suitable for a business inventory report."""


def generate_summary(
    product, percent_change, forecast, last_year_sales, duration, tags,
    portfolio_context=None, forecast_low=None, forecast_high=None, seasonality_note=None,
):
    """Write a grounded narrative for one product's forecast.

    Returns (summary_text, unsupported_numbers). Sampling is near-greedy: this
    is factual summarisation of supplied figures, and the creative-writing
    defaults this inherited (temperature 0.7, a 512-token budget for "3-5
    sentences") gave the model both licence and room to invent.
    """
    prompt = _build_summary_prompt(
        product, percent_change, forecast, last_year_sales, duration, tags,
        portfolio_context, forecast_low, forecast_high, seasonality_note,
    )
    messages = [
        {"role": "system", "content": "You are a professional inventory and sales analyst. Provide concise, data-driven insights."},
        {"role": "user", "content": prompt},
    ]

    best = None
    for _ in range(2):  # one retry when the model reaches for numbers it wasn't given
        text = _chat(messages, max_tokens=220, temperature=0.2, top_p=0.9)
        unsupported = _unsupported_numbers(text, prompt)
        if not unsupported:
            return text, []
        if best is None or len(unsupported) < len(best[1]):
            best = (text, unsupported)

    return best


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
        forecast_low, forecast_high = _aggregate_interval(m, forecast, sum_forecast_now)

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
            forecast_low=str(round(forecast_low)),
            forecast_high=str(round(forecast_high)),
            seasonality_note=_seasonality_note(df_product),
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


def _aggregate_interval(model, forecast, total):
    """Confidence interval for the summed forecast, not the sum of intervals.

    Adding up each month's yhat_lower and yhat_upper describes the case where
    every single month lands at its extreme together, which produced absurd
    ranges in practice (9 to 517 units around a 261 forecast). Combining the
    monthly spreads in quadrature instead treats the month-to-month errors as
    largely independent, which understates correlated trend error but is far
    closer to the truth than the naive sum.
    """
    try:
        z = norm.ppf(0.5 + model.interval_width / 2)
        sigmas = (forecast["yhat_upper"] - forecast["yhat_lower"]) / (2 * z)
        spread = z * float(np.sqrt((sigmas**2).sum()))
    except Exception:  # noqa: BLE001 - fall back to the raw bounds
        return forecast["yhat_lower"].sum(), forecast["yhat_upper"].sum()

    return max(0.0, total - spread), total + spread


MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _seasonality_note(df_product):
    """Describe this product's seasonality from its actual sales history.

    The category/seasonality tag elsewhere is inferred from the product *name*,
    so asking the model to judge "seasonal swing or real demand shift" against
    that tag is circular - it would be checking its own earlier guess. This
    measures the swing from the real monthly numbers instead.
    """
    if df_product.empty:
        return None

    monthly = df_product.groupby(df_product["ds"].dt.month)["y"].mean()
    if len(monthly) < 6 or monthly.max() <= 0:
        return None

    peak_month = MONTH_NAMES[int(monthly.idxmax()) - 1]
    trough_month = MONTH_NAMES[int(monthly.idxmin()) - 1]
    peak, trough, avg = monthly.max(), monthly.min(), monthly.mean()

    swing = (peak - trough) / avg if avg else 0
    if swing < 0.5:
        strength = "steady through the year, with little seasonal variation"
    elif swing < 1.5:
        strength = "moderately seasonal"
    else:
        strength = "strongly seasonal"

    return (
        f"{strength}; historically peaks in {peak_month} (~{peak:.0f} units/month) "
        f"and bottoms out in {trough_month} (~{trough:.0f} units/month)"
    )


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
    """Return (summary, unverified) for a prediction, caching on first request.

    `unverified` is True when the generated text contains figures that can't be
    traced back to the data it was given - the caller can flag it rather than
    presenting a possibly-invented number as fact.
    """
    if prediction.summary:
        return prediction.summary, bool(prediction.summary_unverified)

    tags = {
        "category": prediction.category or "unknown",
        "seasonality": prediction.seasonality or "unknown",
    }

    summary, unsupported = generate_summary(
        prediction.product_name,
        prediction.percent_change,
        prediction.forecast,
        prediction.actual_sales,
        prediction.duration,
        tags,
        _portfolio_context(prediction),
        prediction.forecast_low,
        prediction.forecast_high,
        prediction.seasonality_note,
    )

    prediction.summary = summary
    prediction.summary_unverified = bool(unsupported)
    db.session.commit()
    return summary, bool(unsupported)


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
