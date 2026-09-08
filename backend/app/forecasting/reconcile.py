"""Hierarchical reconciliation (cross-sectional: Total -> Category -> SKU).

Base forecasts made independently per series are INCOHERENT - the SKU forecasts
in a category don't sum to the category's own forecast. Reconciliation projects
them onto the space where they do add up, and the trace-minimizing projections
(MinT / OLS / WLS-structural) can also SHARPEN the noisy bottom level by borrowing
strength from the more stable aggregates.

Dependency-free on purpose: MinT-OLS and WLS-structural are closed-form
(G = (S'W^-1 S)^-1 S'W^-1), so no `hierarchicalforecast` / QP solver is bundled.
Non-negativity is a clip (a pragmatic stand-in for full non-negative
reconciliation), fine for unit demand.

MEASURED, NOT ASSUMED (scratchpad/bench_reconcile.py, 417 real M5 series,
Total->Category->SKU): reconciliation moved bottom-level MASE by ~0% (mean 1.669
unchanged; WLS median 1.093->1.088), and the base forecasts were already 99.2%
coherent (only a 0.8% total gap to close). So MinT is NOT wired into the forecast
path - it would add matrix machinery for a net-zero accuracy gain, the same honest
call the closed loop got. This module stays as a tested primitive: `bottomup`
gives coherent category/total rollups (correct by construction) for any future
category-forecast view; OLS/WLS are here and verified if a hierarchy ever shows
the shared structure that makes trace-minimization pay.
"""
import numpy as np


def build_summing(bottom_keys, category_of):
    """Summing matrix S (m x n): m = 1 total + C categories + n bottom SKUs, n
    bottom series. Returns (S, labels, cats); labels[i] = (level, key) for node i,
    ordered total, categories (sorted), then bottom in `bottom_keys` order."""
    cats = sorted({category_of.get(k, "Uncategorized") for k in bottom_keys})
    n = len(bottom_keys)
    rows, labels = [], []
    rows.append(np.ones(n)); labels.append(("total", "TOTAL"))
    for c in cats:
        rows.append(np.array([1.0 if category_of.get(k) == c else 0.0 for k in bottom_keys]))
        labels.append(("category", c))
    for i, k in enumerate(bottom_keys):
        e = np.zeros(n); e[i] = 1.0
        rows.append(e); labels.append(("sku", k))
    return np.vstack(rows), labels, cats


def _projection(S, method):
    """G (n x m): maps base forecasts at all nodes to reconciled BOTTOM."""
    m, n = S.shape
    if method == "bottomup":
        G = np.zeros((n, m)); G[:, m - n:] = np.eye(n)
        return G
    if method == "ols":
        w_inv = np.ones(m)
    elif method == "wls_struct":
        # structural weights = number of bottom series each node aggregates
        w_inv = 1.0 / S.sum(axis=1)
    else:
        raise ValueError(f"unknown method {method!r}")
    StWi = S.T * w_inv                      # (n x m), row-scaled
    return np.linalg.solve(StWi @ S, StWi)  # (S'W^-1 S)^-1 S'W^-1


def reconcile(base, S, method="wls_struct", nonneg=True):
    """Reconcile base forecasts to coherence. `base` is (m,) or (m, H), ordered as
    build_summing's labels. Returns (bottom, allnodes): reconciled bottom (n[,H])
    and coherent forecasts at every node (m[,H]). With nonneg the bottom is clipped
    at 0 and the aggregates recomputed from it, so coherence is preserved."""
    base = np.asarray(base, dtype=float)
    G = _projection(S, method)
    bottom = G @ base
    if nonneg:
        bottom = np.clip(bottom, 0.0, None)
    return bottom, S @ bottom
