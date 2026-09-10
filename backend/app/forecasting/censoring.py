"""Stockout de-censoring: sales history is not demand history.

When a steady seller stocks out, its SALES drop to ~0 for that stretch even though
DEMAND didn't - the shelf was empty. Fitting a forecast to that censored series
systematically understates the SKU, and the reorder point inherits the bias, on
exactly the fast movers where a stockout hurts most. This reconstructs the likely
demand for those periods so the forecast trains on demand, not availability.

Deliberately crude and conservative (per the design review): we don't estimate a
censored-demand likelihood, we just stop treating an out-of-stock as zero demand.
A period is flagged only when all of the following hold, so we impute a real
stockout and never a legitimate zero:
  * the SKU is a STEADY seller (ADI < 1.32 - the same Syntetos-Boylan cut the
    engine routes on); genuinely intermittent SKUs have real zeros, left alone;
  * the period sits far below its SEASONAL expectation (same-phase demand in other
    cycles), so an off-season zero on a seasonal item isn't mistaken for a stockout;
  * demand RECOVERS afterwards - a temporary dip, not a sustained decline or a
    discontinuation (those are real and must flow through to the forecast).
Trailing/current stockouts are left to the inventory layer (it has live on-hand);
this handles the interior censoring that biases the fit.
"""
import numpy as np

from .intermittent import ADI_CUT, CV2_CUT

MIN_ACTIVE_CYCLES = 2       # need ~2 seasons of active history to judge a phase
# A true stockout is a NEAR-ZERO reading from an established level on a SMOOTH
# seller - not merely a low month, which is common and legitimate on noisy real
# demand. These are deliberately strict (recalibrated against real M5, where a
# loose "below expected" rule mislabeled ~80% of SKUs): near-zero only, smooth
# sellers only, and a material level - so we impute genuine stockouts, not noise.
CENSOR_FRAC = 0.12          # a period <=12% of its expected level (i.e. ~empty shelf)
RECOVER_FRAC = 0.60         # ...and demand must recover to >=60% of expected later
MIN_LEVEL = 5.0             # only SKUs whose expected level is materially non-trivial
MAX_CENSORED_FRAC = 0.15    # if >15% looks censored, it's a volatile SKU - bail


def _seasonal_expectation(active, season):
    """Per-index expected level = median of the SAME-PHASE positive values in the
    other cycles (so a seasonal peak/trough is judged against its own season, and a
    censored period doesn't drag its own expectation). Falls back to the global
    positive median where a phase has too few positive samples."""
    m = len(active)
    gpos = float(np.median(active[active > 0])) if np.any(active > 0) else 0.0
    if season < 2 or m < MIN_ACTIVE_CYCLES * season:
        return np.full(m, gpos)
    exp = np.empty(m)
    for i in range(m):
        same = active[[j for j in range(m) if j % season == i % season and active[j] > 0]]
        exp[i] = np.median(same) if len(same) >= 2 else gpos
    return exp


def detect(y, season):
    """Return (censored_mask, expected) over the FULL series y. `censored_mask[i]`
    marks period i as a probable stockout; `expected[i]` is the demand to impute
    there. Leading pre-launch zeros and non-steady SKUs yield an all-False mask."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    mask = np.zeros(n, dtype=bool)
    expected = y.copy()
    nz = np.nonzero(y > 0)[0]
    if len(nz) == 0:
        return mask, expected
    start = nz[0]
    active = y[start:]
    m = len(active)
    if m < season + 3:
        return mask, expected
    # SMOOTH-seller gate: only a smooth, regular seller (ADI < 1.32 AND CV2 < 0.49,
    # the engine's own cuts) makes a near-zero read anomalous enough to call a
    # stockout. Intermittent/lumpy SKUs have real zeros; erratic ones have wild low
    # months that aren't out-of-stocks - both are left untouched.
    nzv = active[active > 0]
    n_pos = len(nzv)
    adi = m / n_pos if n_pos else np.inf
    cv2 = float((nzv.std() / nzv.mean()) ** 2) if n_pos and nzv.mean() > 0 else np.inf
    if adi >= ADI_CUT or cv2 >= CV2_CUT:
        return mask, expected
    exp = _seasonal_expectation(active, season)
    near_zero = (active <= CENSOR_FRAC * exp) & (exp >= MIN_LEVEL)
    healthy = active >= RECOVER_FRAC * exp
    max_run = max(2, season // 2)            # a bracketed run longer than this is
    flagged = np.zeros(m, dtype=bool)        # dormancy, not a stockout - skip

    # Walk contiguous near-zero RUNS; flag one only if it is bracketed by healthy
    # demand on BOTH sides (an isolated empty-shelf stretch between normal months).
    # A run touching the start (pre-launch, already trimmed) or the end (a current
    # stockout or a real decline - ambiguous without live on-hand) is left alone.
    i = 0
    while i < m:
        if not near_zero[i]:
            i += 1
            continue
        j = i
        while j + 1 < m and near_zero[j + 1]:
            j += 1
        run_len = j - i + 1
        if i > 0 and j < m - 1 and healthy[i - 1] and healthy[j + 1] and run_len <= max_run:
            flagged[i:j + 1] = True
        i = j + 1

    if flagged.sum() == 0 or flagged.sum() > MAX_CENSORED_FRAC * m:
        return mask, expected                # nothing, or too much to trust
    for i in np.nonzero(flagged)[0]:
        expected[start + i] = exp[i]
        mask[start + i] = True
    return mask, expected


def decensor_frame(df, group_col, grain):
    """De-censor the y column per SKU in place-safe copy. Returns (df2, info) where
    info maps group_key -> {'periods': [ISO dates], 'imputed': total units added}.
    Only steady sellers with recovered interior dips are touched."""
    import pandas as pd  # local: keep the module import-light for the battery
    from .base import WEEKLY

    season = 52 if grain is WEEKLY else 12
    df2 = df.copy()
    info = {}
    for key, g in df2.groupby(group_col):
        g = g.sort_values("ds")
        y = g["y"].to_numpy(dtype=float)
        mask, expected = detect(y, season)
        if not mask.any():
            continue
        idx = g.index[mask]
        df2.loc[idx, "y"] = expected[mask]
        added = float(np.sum(expected[mask] - y[mask]))
        info[key] = {
            "periods": [d.date().isoformat() if hasattr(d, "date") else str(d)
                        for d in pd.to_datetime(g["ds"].to_numpy()[mask])],
            "imputed": round(added, 1),
        }
    return df2, info
