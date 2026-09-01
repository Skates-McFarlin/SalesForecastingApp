"""Generate a rich, edge-case-heavy synthetic sales catalog for validating the
forecasting intelligence work.

Unlike the original homogeneous test file (every SKU a clean seasonal series),
this builds a heterogeneous catalog with KNOWN ground-truth patterns so each
technique can be measured honestly:

- distinct category seasonal shapes (winter/summer/school/holiday/staples/...)
  so category intelligence and cross-SKU learning have real signal;
- product NAMES that carry the pattern (e.g. "Down Parka" -> winter) so
  LLM-extracted attributes correlate with demand;
- price tiers (premium vs budget) for the price-tier attribute / elasticity;
- edge cases: intermittent, lumpy, stockout gaps, new launches, declines,
  flat staples, and thin cold-start SKUs that share a category with mature
  siblings.

Writes rich_test.xlsx (app-compatible) + rich_test_truth.json (per-SKU ground
truth) for measurement.
"""
import json
import os

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
YEARS = range(2020, 2025)          # 5 years monthly -> 60 months
DATES = pd.date_range("2020-01-01", "2024-12-01", freq="MS")

# Category -> monthly seasonal multiplier (mean ~1). Distinct shapes so a SKU's
# category is genuinely informative.
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

# Product names per category, tagged with a rough price tier via the name.
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


def month_index(d):
    return list(DATES).index(d)


def base_series(shape, level, trend=0.0, noise=0.12):
    """A smooth seasonal series: level * category shape * (1 + trend ramp) * noise."""
    out = []
    n = len(DATES)
    for k, d in enumerate(DATES):
        ramp = 1.0 + trend * (k / n)
        v = level * shape[d.month] * ramp * (1 + RNG.normal(0, noise))
        out.append(max(0, v))
    return np.array(out)


def make_sku(sku, name, cat, price, pattern, values):
    row = {"Product ID (SKU)": sku, "Product Name": name, "Category": cat, "Unit Price": price}
    for d, v in zip(DATES, values):
        row["Quantity Sold " + d.strftime("%b %Y")] = int(round(max(0, v)))
    return row, {"sku": sku, "pattern": pattern, "category": cat}


def build():
    rows, truth = [], []
    counter = {c: 0 for c in NAMES}

    def next_sku(cat):
        counter[cat] += 1
        return f"{CAT_PREFIX[cat]}-{1000 + counter[cat]}"

    def add(cat, name_price, pattern, values):
        name, price = name_price
        sku = next_sku(cat)
        # vary price a little per SKU
        price = round(price * (0.9 + 0.2 * RNG.random()), 2)
        r, t = make_sku(sku, name, cat, price, pattern, values)
        rows.append(r); truth.append(t)

    for cat, shape in CATEGORY_SHAPE.items():
        names = NAMES[cat]
        # 3 mature smooth-seasonal SKUs per category (varied level)
        for i in range(3):
            add(cat, names[i % len(names)], "smooth_seasonal",
                base_series(shape, level=RNG.uniform(20, 120)))
        # 1 trending up, 1 trending down
        add(cat, names[3 % len(names)], "trending_up", base_series(shape, RNG.uniform(30, 60), trend=0.8))
        add(cat, names[4 % len(names)], "trending_down", base_series(shape, RNG.uniform(60, 100), trend=-0.6))
        # 1 thin cold-start (only last 6 months populated), shares the category shape
        vals = base_series(shape, RNG.uniform(30, 80))
        vals[:-6] = 0
        add(cat, names[5 % len(names)], "thin_coldstart", vals)

    # Intermittent SKUs (spare-parts style) across a couple of categories
    for i in range(10):
        cat = ["Electronics", "Fitness", "Everyday Staples"][i % 3]
        base = np.zeros(len(DATES))
        for k in range(len(DATES)):
            if RNG.random() < 0.22:
                base[k] = RNG.integers(3, 15)
        add(cat, ("Replacement Part Kit", 25), "intermittent", base)

    # Lumpy SKUs (sparse + highly variable size)
    for i in range(6):
        cat = ["Electronics", "Holiday Decor"][i % 2]
        base = np.zeros(len(DATES))
        for k in range(len(DATES)):
            if RNG.random() < 0.30:
                base[k] = RNG.integers(1, 60)  # wildly variable
        add(cat, ("Bulk Special Order", 40), "lumpy", base)

    # Stockout gaps: smooth series with an interior zero run
    for i in range(6):
        cat = list(CATEGORY_SHAPE)[i % len(CATEGORY_SHAPE)]
        vals = base_series(CATEGORY_SHAPE[cat], RNG.uniform(40, 90))
        start = RNG.integers(18, 36)
        vals[start:start + RNG.integers(3, 6)] = 0  # stockout
        add(cat, NAMES[cat][i % len(NAMES[cat])], "stockout_gap", vals)

    # New launches: zero until a launch month, then ramp
    for i in range(6):
        cat = list(CATEGORY_SHAPE)[(i + 2) % len(CATEGORY_SHAPE)]
        vals = base_series(CATEGORY_SHAPE[cat], RNG.uniform(30, 70), trend=1.0)
        launch = RNG.integers(24, 42)
        vals[:launch] = 0
        add(cat, NAMES[cat][i % len(NAMES[cat])], "new_launch", vals)

    # Declining/dying (obsolescence): healthy then fades toward zero
    for i in range(6):
        cat = list(CATEGORY_SHAPE)[(i + 4) % len(CATEGORY_SHAPE)]
        vals = base_series(CATEGORY_SHAPE[cat], RNG.uniform(50, 100))
        n = len(DATES)
        fade = np.clip(np.linspace(1.2, -0.2, n), 0, None)
        add(cat, NAMES[cat][i % len(NAMES[cat])], "declining", vals * fade)

    df = pd.DataFrame(rows)
    out_dir = os.path.dirname(os.path.abspath(__file__))
    xlsx = os.path.join(out_dir, "rich_test.xlsx")
    df.to_excel(xlsx, index=False)
    with open(os.path.join(out_dir, "rich_test_truth.json"), "w") as f:
        json.dump(truth, f, indent=2)
    print("wrote %s: %d SKUs, %d months" % (xlsx, len(df), len(DATES)))
    import collections
    print("patterns:", dict(collections.Counter(t["pattern"] for t in truth)))
    print("categories:", dict(collections.Counter(t["category"] for t in truth)))


if __name__ == "__main__":
    build()
