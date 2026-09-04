import json
import io
from datetime import datetime
import re
import threading
import time
import subprocess
import atexit
import sys
import socket
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import requests
import pandas as pd
import numpy as np
from app.models.prediction import Prediction
from app.models.file import File
from app.extensions import db
from app.forecasting import selector, elasticity as elasticity_mod
from app.forecasting.base import (
    aggregate_interval, future_index, monthly_actuals, period_actuals, MONTHLY,
)
from huggingface_hub import hf_hub_download
import os

GGUF_REPO_ID = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
GGUF_FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"

LLAMA_SERVER_HOST = "127.0.0.1"

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
# Chosen fresh each startup rather than hardcoded. A crashed or force-killed
# app leaves an orphaned llama-server still holding its port; with a fixed
# port, the next launch's health check would go green against that stale
# process - reporting "ready" in ~0s while silently doing all its inference
# through a server this app doesn't own (possibly from an entirely different
# build). An ephemeral port makes that collision impossible.
llama_server_port = None
# Job-object handle kept alive for the life of this process: the job is set to
# kill its members when its last handle closes, so this global MUST stay
# referenced or llama-server would be killed the moment it's garbage-collected.
llama_job = None
model_status = {"status": "starting", "ready": False, "error": None}


def _bind_child_to_process_lifetime(process):
    """Tie llama-server's lifetime to this backend via a Windows job object,
    so the OS kills it whenever run.exe exits - including a force-kill that
    skips atexit and Electron's taskkill. An installer force-kills the running
    app to swap files, which otherwise orphans llama-server (a real leak seen
    in testing). Returns the job handle, which the CALLER MUST keep referenced
    (see llama_job) - the job kills its members when its last handle closes,
    so letting it be collected would immediately kill the child. Best-effort:
    returns None off Windows or on any API failure, where the graceful
    atexit/taskkill cleanup still covers the normal shutdown path.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9
        ULONG_PTR = ctypes.c_size_t

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ULONG_PTR),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

        return job
    except Exception:  # noqa: BLE001 - best effort; graceful cleanup still applies
        return None


def _llama_base_url():
    return f"http://{LLAMA_SERVER_HOST}:{llama_server_port}"


def _free_port():
    """Ask the OS for an unused port, then hand it to llama-server.

    There's a small race between closing this socket and llama-server
    binding it, but the readiness check below verifies our own child is
    alive and serving, so a lost race surfaces as a clear startup error
    rather than a silent misconnection.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LLAMA_SERVER_HOST, 0))
        return sock.getsockname()[1]


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
    global llama_process, llama_server_port, llama_job
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
        llama_server_port = _free_port()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        llama_process = subprocess.Popen(
            [
                server_exe,
                "--model", MODEL_FILE,
                "--host", LLAMA_SERVER_HOST,
                "--port", str(llama_server_port),
                "--parallel", "8",
            ],
            cwd=os.path.dirname(server_exe),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        # Held in a module global so the OS tears down llama-server if this
        # backend is force-killed (installer swap) without a graceful stop.
        llama_job = _bind_child_to_process_lifetime(llama_process)

        for _ in range(120):
            # Check our own child first: a healthy response from a server we
            # didn't spawn is not success, and if our process died there's
            # nothing to wait for - fail now with the exit code rather than
            # polling a port someone else may answer on.
            if llama_process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited during startup (code {llama_process.returncode})"
                )
            try:
                if requests.get(f"{_llama_base_url()}/health", timeout=2).status_code == 200:
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


# Bootstrap the LLM in the background unless explicitly skipped (tests /
# forecast-only usage that don't need summaries). Skipping avoids downloading
# and spawning llama-server.
if os.getenv("INSIGHTA_SKIP_LLM") != "1":
    threading.Thread(target=_load_model, daemon=True).start()


def _chat(messages, max_tokens, temperature=0.0, top_p=1.0):
    """Run one chat-formatted generation through llama-server.

    llama-server applies the GGUF's embedded Qwen chat template itself -
    no manual tokenization/padding needed here, unlike the old
    transformers-based path.
    """
    resp = requests.post(
        f"{_llama_base_url()}/v1/chat/completions",
        json={"messages": messages, "max_tokens": max_tokens, "temperature": temperature, "top_p": top_p},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _context_lines(sku=None, extra_context=None):
    """Format a SKU and any extra file-provided columns (price, rating, brand,
    whatever a given upload happens to include beyond name/SKU/quantities) as
    labeled data lines, so per-SKU calls have real signal to differentiate on
    instead of a repeated generic product name."""
    lines = []
    if sku:
        lines.append(f"- SKU: {sku}")
    for key, value in (extra_context or {}).items():
        if value:
            lines.append(f"- {key}: {value}")
    return lines


def _classification_messages(product_name, sku=None, extra_context=None):
    context_block = "\n".join(_context_lines(sku, extra_context))
    if context_block:
        context_block = "\n" + context_block

    prompt = f"""Classify this product for a sales forecasting report.

Product Name: {product_name}{context_block}

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


def classify_products_batch(items, max_workers=8):
    """Zero-shot classify many products' seasonality/category concurrently.

    Runs one call per item (per SKU, not collapsed to distinct product
    names) so two SKUs sharing a generic name can still classify
    differently whenever the file gives them something to differ on (SKU
    code, price, rating, whatever else is present) - collapsing by name
    would erase exactly that distinction. llama-server's --parallel slots
    do real server-side continuous batching; the client just needs to fire
    concurrent requests to use it - a real throughput win, not just
    deferred cost (empirically ~0.3s/item at 8 concurrent workers vs
    ~5.3s/item sequential). This is a stand-in for real product context
    until an actual data source (a category taxonomy, tariff schedule,
    etc.) is wired in via RAG later.

    `items`: list of dicts with keys "key" (unique grouping id to return
    results under), "product_name", and optionally "sku"/"extra_context".
    """
    def classify_one(item):
        messages = _classification_messages(
            item["product_name"], item.get("sku"), item.get("extra_context")
        )
        raw = _chat(messages, max_tokens=64, temperature=0.0)
        return item["key"], _extract_tags(raw)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return dict(executor.map(classify_one, items))


def _cached_tags(has_sku, group_col, products, extra_context_by_group):
    """Reuse classification results from earlier runs for products/SKUs
    already seen before, so re-running the same catalog (a different date
    range, a different duration) doesn't re-hit the LLM for products that
    haven't changed. A cache hit requires the SKU (or product name, for
    files with no SKU column) AND its extra file context (Category, and
    whatever else a future file provides) to match exactly - if either
    differs, it's treated as unseen and classified fresh, since stale
    per-SKU signal is exactly what per-SKU classification exists to avoid.

    Returns (tags_by_group, group_keys_still_needing_classification).
    """
    keys = list(products)
    if not keys:
        return {}, []

    column = Prediction.sku if has_sku else Prediction.product_name
    rows = (
        Prediction.query.filter(column.in_(keys))
        .order_by(Prediction.created_at.desc())
        .all()
    )

    most_recent = {}
    for row in rows:
        key = row.sku if has_sku else row.product_name
        most_recent.setdefault(key, row)  # rows are newest-first

    tags_by_group = {}
    to_classify = []
    for group_key in products:
        row = most_recent.get(group_key)
        current_extra = extra_context_by_group.get(group_key, {})
        if row is not None:
            try:
                cached_extra = json.loads(row.extra_context) if row.extra_context else {}
            except (TypeError, ValueError):
                cached_extra = {}
            if cached_extra == current_extra:
                tags_by_group[group_key] = {
                    "category": row.category or "unknown",
                    "seasonality": row.seasonality or "unknown",
                }
                continue
        to_classify.append(group_key)

    return tags_by_group, to_classify


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
    sku=None, extra_context=None,
):
    """Assemble the summary prompt.

    Every line here is a fact computed from the data. The prompt deliberately
    does NOT ask for anything the data can't answer - notably a restock
    quantity, which this app has no inventory figures for, and which the model
    used to satisfy by echoing the forecast back as if it were advice. The
    same rule applies to sku/extra_context: they're included so the model can
    reference real per-SKU signal (a price column, a rating, whatever the
    file happens to provide) when it exists, not so it can invent a tier or
    reputation the data never stated.
    """
    # Direction in words rather than a signed number: a small model reads
    # "7.21%" against a larger forecast and still writes "a decrease of 7.21%"
    # a fair share of the time.
    lines = [
        f"- Product Name: {product}",
        *_context_lines(sku, {k: v for k, v in (extra_context or {}).items() if k != "Category"}),
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
    sku=None, extra_context=None,
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
        sku, extra_context,
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


# A SKU needs ~2 years of monthly data before a model can learn its own yearly
# shape; below this it forecasts nearly flat, so thin SKUs take the borrowed-
# shape cold-start path instead of the ensemble.
SUFFICIENT_HISTORY_MONTHS = 24
# Only SKUs with a full, repeated yearly cycle contribute to a pooled shape.
MIN_POOL_MONTHS = 24

# Maps the LLM's name-derived seasonality tag (the model's offline world
# knowledge - a "space heater" is winter, "sunscreen" is summer) to the
# calendar months a product like that peaks in. Used only as a last-resort
# prior when a thin SKU has no siblings to borrow a measured shape from.
SEASON_TO_PEAK_MONTHS = {
    "winter": [12, 1, 2],
    "spring": [3, 4, 5],
    "summer": [6, 7, 8],
    "fall": [9, 10, 11],
    "holiday": [11, 12],
}


def _monthly_seasonal_index(df_group):
    """A normalized 12-month seasonal shape (month -> multiplier around 1.0)
    from a group's history, or None if there's no meaningful yearly signal. A
    multiplier of 1.4 means that month runs 40% above the group's average
    month; months never observed default to a neutral 1.0."""
    if df_group.empty:
        return None
    monthly = df_group.groupby(df_group["ds"].dt.month)["y"].mean()
    if len(monthly) < 6 or monthly.mean() <= 0:
        return None
    overall = monthly.mean()
    observed = {int(m): float(v / overall) for m, v in monthly.items()}
    return {m: observed.get(m, 1.0) for m in range(1, 13)}


def _average_indices(index_list):
    """Pool several per-SKU seasonal indices into one, renormalized to mean 1
    so it only redistributes volume across the year without inflating the
    annual total."""
    if not index_list:
        return None
    summed = {m: sum(ix[m] for ix in index_list) / len(index_list) for m in range(1, 13)}
    mean = sum(summed.values()) / 12
    if mean <= 0:
        return None
    return {m: summed[m] / mean for m in range(1, 13)}


def _prior_index_from_season(season_tag):
    """Last-resort seasonal shape from the LLM's season tag, for a thin SKU
    with no siblings to learn from. Deliberately gentle (a modest peak-month
    lift, not a hard spike) since it's a type-level guess, not measured."""
    peaks = SEASON_TO_PEAK_MONTHS.get((season_tag or "").lower())
    if not peaks:
        return None  # year-round / unknown -> impose no shape
    raw = {m: (1.6 if m in peaks else 1.0) for m in range(1, 13)}
    mean = sum(raw.values()) / 12
    return {m: raw[m] / mean for m in range(1, 13)}


def predict_sales_forecasting(data, start_date, duration):
    """Forecast from an uploaded file (stores the file blob, then forecasts)."""
    file_data = data.read()

    file_record = File(filename=data.filename, filedata=file_data)
    db.session.add(file_record)
    # flush (not commit): assigns file_record.id within the open transaction
    # without fsyncing yet - the whole request commits once, at the end.
    db.session.flush()

    json_data, extra_context_by_group = preprocess_data(data)
    return _forecast_core(
        json_data, extra_context_by_group, start_date, duration, file_id=file_record.id
    )


def predict_from_catalog(start_date, duration):
    """Forecast the persistent catalog - the stored business is the source of
    truth, so no upload is needed. Grain (weekly for daily data, else monthly)
    is detected from the catalog."""
    from app.controllers.catalog_controller import catalog_to_json_data

    json_data, extra_context_by_group, grain = catalog_to_json_data()
    if not json_data:
        return json.dumps([])
    return _forecast_core(
        json_data, extra_context_by_group, start_date, duration, file_id=None, grain=grain
    )


def _forecast_core(json_data, extra_context_by_group, start_date, duration,
                   file_id=None, grain=MONTHLY):
    """Shared forecasting pipeline over already-parsed data, whichever source it
    came from (an upload or the stored catalog) and at whichever grain."""
    forecast_periods = duration
    forecast_start_date = start_date
    # The same window one year back, for the year-over-year comparison.
    last_year_start = pd.Timestamp(start_date) - pd.DateOffset(years=1)

    df = pd.DataFrame(json_data)

    # Ensure the date column is in datetime format
    df["ds"] = pd.to_datetime(df["ds"], format="%Y-%m-%d")

    # Group by SKU when the file provides one (each SKU forecast
    # separately - two SKUs sharing a generic product name, e.g. two
    # different bicycle models, are different products), falling back to
    # product name for files with no SKU column.
    has_sku = df["sku"].astype(bool).any()
    group_col = "sku" if has_sku else "product_name"
    products = df[group_col].unique()

    # Classify every SKU individually (not collapsed by name) so real
    # per-SKU signal - the SKU code itself, plus any extra columns the file
    # provides - can differentiate products that happen to share a name.
    # See classify_products_batch for why this stays cheap at SKU scale.
    # Products already classified in an earlier run (same SKU, same extra
    # context) reuse that result instead of hitting the LLM again - the
    # dominant cost at catalog scale, and pure waste for a re-run of the
    # same file with a different date range or duration.
    tags_by_group, groups_needing_classification = _cached_tags(
        has_sku, group_col, products, extra_context_by_group
    )
    if groups_needing_classification:
        classification_items = []
        for group_key in groups_needing_classification:
            df_g = df[df[group_col] == group_key]
            classification_items.append({
                "key": group_key,
                "product_name": df_g["product_name"].iloc[0],
                "sku": df_g["sku"].iloc[0] if has_sku else None,
                "extra_context": extra_context_by_group.get(group_key, {}),
            })
        tags_by_group.update(classify_products_batch(classification_items))

    # Decide each SKU's seasonal shape before fitting - the offline "smart out
    # of the box" logic. A SKU with enough history learns its own yearly shape;
    # a thin/new one borrows the measured shape of its category siblings, or -
    # if even the category is thin - falls back to the seasonal prior implied
    # by the LLM's world-knowledge tag. This is what lets a brand-new "winter
    # jacket" forecast a winter peak instead of flat. _fit_forecast applies the
    # chosen index; None means "enough history, use its own seasonality".
    category_by_group = {}
    own_months_by_group = {}
    for group_key in products:
        tags = tags_by_group.get(group_key, {})
        category_by_group[group_key] = (
            extra_context_by_group.get(group_key, {}).get("Category")
            or tags.get("category")
            or "unknown"
        )
        own_months_by_group[group_key] = len(df[df[group_col] == group_key])

    seasonal_index_by_group = {}
    method_by_group = {}
    if grain is MONTHLY:
        per_category_indices = defaultdict(list)
        all_indices = []
        for group_key in products:
            if own_months_by_group[group_key] >= MIN_POOL_MONTHS:
                idx = _monthly_seasonal_index(df[df[group_col] == group_key])
                if idx:
                    per_category_indices[category_by_group[group_key]].append(idx)
                    all_indices.append(idx)
        pooled_by_category = {c: _average_indices(v) for c, v in per_category_indices.items()}
        pooled_all = _average_indices(all_indices)
        for group_key in products:
            season_tag = tags_by_group.get(group_key, {}).get("seasonality", "unknown")
            if own_months_by_group[group_key] >= SUFFICIENT_HISTORY_MONTHS:
                seasonal_index_by_group[group_key], method_by_group[group_key] = None, "own history"
            elif pooled_by_category.get(category_by_group[group_key]):
                seasonal_index_by_group[group_key] = pooled_by_category[category_by_group[group_key]]
                method_by_group[group_key] = "category seasonality"
            elif pooled_all:
                seasonal_index_by_group[group_key], method_by_group[group_key] = pooled_all, "overall seasonality"
            elif _prior_index_from_season(season_tag):
                seasonal_index_by_group[group_key] = _prior_index_from_season(season_tag)
                method_by_group[group_key] = f"seasonal prior ({season_tag})"
            else:
                seasonal_index_by_group[group_key], method_by_group[group_key] = None, "limited history"
    else:
        # Weekly: mature SKUs learn their own 52-week seasonality; cold-start
        # SKUs use a flat borrowed level (weekly seasonal-shape borrowing is a
        # later refinement).
        for group_key in products:
            enough = own_months_by_group[group_key] >= grain.sufficient_history
            method_by_group[group_key] = "own history" if enough else "limited history"

    # Forecast every SKU: an ensemble of fast statistical models + a global
    # LightGBM for mature SKUs, borrowed-shape for thin ones. All batched, so
    # this whole phase is a handful of vectorized calls, not a per-SKU fit
    # loop (see app/forecasting/selector.py).
    forecasts = selector.run_forecast(
        df, group_col, list(products), forecast_start_date, forecast_periods,
        category_by_group, own_months_by_group, seasonal_index_by_group, grain,
    )
    end_ts = grain.future_index(forecast_start_date, forecast_periods).max()
    end_date = (end_ts + pd.offsets.MonthEnd(0)) if grain is MONTHLY else end_ts

    # Price elasticity per SKU (only when the file carries monthly prices);
    # powers the "what-if a price change" figure client-side.
    elasticity_by_group = elasticity_mod.estimate_all(
        df, group_col, list(products), category_by_group
    )

    # Prepare forecast results storage
    forecast_results = []

    # Assemble each product/SKU's prediction from its forecast
    for group_key in products:
        # Filter dataset for the current product/SKU
        df_product = df[df[group_col] == group_key]
        product = df_product["product_name"].iloc[0]
        sku = df_product["sku"].iloc[0] if has_sku else None
        extra_context = extra_context_by_group.get(group_key, {})

        model_label, fc = forecasts[group_key]
        sum_forecast_now = fc.total
        forecast_low, forecast_high = aggregate_interval(fc)

        ly_keys = {grain.period_key(d) for d in grain.future_index(last_year_start, forecast_periods)}
        in_window = df_product["ds"].apply(lambda d: grain.period_key(d) in ly_keys)

        actual_sales_values = df_product.loc[in_window, "y"].tolist()
        # Require the full comparison window, not just some overlap. A
        # 24-month forecast whose "last year" window only has 12 real months
        # (the other 12 fall past the file's history) used to silently sum
        # just those 12 and present it as if it were a matching period -
        # comparing a 24-month forecast against half a lookback window,
        # which inflated every "% change" by roughly 2x. Partial coverage is
        # treated the same as no coverage: N/A, not a misleading number.
        has_full_comparison = len(actual_sales_values) == forecast_periods
        actual_last_year_sales = sum(actual_sales_values) if has_full_comparison else 0

        # Calculate percentage change correctly
        percent_change = (
            ((sum_forecast_now - actual_last_year_sales) / abs(actual_last_year_sales))
            * 100
            if has_full_comparison and actual_last_year_sales != 0
            else "N/A"
        )
        
        product_tags = tags_by_group.get(group_key, {"seasonality": "unknown", "category": "unknown"})
        # A real Category column beats an LLM guess - no reason to make the
        # model re-derive something the file already states.
        category = extra_context.get("Category") or product_tags["category"]
        history_months = len(df_product)
        has_data_gap = _has_data_gap(df_product)

        prediction = Prediction(
            file_id=file_id,
            product_name=product,
            sku=sku,
            duration=f"{forecast_start_date} - {end_date.date()}",
            forecast=str(round(sum_forecast_now)),
            actual_sales=str(round(actual_last_year_sales)),
            percent_change=str(
                (round(percent_change, 2) if percent_change != "N/A" else "N/A")
            ),
            category=category,
            seasonality=product_tags["seasonality"],
            forecast_low=str(round(forecast_low)),
            forecast_high=str(round(forecast_high)),
            seasonality_note=_seasonality_note(df_product),
            history_months=history_months,
            has_data_gap=has_data_gap,
            forecast_method=method_by_group.get(group_key),
            forecast_model=model_label,
            extra_context=json.dumps(extra_context) if extra_context else None,
        )
        db.session.add(prediction)
        # flush, not commit: assigns prediction.id (needed below) but skips
        # the fsync-per-row cost - previously the dominant cost of this loop
        # once catalogs reached SKU scale (hundreds of individual commits).
        # One real commit happens after the loop.
        db.session.flush()

        # Store the result in the required format
        forecast_results.append(
            {
                "PredictionId": prediction.id,
                "ProductName": product,
                "Sku": sku,
                "Duration": f"{forecast_start_date} - {end_date.date()}",
                "Forecast": round(sum_forecast_now),
                "ForecastLow": round(forecast_low),
                "ForecastHigh": round(forecast_high),
                "Last Year Actual Sales": round(actual_last_year_sales),
                "% Change from Previous Year": (
                    round(percent_change, 2) if percent_change != "N/A" else "N/A"
                ),
                "Category": category,
                "Seasonality": product_tags["seasonality"],
                "HistoryMonths": history_months,
                "HasDataGap": has_data_gap,
                "ForecastMethod": method_by_group.get(group_key),
                "ForecastModel": model_label,
                "Elasticity": (
                    round(elasticity_by_group.get(group_key, (None, None))[0], 2)
                    if elasticity_by_group.get(group_key, (None, None))[0] is not None
                    else None
                ),
                "ElasticitySource": elasticity_by_group.get(group_key, (None, None))[1],
            }
        )

    db.session.commit()
    return json.dumps(forecast_results, indent=4)


def _has_data_gap(df_product):
    """Flag an interior run of 2+ zero-sales months in a product's history.

    Leading/trailing zeros (before launch, after discontinuation) are normal
    and not flagged - only zeros sandwiched between real activity, which
    usually mean a stockout rather than genuine zero demand. Prophet can't
    tell the difference, so this is surfaced for the user to judge instead.
    """
    values = df_product.sort_values("ds")["y"].tolist()

    first_nonzero = next((i for i, v in enumerate(values) if v > 0), None)
    last_nonzero = next((i for i in range(len(values) - 1, -1, -1) if values[i] > 0), None)
    if first_nonzero is None or last_nonzero is None or first_nonzero >= last_nonzero:
        return False

    run = 0
    for v in values[first_nonzero : last_nonzero + 1]:
        run = run + 1 if v == 0 else 0
        if run >= 2:
            return True
    return False


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

    try:
        extra_context = json.loads(prediction.extra_context) if prediction.extra_context else {}
    except (TypeError, ValueError):
        extra_context = {}

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
        prediction.sku,
        extra_context,
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


SKU_COLUMN = "Product ID (SKU)"


def inspect_data(data):
    """Cheap first pass over an upload: just the span of dated sales columns.

    Lets the UI build start-date pickers from the file's real coverage instead
    of guessing a year range - so the Accuracy tab can only pick months that
    actually exist to backtest against, and the Forecast tab knows where history
    ends. Returns {min_year, min_month, max_year, max_month} or None if the file
    has no recognisable "Quantity Sold {Mon} {Year}" columns.
    """
    _, headers = _read_rows(data)
    months = []
    for header in headers:
        m = re.match(r"Quantity Sold (\w+) (\d{4})", header)
        if not m:
            continue
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%b %Y")
        except ValueError:
            continue
        months.append((dt.year, dt.month))
    if not months:
        return None
    lo, hi = min(months), max(months)
    return {
        "min_year": lo[0], "min_month": lo[1],
        "max_year": hi[0], "max_month": hi[1],
    }


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

    # Optional monthly unit-price columns ("Unit Price Jan 2016") parallel to
    # the quantity columns - the time-varying price the elasticity estimator
    # needs. Kept out of extra_columns so 60 price columns don't pollute the
    # per-SKU context.
    price_columns = [h for h in headers if re.match(r"Unit Price \w+ \d{4}", h)]

    has_sku_column = SKU_COLUMN in headers
    # Any column that isn't the name, the SKU, or a dated quantity/price column
    # is per-SKU context the file happens to provide (Category, a static list
    # price, a rating, ...) - flows through generically with no code changes.
    extra_columns = [
        h for h in headers
        if h not in sales_columns and h not in price_columns
        and h not in ("Product Name", SKU_COLUMN)
    ]

    # Dictionary to store aggregated sales
    aggregated_data = {}
    extra_context_by_group = {}

    # Loop through each row
    for row in rows:
        product_name = row["Product Name"]
        sku = row.get(SKU_COLUMN, "").strip() if has_sku_column else ""
        group_key = sku or product_name

        if group_key not in extra_context_by_group:
            extra_context_by_group[group_key] = {
                col: row[col] for col in extra_columns if row.get(col, "")
            }

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

                    price_col = f"Unit Price {month_name}"
                    price = None
                    if price_col in row:
                        try:
                            price = float(row[price_col])
                        except (TypeError, ValueError):
                            price = None

                    # **Aggregate Sales for Each Product/SKU and Date**
                    key = (group_key, date_str)
                    if key in aggregated_data:
                        aggregated_data[key]["y"] += quantity_sold
                    else:
                        aggregated_data[key] = {
                            "ds": date_str,
                            "y": quantity_sold,
                            "product_name": product_name,
                            "sku": sku,
                            "price": price,
                        }

    # Convert aggregated data dictionary to a list
    json_data = list(aggregated_data.values())

    return json_data, extra_context_by_group


def calculate_error_metrics(data, start_date, duration):
    """Backtest accuracy from an uploaded file."""
    json_data, extra_context_by_group = preprocess_data(data)
    return _error_metrics_core(json_data, extra_context_by_group, start_date, duration)


def calculate_error_metrics_from_catalog(start_date, duration):
    """Backtest accuracy on the stored catalog, at the catalog's grain."""
    from app.controllers.catalog_controller import catalog_to_json_data

    json_data, extra_context_by_group, grain = catalog_to_json_data()
    if not json_data:
        return json.dumps([])
    return _error_metrics_core(json_data, extra_context_by_group, start_date, duration, grain)


def _error_metrics_core(json_data, extra_context_by_group, start_date, duration, grain=MONTHLY):
    """Train only on data before start_date, forecast the period, and score
    against what actually happened. Uses the SAME ensemble the app forecasts
    with (app/forecasting/selector.py), so the Accuracy tab measures the real
    model - and it's batched, so this is fast instead of a per-product loop."""
    horizon = duration

    full_df = pd.DataFrame(json_data)
    full_df["ds"] = pd.to_datetime(full_df["ds"], format="%Y-%m-%d")
    has_sku = full_df["sku"].astype(bool).any()
    group_col = "sku" if has_sku else "product_name"

    cutoff = pd.to_datetime(start_date)
    train_df = full_df[full_df["ds"] < cutoff]
    products = [
        g for g in full_df[group_col].unique()
        if not train_df[train_df[group_col] == g].empty
    ]
    if not products:
        return json.dumps([], indent=4)

    category_by_group = {
        g: (extra_context_by_group.get(g, {}).get("Category") or "unknown") for g in products
    }
    history_by = {g: int((train_df[group_col] == g).sum()) for g in products}
    forecasts = selector.run_forecast(
        train_df, group_col, products, start_date, horizon,
        category_by_group, history_by, {}, grain,
    )

    end_ts = grain.future_index(start_date, horizon).max()
    end_date = (end_ts + pd.offsets.MonthEnd(0)) if grain is MONTHLY else end_ts
    error_results = []
    for g in products:
        df_g = full_df[full_df[group_col] == g]
        actual_arr = period_actuals(df_g, start_date, horizon, grain)
        yhat_arr = np.asarray(forecasts[g][1].yhat, dtype=float)

        mae = np.mean(np.abs(yhat_arr - actual_arr))
        rmse = np.sqrt(np.mean((yhat_arr - actual_arr) ** 2))
        with np.errstate(divide="ignore", invalid="ignore"):
            mape = np.mean(
                np.where(actual_arr != 0, np.abs((yhat_arr - actual_arr) / actual_arr), 0)
            ) * 100

        error_results.append(
            {
                "ProductName": df_g["product_name"].iloc[0],
                "Duration": f"{start_date} - {end_date.date()}",
                "Forecast": float(round(yhat_arr.sum(), 2)),
                "Actual Sales": float(round(actual_arr.sum(), 2)),
                "Error Metrics": {
                    "MAE": float(round(mae, 2)),
                    "RMSE": float(round(rmse, 2)),
                    "MAPE": f"{float(round(mape, 2))}%",
                },
            }
        )
    return json.dumps(error_results, indent=4)
