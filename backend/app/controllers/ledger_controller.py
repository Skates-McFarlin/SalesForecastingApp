"""Decision & outcome ledger - Phase 1.

Every catalog forecast is snapshotted here (what the app recommended), and once
real sales cover a run's forecast window, that run is reconciled against what
actually sold. This is the record the self-correcting loop (Phase 5) will learn
from - and, immediately, an honest track record of the app's accuracy on the
user's own business rather than a synthetic backtest.

The outcome measured at this phase is realized sales vs forecast. Stockout /
overstock outcomes wait for Phase 2, which adds real inventory state (on-hand,
lead time) - there's nothing to measure them against yet.
"""
from datetime import datetime

import numpy as np
import pandas as pd

from app.extensions import db
from app.models.forecast_run import ForecastRun
from app.models.ledger_item import LedgerItem
from app.forecasting.base import MONTHLY, WEEKLY, period_actuals

# The service level the recorded "recommended order" is computed at - the app's
# headline recommendation (matches the UI default). The user can still explore
# other service levels live; the ledger records this one as the decision.
DEFAULT_SERVICE_LEVEL = 0.95
_Z80_HALF = 1.2816  # upper half-width of the ~80% conformal band, in sigmas
_SERVICE_Z = {0.9: 1.2816, 0.95: 1.6449, 0.99: 2.3263}


def _grain_for(label):
    return WEEKLY if label == "weekly" else MONTHLY


def _recommend(forecast, low, high, z):
    """Port of the UI's recommendation(): expected demand + z*sigma safety
    stock, with sigma recovered from the ~80% conformal band. Kept identical so
    the ledger records the same number the user saw."""
    try:
        forecast = float(forecast)
        low = float(low)
        high = float(high)
    except (TypeError, ValueError):
        try:
            return round(float(forecast)), 0.0
        except (TypeError, ValueError):
            return 0.0, 0.0
    if not (np.isfinite(low) and np.isfinite(high)) or high <= low:
        return round(forecast), 0.0
    sigma = (high - low) / (2 * _Z80_HALF)
    safety = z * sigma
    return round(forecast + safety), round(safety)


def record_run(forecast_results, start_date, horizon, grain,
               catalog_products=None, catalog_date_to=None):
    """Snapshot a catalog forecast into the ledger.

    `forecast_results` is the list of per-SKU dicts _forecast_core produced.
    Best-effort: a ledger write must never break a forecast the user asked for,
    so any failure rolls back quietly and returns None.
    """
    try:
        z = _SERVICE_Z.get(DEFAULT_SERVICE_LEVEL, 1.6449)
        run = ForecastRun(
            grain=grain.label,
            start_date=pd.to_datetime(start_date).date(),
            horizon=int(horizon),
            service_level=DEFAULT_SERVICE_LEVEL,
            catalog_products=catalog_products,
            catalog_date_to=(
                pd.to_datetime(catalog_date_to).date() if catalog_date_to else None
            ),
            status="pending",
        )
        db.session.add(run)
        db.session.flush()  # assign run.id for the items below

        for r in forecast_results:
            fc = float(r.get("Forecast") or 0)
            low = r.get("ForecastLow")
            high = r.get("ForecastHigh")
            order, safety = _recommend(fc, low, high, z)
            sku = r.get("Sku")
            name = r.get("ProductName") or ""
            raw = r.get("ForecastRaw")
            db.session.add(LedgerItem(
                run_id=run.id,
                product_key=(sku or name),
                product_name=name,
                sku=sku,
                forecast=fc,
                raw_forecast=(float(raw) if raw is not None else fc),
                forecast_low=(float(low) if low is not None else None),
                forecast_high=(float(high) if high is not None else None),
                recommended_order=float(order),
                safety_stock=float(safety),
            ))

        db.session.commit()
        return run.id
    except Exception:  # noqa: BLE001 - never let bookkeeping break the forecast
        db.session.rollback()
        return None


def _match_product(df, group_col, key):
    """Rows in the resampled catalog belonging to one ledger item.

    product_key is SKU-when-present else name (how the forecaster groups), so
    match a real SKU exactly, and fall back to name only for SKU-less products.
    """
    if group_col == "sku":
        return df[(df["sku"] == key) | ((df["sku"] == "") & (df["product_name"] == key))]
    return df[df["product_name"] == key]


def reconcile_runs():
    """Fill in realized sales for any run whose forecast window is now fully
    covered by catalog data, and mark it complete. Idempotent - safe to call on
    every sync and every ledger view. Returns the number of runs reconciled."""
    from app.controllers.catalog_controller import catalog_to_json_data

    pending = ForecastRun.query.filter(ForecastRun.status != "complete").all()
    if not pending:
        return 0

    # Rebuild each grain's resampled catalog at most once, not per run.
    frames = {}
    reconciled = 0
    now = datetime.utcnow()

    for run in pending:
        grain = _grain_for(run.grain)
        window = grain.future_index(run.start_date, run.horizon)
        window_end = window.max()

        if run.grain not in frames:
            json_data, _, _ = catalog_to_json_data(grain)
            df = pd.DataFrame(json_data)
            if not df.empty:
                df["ds"] = pd.to_datetime(df["ds"])
            frames[run.grain] = df
        df = frames[run.grain]
        if df.empty:
            continue

        catalog_max = df["ds"].max()
        # Only grade a run once its whole horizon has actually happened - a
        # partially-observed window would compare a full-horizon forecast against
        # half a period of sales and look wildly wrong.
        if pd.isna(catalog_max) or catalog_max < window_end:
            continue

        group_col = "sku" if df["sku"].astype(bool).any() else "product_name"
        for item in run.items:
            df_p = _match_product(df, group_col, item.product_key)
            actual = float(period_actuals(df_p, run.start_date, run.horizon, grain).sum())
            item.actual = actual
            item.reconciled = True

        run.status = "complete"
        run.reconciled_at = now
        reconciled += 1

    if reconciled:
        db.session.commit()
    return reconciled


def _run_stats(items):
    """Aggregate accuracy for a reconciled run's items."""
    done = [i for i in items if i.reconciled and i.actual is not None]
    if not done:
        return None
    total_f = sum(i.forecast for i in done)
    total_a = sum(i.actual for i in done)
    abs_err = sum(abs(i.forecast - i.actual) for i in done)
    # Portfolio error: total absolute miss as a share of what actually sold -
    # a stabler, more honest headline than averaging per-SKU MAPE (which blows
    # up on any SKU that sold near zero).
    portfolio_error = (abs_err / total_a * 100) if total_a > 0 else None
    bias = ((total_f - total_a) / total_a * 100) if total_a > 0 else None
    within = sum(
        1 for i in done
        if i.forecast_low is not None and i.forecast_high is not None
        and i.forecast_low <= i.actual <= i.forecast_high
    )
    return {
        "total_forecast": round(total_f),
        "total_actual": round(total_a),
        "portfolio_error": (round(portfolio_error, 1) if portfolio_error is not None else None),
        "bias": (round(bias, 1) if bias is not None else None),
        "within_interval": within,
        "within_interval_pct": round(within / len(done) * 100, 0),
        "scored_items": len(done),
    }


def _period_label(grain, start_date, horizon):
    """Human span for a run, e.g. 'Jun 2024 - Aug 2024' or 'wk of 2024-06-02 +8'."""
    g = _grain_for(grain)
    window = g.future_index(start_date, horizon)
    if g is MONTHLY:
        return f"{window.min().strftime('%b %Y')} – {window.max().strftime('%b %Y')}"
    return f"{window.min().strftime('%Y-%m-%d')} – {window.max().strftime('%Y-%m-%d')}"


def list_runs():
    """Every recorded run, newest first, with aggregate accuracy where the run
    has been reconciled. Reconciles first so the view is always current."""
    reconcile_runs()
    out = []
    for run in ForecastRun.query.order_by(ForecastRun.created_at.desc()).all():
        items = run.items.all()
        out.append({
            "id": run.id,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "grain": run.grain,
            "start_date": run.start_date.isoformat(),
            "horizon": run.horizon,
            "period": _period_label(run.grain, run.start_date, run.horizon),
            "service_level": run.service_level,
            "product_count": len(items),
            "status": run.status,
            "reconciled_at": run.reconciled_at.isoformat() if run.reconciled_at else None,
            "stats": _run_stats(items) if run.status == "complete" else None,
        })
    return out


def run_detail(run_id):
    """Per-SKU forecast-vs-outcome for one run."""
    run = ForecastRun.query.get(run_id)
    if run is None:
        return None
    items = []
    for i in run.items.all():
        err_pct = None
        if i.reconciled and i.actual is not None and i.actual > 0:
            err_pct = round((i.forecast - i.actual) / i.actual * 100, 1)
        items.append({
            "product_name": i.product_name,
            "sku": i.sku,
            "forecast": round(i.forecast),
            "forecast_low": (round(i.forecast_low) if i.forecast_low is not None else None),
            "forecast_high": (round(i.forecast_high) if i.forecast_high is not None else None),
            "recommended_order": (round(i.recommended_order) if i.recommended_order is not None else None),
            "safety_stock": (round(i.safety_stock) if i.safety_stock is not None else None),
            "actual": (round(i.actual) if (i.reconciled and i.actual is not None) else None),
            "error_pct": err_pct,
            "within_interval": (
                bool(i.forecast_low is not None and i.forecast_high is not None
                     and i.actual is not None and i.forecast_low <= i.actual <= i.forecast_high)
                if i.reconciled else None
            ),
        })
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "grain": run.grain,
        "period": _period_label(run.grain, run.start_date, run.horizon),
        "status": run.status,
        "service_level": run.service_level,
        "stats": _run_stats(run.items.all()) if run.status == "complete" else None,
        "items": items,
    }
