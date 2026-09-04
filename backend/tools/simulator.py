"""Daily business simulator (Phase 0.5).

Generates realistic DAILY sales for a synthetic catalog with known ground-truth
structure - the validation foundation for weekly forecasting and, later, the
closed-loop decision simulation (Phases 3-5).

Daily demand is drawn as integer counts from an underlying rate:

    rate(day) = base_level * annual_shape[month] * weekday_shape[dow]
                * trend_ramp * price_effect
    realized  = Poisson(rate)      # (lumpy SKUs use a bursty draw instead)

Poisson counts give the natural daily noise and sparsity - a 0.3-units/day SKU
is mostly zeros with occasional 1s - which is exactly why the engine forecasts a
WEEKLY rate rather than daily points. The true rate is kept per day in the
ground truth so a forecast can be scored against signal, not the daily noise.

`simulate()` returns a long-format daily DataFrame (one row per SKU-day) plus a
per-SKU truth list. The long format is deliberate: real daily/transactional
feeds are long, not wide monthly columns.
"""
import numpy as np
import pandas as pd

# --- shared structure (annual shape / names / elasticity mirror the monthly
#     generator so results stay comparable) --------------------------------

def _norm(d):
    m = np.mean(list(d.values()))
    return {k: v / m for k, v in d.items()}


CATEGORY_SHAPE = {
    "Winter Apparel":  _norm({1: 1.9, 2: 1.6, 3: 1.0, 4: 0.6, 5: 0.4, 6: 0.3, 7: 0.3, 8: 0.4, 9: 0.7, 10: 1.1, 11: 1.6, 12: 2.1}),
    "Summer Outdoor":  _norm({1: 0.3, 2: 0.3, 3: 0.5, 4: 0.9, 5: 1.4, 6: 1.9, 7: 2.1, 8: 1.8, 9: 1.1, 10: 0.6, 11: 0.4, 12: 0.3}),
    "Back to School":  _norm({1: 0.7, 2: 0.6, 3: 0.6, 4: 0.6, 5: 0.7, 6: 0.9, 7: 1.4, 8: 2.4, 9: 1.8, 10: 0.8, 11: 0.6, 12: 0.6}),
    "Holiday Decor":   _norm({1: 0.4, 2: 0.3, 3: 0.3, 4: 0.3, 5: 0.3, 6: 0.3, 7: 0.4, 8: 0.5, 9: 0.8, 10: 1.5, 11: 2.6, 12: 3.0}),
    "Everyday Staples": {m: 1.0 for m in range(1, 13)},
    "Fitness":         _norm({1: 2.2, 2: 1.6, 3: 1.2, 4: 1.0, 5: 0.9, 6: 0.9, 7: 0.8, 8: 0.8, 9: 1.0, 10: 1.0, 11: 0.9, 12: 0.8}),
    "Electronics":     _norm({1: 0.9, 2: 0.8, 3: 0.8, 4: 0.8, 5: 0.8, 6: 0.8, 7: 0.9, 8: 0.9, 9: 1.0, 10: 1.2, 11: 1.9, 12: 1.9}),
}

# Day-of-week multiplier (Mon=0 .. Sun=6), weekend-heavy retail. Mean ~1.
WEEKDAY_SHAPE = _norm({0: 0.80, 1: 0.85, 2: 0.90, 3: 0.95, 4: 1.15, 5: 1.55, 6: 1.30})

NAMES = {
    "Winter Apparel": [("Down Parka Men's", 180), ("Wool Beanie", 22), ("Thermal Base Layer", 45),
                        ("Winter Snow Boots", 130), ("Fleece Gloves", 18), ("Premium Cashmere Scarf", 95)],
    "Summer Outdoor": [("Beach Umbrella", 40), ("Sunscreen SPF 50", 14), ("Cooler Box 40L", 75),
                        ("Swim Goggles", 16), ("Inflatable Paddle Board", 320), ("Camping Hammock", 55)],
    "Back to School": [("Spiral Notebook 5-Pack", 12), ("Ballpoint Pens Box", 8), ("Kids Backpack", 35),
                        ("Lunch Box", 20), ("Scientific Calculator", 25), ("Colored Pencils Set", 15)],
    "Holiday Decor": [("Christmas LED String Lights", 28), ("Artificial Wreath", 45), ("Ornament Set 24pc", 30),
                       ("Tree Skirt", 22), ("Premium Pre-Lit Tree", 250), ("Advent Calendar", 18)],
    "Everyday Staples": [("Cotton Socks 6-Pack", 14), ("Paper Towels 12-Roll", 20), ("Dish Soap", 5),
                          ("AA Batteries 24-Pack", 16), ("Trash Bags 80ct", 18), ("Hand Soap Refill", 9)],
    "Fitness": [("Yoga Mat", 30), ("Resistance Bands Set", 25), ("Adjustable Dumbbell", 150),
                 ("Jump Rope", 12), ("Foam Roller", 28), ("Premium Kettlebell 20kg", 90)],
    "Electronics": [("Wireless Earbuds", 60), ("USB-C Cable 3-Pack", 15), ("Phone Case", 20),
                     ("Power Bank 20000mAh", 45), ("Bluetooth Speaker", 80), ("Premium Noise-Cancel Headphones", 300)],
}

CAT_PREFIX = {"Winter Apparel": "WIN", "Summer Outdoor": "SUM", "Back to School": "SCH",
              "Holiday Decor": "HOL", "Everyday Staples": "STP", "Fitness": "FIT", "Electronics": "ELC"}

ELASTICITY = {
    "Everyday Staples": -0.3, "Back to School": -0.8, "Holiday Decor": -1.2,
    "Winter Apparel": -1.5, "Summer Outdoor": -1.5, "Fitness": -1.8, "Electronics": -2.2,
}


def _daily_prices(base_price, dates, rng):
    """Base list price with a few multi-day promo events per year (10-30% off)
    plus small noise - the price variation the elasticity estimator needs."""
    prices = np.full(len(dates), base_price, dtype=float)
    years = (dates[-1].year - dates[0].year) + 1
    for _ in range(int(rng.integers(2, 5)) * years):
        start = int(rng.integers(0, len(dates)))
        length = int(rng.integers(4, 12))  # a sale lasts several days
        prices[start:start + length] = base_price * rng.uniform(0.7, 0.9)
    prices *= (1 + rng.normal(0, 0.02, len(prices)))
    return np.round(np.maximum(prices, 0.01), 2)


def _rate_curve(dates, cat, base_level, trend, rng):
    """The deterministic daily demand-rate signal (before price and noise)."""
    months = dates.month.to_numpy()
    dows = dates.weekday.to_numpy()
    annual = np.array([CATEGORY_SHAPE[cat][m] for m in months])
    weekly = np.array([WEEKDAY_SHAPE[d] for d in dows])
    ramp = 1.0 + trend * (np.arange(len(dates)) / len(dates))
    return base_level * annual * weekly * ramp


def _draw(rate, pattern, rng):
    """Realized integer daily sales from a rate. Poisson for most; a bursty
    (over-dispersed) draw for lumpy SKUs where order sizes vary wildly."""
    rate = np.clip(rate, 0, None)
    if pattern == "lumpy":
        hit = rng.random(len(rate)) < np.clip(rate / 4.0, 0, 0.5)
        size = rng.integers(1, 60, len(rate))
        return (hit * size).astype(int)
    return rng.poisson(rate).astype(int)


def simulate(start="2021-01-01", end="2024-12-31", seed=42):
    """Generate the daily catalog. Returns (df_long, truth).

    df_long columns: Sku, Product Name, Category, Date, Quantity, Unit Price.
    truth: per-SKU dict with pattern/category/elasticity/base_level and the true
    daily rate curve (for scoring against signal).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="D")
    n = len(dates)
    rows, truth = [], []
    counter = {c: 0 for c in NAMES}

    def next_sku(cat):
        counter[cat] += 1
        return f"{CAT_PREFIX[cat]}-{1000 + counter[cat]}"

    def add(cat, name_price, pattern, base_level, trend=0.0, elastic=True,
            launch=None, decline=False, stockout=None):
        name, list_price = name_price
        sku = next_sku(cat)
        base_price = round(list_price * (0.9 + 0.2 * rng.random()), 2)
        prices = _daily_prices(base_price, dates, rng)

        rate = _rate_curve(dates, cat, base_level, trend, rng)
        E = ELASTICITY[cat] if elastic else 0.0
        rate = rate * (prices / base_price) ** E  # promo days lift demand

        if launch is not None:
            rate[:launch] = 0.0
        if decline:
            rate = rate * np.clip(np.linspace(1.2, -0.2, n), 0, None)
        if stockout is not None:
            rate[stockout[0]:stockout[1]] = 0.0

        qty = _draw(rate, pattern, rng)
        for d, q, p in zip(dates, qty, prices):
            rows.append({"Sku": sku, "Product Name": name, "Category": cat,
                         "Date": d, "Quantity": int(q), "Unit Price": round(float(p), 2)})
        truth.append({"sku": sku, "pattern": pattern, "category": cat,
                      "elasticity": round(E, 3), "base_level": round(float(base_level), 3),
                      "rate": rate})

    for cat, names in NAMES.items():
        for i in range(3):  # mature smooth-seasonal
            add(cat, names[i % len(names)], "smooth_seasonal", rng.uniform(0.5, 6.0))
        add(cat, names[3 % len(names)], "trending_up", rng.uniform(1.0, 3.0), trend=1.2)
        add(cat, names[4 % len(names)], "trending_down", rng.uniform(2.0, 5.0), trend=-0.7)
        add(cat, names[5 % len(names)], "thin_coldstart", rng.uniform(1.0, 4.0),
            launch=n - 180)  # only the last ~6 months exist

    for i in range(10):  # intermittent (spare-parts): very low rate -> sparse
        cat = ["Electronics", "Fitness", "Everyday Staples"][i % 3]
        add(cat, ("Replacement Part Kit", 25), "intermittent", rng.uniform(0.05, 0.25), elastic=False)

    for i in range(6):  # lumpy: rare but large orders
        cat = ["Electronics", "Holiday Decor"][i % 2]
        add(cat, ("Bulk Special Order", 40), "lumpy", rng.uniform(0.4, 1.2), elastic=False)

    for i in range(6):  # stockout gap (interior zero run)
        cat = list(CATEGORY_SHAPE)[i % len(CATEGORY_SHAPE)]
        s = int(rng.integers(n // 3, 2 * n // 3))
        add(cat, NAMES[cat][i % len(NAMES[cat])], "stockout_gap", rng.uniform(1.0, 4.0),
            stockout=(s, s + int(rng.integers(20, 45))))

    for i in range(6):  # new launch partway through
        cat = list(CATEGORY_SHAPE)[(i + 2) % len(CATEGORY_SHAPE)]
        add(cat, NAMES[cat][i % len(NAMES[cat])], "new_launch", rng.uniform(1.0, 3.0),
            trend=1.2, launch=int(rng.integers(n // 2, 3 * n // 4)))

    for i in range(6):  # declining/obsolescing
        cat = list(CATEGORY_SHAPE)[(i + 4) % len(CATEGORY_SHAPE)]
        add(cat, NAMES[cat][i % len(NAMES[cat])], "declining", rng.uniform(2.0, 5.0), decline=True)

    df = pd.DataFrame(rows)
    return df, truth


if __name__ == "__main__":
    import collections
    df, truth = simulate()
    print("SKUs:", df["Sku"].nunique(), "| rows:", len(df),
          "| span:", df["Date"].min().date(), "->", df["Date"].max().date())
    print("patterns:", dict(collections.Counter(t["pattern"] for t in truth)))
    tot = df.groupby("Sku")["Quantity"].sum()
    print("total units/SKU: min %d, median %d, max %d" % (tot.min(), tot.median(), tot.max()))
    # sanity: day-of-week effect should show weekend lift
    dow = df.groupby(df["Date"].dt.weekday)["Quantity"].mean()
    print("mean qty by weekday (Mon..Sun):", [round(x, 2) for x in dow.tolist()])
