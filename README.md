# Insighta — Sales Forecasting & Inventory Planning

A desktop app that turns a spreadsheet of sales history into **per-product demand forecasts and concrete inventory decisions** — what to order, how much safety stock to hold, where to spend a limited budget, and how demand responds to price. It runs entirely on an ordinary Windows machine, offline, with no cloud services or API keys.

Unlike a one-shot forecasting tool, Insighta is **stateful**: it remembers every forecast it made, checks each one against what actually sold, and **corrects itself** on the next run. Built with a React + Electron front end and a Python (Flask) forecasting engine, packaged into a single Windows installer.

> **Status:** working desktop application (Windows). Upload an Excel/CSV of monthly *or* weekly sales and get forecasts, calibrated confidence ranges, reorder decisions, a budget-constrained order plan, and a backtested accuracy report — plus an assistant you can ask about your own numbers.

---

## What it does

- **Per-SKU demand forecasting** — upload sales history (`.xlsx`/`.csv`, monthly or weekly), pick a horizon or a specific future window, and get a forecast for every product, not just an aggregate.
- **Inventory decisions, not just numbers** — each forecast becomes a **reorder point**, an **order-up-to level**, and a **suggested order quantity** at a chosen service level (90 / 95 / 99%), grounded in on-hand stock, lead time, and costs you can edit inline.
- **Attention view** — the landing screen ranks what actually needs a decision today: imminent stockouts, overdue purchase orders, demand shifts, and overstock — each with a one-click order action.
- **Budget-constrained order plan** — given a spend cap, it allocates the budget across SKUs to buy the most service per dollar (a Lagrangian water-filling allocation over each product's demand distribution), with a live budget slider.
- **Purchase orders & learned lead time** — track orders on the way; the app learns each supplier's real resupply time from your order→arrival history instead of trusting a guessed number.
- **A decision ledger that learns** — every forecast is logged, then reconciled against real sales as the window closes. From that track record the engine learns each SKU's **bias and interval width** and auto-corrects future forecasts. Your forecasts get better the longer you use it.
- **Price elasticity & what-if** — when the file includes prices, it estimates each product's price sensitivity and shows how demand would move if you changed the price.
- **Accuracy report & backtest** — trains on past data and scores the *real* forecasting engine against what actually happened (MAE / RMSE / MAPE), plus a rolling-origin track record, so quality is measurable, not assumed.
- **Ask your business** — a bundled local language model answers plain-language questions ("what should I reorder before the holidays?") grounded strictly in your data. It only ever *describes* the numbers the models produce; it never invents figures.

Everything runs **locally and offline** (the forecasting models download once on first launch, then need no internet).

---

## Benchmarks

Claims here are measured, not asserted. The engine was validated on the public **[M5](https://www.kaggle.com/competitions/m5-forecasting-accuracy) Walmart retail dataset** — real, heavily intermittent demand — aggregated to the app's operational weekly grain: **417 SKUs across 7 departments**, scored strictly **out-of-sample** with a **4-cutoff rolling-origin backtest**. The metric is **MASE** (scale-free, handles zeros; **1.0 = a naive one-step forecast**, lower is better). Baselines are real methods, not strawmen: seasonal-naive, AutoETS, and the intermittent-demand specialists **Croston-SBA** and **TSB**.

**1. It beats the standard baseline decisively.** Insighta produces a better forecast than seasonal-naive on **77–85% of SKUs** — and holds that margin in *every* quarter of the rolling-origin backtest, so it isn't a lucky window.

**2. It matches specialist methods — with one general engine.** Each classical method only wins on its own niche; Insighta is competitive everywhere at once, automatically, without you hand-picking a model per product. On the *typical* SKU (median MASE) it's the **best of every method tested**.

| MASE (all SKUs) | Insighta | AutoETS | TSB | Croston-SBA | Seasonal-naive |
|---|---|---|---|---|---|
| mean | 1.68 | 1.67 | 1.63 | 2.01 | 2.54 |
| **median** | **1.06** | 1.08 | 1.10 | 1.15 | 1.56 |

Head-to-head win rates confirm a statistical tie with the best classical methods on point accuracy (54% ± 5pt vs AutoETS and TSB) and a decisive win over seasonal-naive (85% ± 3pt).

**3. Its confidence ranges are honestly calibrated — the real differentiator.** An 80%-target interval should contain the actual demand ~80% of the time. Insighta does; AutoETS is over-confident and quietly under-covers, worst of all exactly where it matters most (sparse, intermittent SKUs). Calibrated intervals are what make a stated service level trustworthy for ordering.

| 80%-target interval coverage | Insighta | AutoETS |
|---|---|---|
| all SKUs | **84%** | 78% |
| intermittent SKUs | **83%** | 73% |

*Notes.* MASE scale = each series' in-sample one-step seasonal-naive error. Of 420 sampled series, 3 were dropped (zero holdout demand or flat history make MASE undefined), leaving 417 scored. Benchmark scripts are reproducible against the public M5 files. In an apples-to-apples reorder simulation, Insighta's better calibration and AutoETS's sharper-but-over-confident intervals reach **comparable fill rates at equal inventory** — Insighta's edge is that it delivers the service level it promises.

---

## How the forecasting works

The engine is deliberately not a single model. Different products behave differently, so each SKU is routed and blended rather than forced through one algorithm:

- **Skill-weighted ensemble** — for products with enough history, several models forecast in parallel — statistical models (AutoETS, Dynamic Optimized Theta, seasonal-naive) via [Nixtla StatsForecast](https://github.com/Nixtla/statsforecast), a global gradient-boosted model ([LightGBM](https://github.com/microsoft/LightGBM)), and Amazon's zero-shot **Chronos-Bolt** foundation model — and are blended per SKU by how accurately each performed on a recent validation fold. A model that fits the product dominates; a model that fails it earns near-zero weight. This is *soft weighting*, chosen because hard per-SKU model *selection* measurably overfit.
- **Intermittent demand** — erratic, on-and-off items (spare parts, etc.) are detected by the Syntetos–Boylan classification and routed to specialist Croston/TSB models instead of smooth ones.
- **Cold start** — brand-new products with little history borrow a seasonal shape from their category, deseasonalized so a peak-season launch isn't mistaken for a runaway seller.
- **Prediction intervals** — bands come from the ensemble's own recent errors (a conformal-style, distribution-free approach), then combined across the horizon with a correlation-aware aggregation — because a forecast that's off tends to be off the *same* direction all year, so treating periods as independent understates cumulative risk.
- **Safety stock** — the recommended order is `forecast + z(service level) × σ`, with σ recovered from the calibrated interval, so a "95% service" order genuinely targets ~95%.
- **The closed loop** — every forecast is stored and later reconciled against real sales. The app learns each SKU's persistent bias and how wide its intervals really need to be, then shrinks those corrections toward neutral (so a single odd cycle can't whipsaw it) and applies them to future runs. This is the compounding advantage a stateless tool can't have.

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
