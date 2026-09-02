"""Price elasticity of demand (Phase 7).

When a file carries monthly prices, estimate each SKU's price elasticity - the
% change in demand per % change in price - by regressing log(demand) on
log(price) while controlling for month (so a seasonal price/demand correlation
isn't mistaken for elasticity). SKUs whose price barely moved can't be
estimated from their own data, so they inherit their category's median. The
result powers a "what-if a price change" figure and can feed the models.
"""
from collections import defaultdict

import numpy as np

MIN_POINTS = 24        # months of positive demand+price needed to estimate
MIN_LOGPRICE_STD = 0.02  # enough price movement to identify the slope


def estimate_elasticity(df_sku):
    """Per-SKU elasticity via log-log OLS with month fixed effects, or None if
    there isn't enough price movement / data to identify it."""
    if "price" not in df_sku.columns:
        return None
    d = df_sku.sort_values("ds")
    y = d["y"].to_numpy(dtype=float)
    p = d["price"].to_numpy(dtype=float)
    months = d["ds"].dt.month.to_numpy()

    mask = (y > 0) & np.isfinite(p) & (p > 0)
    if mask.sum() < MIN_POINTS:
        return None
    ly, lp, mo = np.log(y[mask]), np.log(p[mask]), months[mask]
    if np.std(lp) < MIN_LOGPRICE_STD:
        return None

    # design: intercept + log(price) + 11 month dummies (Jan is the baseline)
    dummies = np.zeros((mask.sum(), 11))
    for j, m in enumerate(range(2, 13)):
        dummies[:, j] = (mo == m).astype(float)
    X = np.column_stack([np.ones(mask.sum()), lp, dummies])
    try:
        beta, *_ = np.linalg.lstsq(X, ly, rcond=None)
    except np.linalg.LinAlgError:
        return None
    e = float(beta[1])
    if not np.isfinite(e) or e > 0.5 or e < -6.0:
        return None  # implausible - treat as unidentified
    return e


def estimate_all(df, group_col, products, category_by_group):
    """{group_key: (elasticity, source)} where source is own/category/overall,
    or (None, None) when nothing can be estimated."""
    raw = {g: estimate_elasticity(df[df[group_col] == g]) for g in products}

    by_cat = defaultdict(list)
    for g, e in raw.items():
        if e is not None:
            by_cat[category_by_group.get(g)].append(e)
    cat_median = {c: float(np.median(v)) for c, v in by_cat.items() if v}
    all_e = [e for e in raw.values() if e is not None]
    overall = float(np.median(all_e)) if all_e else None

    out = {}
    for g in products:
        if raw[g] is not None:
            out[g] = (raw[g], "own")
        elif cat_median.get(category_by_group.get(g)) is not None:
            out[g] = (cat_median[category_by_group.get(g)], "category")
        elif overall is not None:
            out[g] = (overall, "overall")
        else:
            out[g] = (None, None)
    return out
