# Insighta — Sales Forecasting & Inventory Planning

A desktop app that turns a spreadsheet of sales history into **per-product demand forecasts and concrete inventory decisions** — what to order, how much safety stock to hold, where to spend a limited budget, and how demand responds to price. It runs entirely on an ordinary Windows machine, offline, with no cloud services or API keys.

Unlike a one-shot forecasting tool, Insighta is **stateful**: it remembers every forecast it made and grades each one against what actually sold, so you get an honest, running track record of how far its forecasts run high or low and how often reality lands inside the stated range. Built with a React + Electron front end and a Python (Flask) forecasting engine, packaged into a single Windows installer.

> **Status:** working desktop application (Windows). Upload an Excel/CSV of monthly *or* weekly sales and get forecasts, calibrated confidence ranges, reorder decisions, a budget-constrained order plan, and a backtested accuracy report — plus an assistant you can ask about your own numbers.

---

## What it does

- **Per-SKU demand forecasting** — upload sales history (`.xlsx`/`.csv`, monthly or weekly), pick a horizon or a specific future window, and get a forecast for every product, not just an aggregate.
- **Inventory decisions, not just numbers** — each forecast becomes a **reorder point**, an **order-up-to level**, and a **suggested order quantity** at a chosen service level (90 / 95 / 99%), grounded in on-hand stock, lead time, and costs you can edit inline.
- **Attention view** — the landing screen ranks what actually needs a decision today: imminent stockouts, overdue purchase orders, demand shifts, and overstock — each with a one-click order action.
- **Budget-constrained order plan** — given a spend cap, it allocates the budget across SKUs to buy the most service per dollar (a Lagrangian water-filling allocation over each product's demand distribution), with a live budget slider.
- **Purchase orders & learned lead time** — track orders on the way; the app learns each supplier's real resupply time from your order→arrival history instead of trusting a guessed number.
- **A self-grading track record** — every forecast is logged, then reconciled against real sales as the window closes, so the app can show you which products it forecasts well, which run consistently high or low, and whether reality actually lands inside the stated range. (An earlier version auto-rescaled future forecasts from this history; measured on real data that made them *worse* — the ledger's honest job is accountability, not a self-tuning knob.)
- **Price elasticity & what-if** — when the file includes prices, it estimates each product's price sensitivity and shows how demand would move if you changed the price.
- **Accuracy report & backtest** — trains on past data and scores the *real* forecasting engine against what actually happened (MAE / RMSE / MAPE), plus a rolling-origin track record, so quality is measurable, not assumed.
- **Ask your business** — a bundled local language model answers plain-language questions ("what should I reorder before the holidays?") grounded strictly in your data. It only ever *describes* the numbers the models produce; it never invents figures.

Everything runs **locally and offline** (the forecasting models download once on first launch, then need no internet).

---

## Benchmarks

Claims here are measured, not asserted — and the measurements that *didn't* go our way are reported too. The engine was validated on the public **[M5](https://www.kaggle.com/competitions/m5-forecasting-accuracy) Walmart retail dataset** — real, heavily intermittent demand — at both the app's grains: a stratified **~420 SKUs across 7 departments**, scored strictly **out-of-sample** (weekly also with a **4-cutoff rolling-origin backtest**). The metric is **MASE** (scale-free, handles zeros; **1.0 = a naive one-step forecast**, lower is better). Baselines are real methods, not strawmen: seasonal-naive, AutoETS, and the intermittent-demand specialists **Croston-SBA** and **TSB**.

**1. It beats the standard baseline decisively — at both grains.** Insighta produces a better forecast than seasonal-naive on **80% of SKUs monthly and 77–85% weekly** (weekly holds in *every* quarter of the rolling-origin backtest, so it isn't a lucky window).

**2. At monthly grain — the app's default — it beats a strong classical model outright.**

| MASE (monthly, all SKUs) | Insighta | AutoETS | Seasonal-naive |
|---|---|---|---|
| mean | **1.93** | 2.19 | 2.72 |
| median | **1.18** | 1.23 | — |

That's ~12% better than AutoETS on the mean, winning head-to-head on **57% ± 5pt** of SKUs — the ensemble's diversity pays off once monthly aggregation smooths the week-to-week noise.

**3. At weekly grain it matches the best specialist methods — with one general engine.** Under heavy weekly intermittency the classical methods are already near the achievable floor, so Insighta ties them rather than beating them — but it does so *automatically*, without you hand-picking Croston for one SKU and ETS for the next, and it's the **best of every method on the typical (median) SKU**.

| MASE (weekly, all SKUs) | Insighta | AutoETS | TSB | Croston-SBA | Seasonal-naive |
|---|---|---|---|---|---|
| mean | 1.68 | 1.67 | 1.63 | 2.01 | 2.54 |
| **median** | **1.06** | 1.08 | 1.10 | 1.15 | 1.56 |

Head-to-head weekly win rates are a statistical tie with the best classical methods (54% ± 5pt vs AutoETS and TSB) and a decisive win over seasonal-naive (85% ± 3pt).

**4. Its confidence ranges are honestly calibrated.** An 80%-target interval should contain the actual demand ~80% of the time. Insighta lands there; AutoETS is over-confident and quietly under-covers, worst of all where it matters most (sparse, intermittent SKUs).

| 80%-target interval coverage | Insighta | AutoETS |
|---|---|---|
| all SKUs | **84%** | 78% |
| intermittent SKUs | **83%** | 73% |

*Honest caveat:* better calibration does **not** translate into a free inventory saving. In an apples-to-apples reorder simulation, Insighta's wider (well-covering) bands and AutoETS's tighter (over-confident) bands reach **comparable fill at equal inventory** — if anything AutoETS is slightly more inventory-efficient per unit of service. The value of calibration here is *trust*: when the app says 80%, it means it, so a stated service level is a promise rather than an optimistic guess. To make that promise honest on lumpy demand, the safety-stock math uses a **count-distribution quantile** (negative-binomial / Poisson) rather than a symmetric normal — measured on M5, that closes most of the stated-vs-achieved service gap (ordering to 95% delivered ~87% under a normal σ, ~91% here).

*Notes.* MASE scale = each series' in-sample one-step seasonal-naive error. A handful of series per run are dropped where MASE is undefined (zero holdout demand or flat history). Benchmark scripts are reproducible against the public M5 files.

---

## How the forecasting works

The engine is deliberately not a single model. Different products behave differently, so each SKU is routed and blended rather than forced through one algorithm:

- **Skill-weighted ensemble** — for products with enough history, several models forecast in parallel — statistical models (AutoETS, Dynamic Optimized Theta, seasonal-naive) via [Nixtla StatsForecast](https://github.com/Nixtla/statsforecast), a global gradient-boosted model ([LightGBM](https://github.com/microsoft/LightGBM)), and Amazon's zero-shot **Chronos-Bolt** foundation model — and are blended per SKU by how accurately each performed on a recent validation fold. A model that fits the product dominates; a model that fails it earns near-zero weight. This is *soft weighting*, chosen because hard per-SKU model *selection* measurably overfit.
- **Intermittent demand** — erratic, on-and-off items (spare parts, etc.) are detected by the Syntetos–Boylan classification and routed to specialist Croston/TSB models instead of smooth ones.
- **Cold start** — brand-new products with little history borrow a seasonal shape from their category, deseasonalized so a peak-season launch isn't mistaken for a runaway seller.
- **Prediction intervals** — bands come from the ensemble's own recent errors (a conformal-style, distribution-free approach), then combined across the horizon with a correlation-aware aggregation — because a forecast that's off tends to be off the *same* direction all year, so treating periods as independent understates cumulative risk.
- **Safety stock** — the order-up-to level is the service-level *quantile* of demand over the protection window (lead time + review period). For high-volume demand that's `forecast + z × σ`; for low-count, intermittent demand — where a symmetric normal under-delivers the stated service — it uses a count-distribution quantile (negative-binomial when demand is overdispersed, Poisson otherwise), so a "95% service" order genuinely targets ~95%.
- **The self-grading track record** — every forecast is stored and later reconciled against real sales, giving each SKU an observed bias and realized coverage you can inspect. It deliberately does *not* auto-rescale future forecasts: a version that did looked great on a synthetic simulator with injected persistent bias, but on real M5 demand the learned corrections were net-negative (real bias is mostly noise cycle-to-cycle, and rescaling the band fought the already-calibrated conformal interval). The honest value is accountability — a forecaster you can check — not a self-tuning knob that quietly drifts.

Every enrichment was validated against real out-of-sample data (see **Benchmarks**) and a purpose-built, heterogeneous synthetic test catalog with known patterns and elasticities — measure first, ship only what the data supports.

---

## Tech stack

| Layer | Technology |
|------|------------|
| **Desktop shell** | Electron, packaged with electron-builder (NSIS installer) |
| **Front end** | React 19, Vite, Tailwind CSS, Recharts |
| **Back end** | Python, Flask, SQLAlchemy + Alembic migrations |
| **Forecasting** | StatsForecast, LightGBM, Chronos-Bolt, NumPy / pandas |
| **Local LLM** | a small quantized model served via llama.cpp, for offline summaries and the assistant |
| **Packaging** | PyInstaller freezes the Python backend into the Electron app |

---

## Getting started (development)

**Prerequisites:** Python 3.11+, Node.js 18+, Windows.

**1. Back end (Flask API on `127.0.0.1:5000`):**
```bash
cd backend
pip install -r requirements.txt
python run.py
```

**2. Front end (Vite dev server on `localhost:5173`):**
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and upload a sales file. (The forecasting models download once on first use.)

### Building the Windows installer

```bash
cd backend
pyinstaller run.spec        # freeze the Python backend -> backend/dist/run
cd ../electron
npm install
npm run dist                # build the front end + package the installer
```

This produces a self-contained installer under `electron/dist-electron/` (`Insighta Setup <version>.exe`).

---

## Project structure

```
backend/    Flask API + forecasting engine
  app/forecasting/   ensemble, statistical, lightgbm, chronos,
                     intermittent, borrowed-shape, elasticity, conformal
  app/controllers/   forecasting, inventory, purchase orders, ledger,
                     closed-loop learning, budget optimization, assistant
  app/models/        catalog, forecast runs, ledger, settings, purchase orders
frontend/   React + Vite UI (Attention, Assistant, Forecast, Order plan, Accuracy)
electron/   desktop shell + electron-builder packaging config
```

---

## Input format

An Excel or CSV file with a **Product Name** column (optionally a **Product ID (SKU)**), any context columns like **Category**, and one column per period of history — monthly or weekly:

| Product Name | Product ID (SKU) | Category | Quantity Sold Jan 2023 | Quantity Sold Feb 2023 | … | Unit Price Jan 2023 | … |
|---|---|---|---|---|---|---|---|
| Winter Coat | WIN-1001 | Winter Apparel | 120 | 95 | … | 89.00 | … |

`Unit Price <period>` columns are optional and enable the price-elasticity features. On-hand stock, lead time, and cost fields can be supplied in the file or edited inline in the app.

---

## Notes

- Fully offline after the one-time model download; no data leaves the machine.
- The installer is currently unsigned, so Windows SmartScreen shows an "unknown developer" prompt on first run (**More info → Run anyway**).
