# Insighta — Sales Forecasting & Inventory Planning

A desktop app that turns a spreadsheet of monthly sales into **per-product demand forecasts and concrete inventory decisions** — how much to order, how much safety stock to hold, and how demand responds to price. It runs entirely on an ordinary Windows machine, offline, with no cloud services or API keys.

Built with a React + Electron front end and a Python (Flask) forecasting engine, packaged into a single Windows installer.

> **Status:** working desktop application (Windows). Upload an Excel/CSV of monthly sales and get forecasts, confidence ranges, suggested orders, and a backtested accuracy report.

---

## What it does

- **Per-SKU demand forecasting** — upload monthly sales history (`.xlsx`/`.csv`), pick a horizon, and get a forecast for every product, not just an aggregate.
- **Inventory recommendations** — converts each forecast into a **suggested order quantity** and **safety stock** at a chosen service level (90 / 95 / 99%), so the output is a decision, not just a number.
- **Honest confidence ranges** — every forecast carries a prediction interval, calibrated against real out-of-sample backtests rather than an optimistic in-sample check.
- **Price elasticity & what-if** — when the file includes prices, estimates each product's price sensitivity and shows how demand would move if you changed the price.
- **Accuracy report** — a backtest tab that trains on past data and scores the *real* forecasting engine against what actually happened (MAE / RMSE / MAPE), so the model's quality is measurable, not assumed.
- **Plain-language AI summaries** — a small, bundled local language model writes a short explanation of each product's outlook. It only ever *describes* the numbers the models produce; it never invents figures.

Everything runs **locally and offline** (the forecasting models download once on first launch, then need no internet).

---

## How the forecasting works

The engine is deliberately not a single model. Different products behave differently, so each SKU is routed and blended rather than forced through one algorithm:

- **Skill-weighted ensemble** — for products with enough history, several models forecast in parallel — statistical models (AutoETS, Dynamic Optimized Theta) via [Nixtla StatsForecast](https://github.com/Nixtla/statsforecast), a global gradient-boosted model ([LightGBM](https://github.com/microsoft/LightGBM)), and Amazon's zero-shot **Chronos-Bolt** foundation model — and are blended per SKU by how accurately each performed on a recent validation fold. A model that fits the product dominates; a model that fails it earns near-zero weight. This is *soft weighting*, chosen because hard per-SKU model *selection* measurably overfit.
- **Intermittent demand** — erratic, on-and-off items (spare parts, etc.) are detected by the Syntetos–Boylan classification and routed to specialist Croston/TSB models instead of smooth ones.
- **Cold start** — brand-new products with little history borrow a seasonal shape from their category, deseasonalized so a peak-season launch isn't mistaken for a runaway seller.
- **Prediction intervals** — bands come from the ensemble's own recent errors (a conformal-style, distribution-free approach), then combined across the horizon with a correlation-aware aggregation — because a forecast that's off tends to be off the *same* direction all year, so treating months as independent understates annual risk.
- **Safety stock** — the recommended order is `forecast + z(service level) × σ`, with σ recovered from the calibrated interval, so a "95% service" order genuinely targets ~95%.

Every enrichment was validated against a purpose-built, heterogeneous synthetic test catalog with known patterns and elasticities — measure first, ship only what the data supports.

---

## Tech stack

| Layer | Technology |
|------|------------|
| **Desktop shell** | Electron, packaged with electron-builder (NSIS installer) |
| **Front end** | React 19, Vite, Tailwind CSS, Recharts |
| **Back end** | Python, Flask, SQLAlchemy + Alembic migrations |
| **Forecasting** | StatsForecast, LightGBM, Chronos-Bolt, NumPy / pandas |
| **Local LLM** | a small quantized model served via llama.cpp, for offline text summaries |
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
cd electron
npm install
npm run dist
```

This builds the front end, freezes the backend, and produces a self-contained installer under `electron/dist-electron/` (`Insighta Setup <version>.exe`).

---

## Project structure

```
backend/    Flask API + forecasting engine
  app/forecasting/   ensemble, statistical, lightgbm, chronos,
                     intermittent, borrowed-shape, elasticity, conformal
  app/controllers/   request handling, file parsing, AI summaries
frontend/   React + Vite UI (upload, forecast table, chart, accuracy)
electron/   desktop shell + electron-builder packaging config
```

---

## Input format

An Excel or CSV file with a **Product Name** column (optionally a **Product ID (SKU)**), any context columns like **Category**, and one column per month of history:

| Product Name | Product ID (SKU) | Category | Quantity Sold Jan 2023 | Quantity Sold Feb 2023 | … | Unit Price Jan 2023 | … |
|---|---|---|---|---|---|---|---|
| Winter Coat | WIN-1001 | Winter Apparel | 120 | 95 | … | 89.00 | … |

`Unit Price <Mon> <Year>` columns are optional and enable the price-elasticity features.

---

## Notes

- Fully offline after the one-time model download; no data leaves the machine.
- The installer is currently unsigned, so Windows SmartScreen shows an "unknown developer" prompt on first run (**More info → Run anyway**).
