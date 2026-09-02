"""Chronos-Bolt zero-shot foundation model (Phase 4).

Amazon's Chronos-Bolt is a pretrained time-series transformer that forecasts a
series with NO fitting - it has seen millions of series in pretraining and
generalizes zero-shot, which is exactly the strength our per-SKU models lack on
irregular / thin history. It's tiny and fast on CPU (all ~500 SKUs in ~1-2s,
batched) and returns quantiles natively. It joins the ensemble as one more
weighted member, so the per-SKU weighting decides where it actually helps.

The model (~small) downloads on first run to LOCALAPPDATA - the same pattern as
the Qwen LLM - then loads offline from there.
"""
import os
import threading

import numpy as np

from .base import Forecast, clip_nonneg

CHRONOS_REPO = "amazon/chronos-bolt-small"
QUANTILES = [0.1, 0.5, 0.9]  # low / median / high (~80% band)

_appdata = os.getenv("LOCALAPPDATA")
MODEL_DIR = (
    os.path.join(_appdata, "Insighta", "models", "chronos_bolt_small")
    if _appdata
    else os.path.join(os.path.dirname(__file__), "..", "..", "models", "chronos_bolt_small")
)

_pipeline = None
_load_lock = threading.Lock()
_load_failed = False


def _ensure_pipeline():
    """Load the Chronos pipeline once (download on first run), cached in-process.
    Returns None if unavailable so the ensemble simply proceeds without it.

    Downloads via from_pretrained into a persistent cache_dir under LOCALAPPDATA
    (HF cache layout) - the fast, reliable path. Once cached, later loads are
    offline. An earlier snapshot_download(local_dir=...) approach was broken:
    it only created a .cache/ subfolder and never the model files, so loads
    failed and each retry re-hit a slow unauthenticated download.
    """
    global _pipeline, _load_failed
    if _pipeline is not None or _load_failed:
        return _pipeline
    with _load_lock:
        if _pipeline is not None or _load_failed:
            return _pipeline
        try:
            import torch
            from chronos import BaseChronosPipeline

            os.makedirs(MODEL_DIR, exist_ok=True)
            _pipeline = BaseChronosPipeline.from_pretrained(
                CHRONOS_REPO, cache_dir=MODEL_DIR, device_map="cpu", torch_dtype=torch.float32
            )
        except Exception:  # noqa: BLE001 - Chronos is optional; ensemble goes on without it
            _load_failed = True
            _pipeline = None
    return _pipeline


def forecast_all(df_all, group_col, products, horizon):
    """Batched zero-shot forecast for every series. Returns {group_key: Forecast}
    (empty if the model can't be loaded)."""
    pipe = _ensure_pipeline()
    if pipe is None or df_all.empty:
        return {}
    import torch

    keys, contexts = [], []
    for g in products:
        s = df_all[df_all[group_col] == g].sort_values("ds")
        y = s["y"].to_numpy(dtype="float32")
        if len(y) == 0:
            continue
        keys.append(g)
        contexts.append(torch.tensor(y))

    if not contexts:
        return {}

    try:
        q, _mean = pipe.predict_quantiles(
            inputs=contexts, prediction_length=horizon, quantile_levels=QUANTILES
        )
    except Exception:  # noqa: BLE001
        return {}

    q = q.detach().cpu().numpy()  # shape [n_series, horizon, 3]
    out = {}
    for i, g in enumerate(keys):
        low = clip_nonneg(q[i, :, 0])
        yhat = clip_nonneg(q[i, :, 1])
        high = clip_nonneg(q[i, :, 2])
        out[g] = Forecast(yhat=yhat, low=low, high=high)
    return out
