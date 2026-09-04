import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCatalog, importSales, forecastCatalog, scoreCatalogAccuracy,
  fetchSettings, updateSettings, updateProductInventory,
} from "./api";
import { catalogRange, cmp, dateBounds, durationThrough, monthRangeForYear } from "./dates";
import AccuracyResults from "./components/AccuracyResults";
import ControlPanel from "./components/ControlPanel";
import ForecastChart from "./components/ForecastChart";
import KpiStrip from "./components/KpiStrip";
import Ledger from "./components/Ledger";
import ResultsTable from "./components/ResultsTable";
import { Card, ErrorNote, SectionLabel, Select, SERVICE_LEVELS } from "./components/ui";

const TABS = [
  { id: "forecast", label: "Forecast" },
  { id: "accuracy", label: "Accuracy" },
  { id: "ledger", label: "Track record" },
];

const emptyRun = { rows: null, error: null, busy: false };

export default function App() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem("insighta-theme") ?? "light"
  );
  const [tab, setTab] = useState("forecast");

  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(1);
  const [duration, setDuration] = useState(12);
  // Optional specific future window on the Forecast tab. null = just use the
  // length dropdown; { from: {y,m}, through: {y,m} } = report only that window
  // (the full path from the data edge is still forecast to reach it).
  const [fcWindow, setFcWindow] = useState(null);

  const [forecast, setForecast] = useState(emptyRun);
  const [accuracy, setAccuracy] = useState(emptyRun);
  const [service, setService] = useState(SERVICE_LEVELS[1]); // 95% default
  const [settings, setSettings] = useState(null); // inventory defaults (Phase 2)
  const [catalog, setCatalog] = useState(null); // stored business summary
  const [importing, setImporting] = useState(false);
  const [dataRange, setDataRange] = useState(null); // catalog's date coverage
  const [elapsed, setElapsed] = useState(0);
  // Bumped after a forecast or a sync so the Track record tab refetches the
  // ledger (a new run was recorded, or new sales may have graded old ones).
  const [ledgerToken, setLedgerToken] = useState(0);
  const abortRef = useRef(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("insighta-theme", theme);
  }, [theme]);

  // The app opens onto the stored catalog, not a blank upload screen.
  const refreshCatalog = () =>
    fetchCatalog()
      .then((c) => {
        setCatalog(c);
        setDataRange(catalogRange(c));
        return c;
      })
      .catch(() => setCatalog({ empty: true, products: 0 }));

  useEffect(() => {
    refreshCatalog();
    // Inventory defaults; sync the service-level control to the saved default.
    fetchSettings()
      .then((s) => {
        setSettings(s);
        const match = SERVICE_LEVELS.find((lvl) => lvl.value === s.service_level);
        if (match) setService(match);
      })
      .catch(() => setSettings({
        default_lead_time_days: 14, review_period_days: 7,
        service_level: 0.95, holding_cost_rate: 0.25,
      }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist an inventory-defaults change and reflect it immediately.
  const changeSettings = (patch) => {
    setSettings((s) => ({ ...s, ...patch }));
    updateSettings(patch).catch(() => {});
  };

  // Backend inventory field -> the capitalized key the forecast rows carry.
  const INV_TO_ROW = {
    on_hand: "OnHand", on_order: "OnOrder", lead_time_days: "LeadTimeDays",
    unit_cost: "UnitCost", moq: "MOQ", case_pack: "CasePack",
  };
  // Edit one product's inventory: update the row locally (so the reorder math
  // recomputes instantly) and persist to the catalog.
  const changeInventory = (key, patch) => {
    const rowPatch = {};
    for (const [k, v] of Object.entries(patch)) {
      rowPatch[INV_TO_ROW[k] ?? k] = v === "" ? null : v;
    }
    setForecast((f) => ({
      ...f,
      rows: f.rows?.map((r) => ((r.Sku || r.ProductName) === key ? { ...r, ...rowPatch } : r)),
    }));
    updateProductInventory(key, patch).catch(() => {});
  };

  const active = tab === "forecast" ? forecast : accuracy;
  const setActive = tab === "forecast" ? setForecast : setAccuracy;

  // Start-date window derived from the uploaded file (past for backtesting,
  // forward for forecasting). Falls back to a default range before a file lands.
  const bounds = useMemo(() => dateBounds(dataRange, tab), [dataRange, tab]);

  // The catalog's grain (weekly for daily data, else monthly) drives whether the
  // horizon is counted in weeks or months.
  const grain = catalog?.grain === "weekly" ? "weekly" : "monthly";
  // Forecasts anchor at the catalog's data edge (the backend derives this); the
  // UI shows it and turns a "through <month>" target into a horizon length.
  const origin = catalog?.forecast_origin ?? null;
  useEffect(() => {
    setDuration(grain === "weekly" ? 8 : 12);
    setFcWindow(null); // a window/length doesn't carry across grains
  }, [grain]);
  // Effective horizon for the Forecast tab: a window forecasts far enough to
  // reach its "through" month; otherwise the length dropdown applies. The window
  // start (its "from" month, as an ISO date) narrows the reported result.
  const forecastDuration = fcWindow ? durationThrough(origin, fcWindow.through, grain) : duration;
  const forecastWindowStart = fcWindow
    ? `${fcWindow.from.y}-${String(fcWindow.from.m).padStart(2, "0")}-01`
    : null;

  // A freshly detected file snaps the start date to a sensible default.
  useEffect(() => {
    if (!dataRange) return;
    const { def } = dateBounds(dataRange, tab);
    setYear(def.y);
    setMonth(def.m);
    // Only when the file changes, not on every tab flip.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataRange]);

  // Keep the selection inside what the active tab allows (e.g. after switching
  // to Accuracy, a future forecast start snaps back into the data).
  useEffect(() => {
    const cur = { y: year, m: month };
    if (cmp(cur, bounds.min) < 0 || cmp(cur, bounds.max) > 0) {
      setYear(bounds.def.y);
      setMonth(bounds.def.m);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const changeYear = (y) => {
    const { lo, hi } = monthRangeForYear(bounds, y);
    setYear(y);
    setMonth((m) => Math.min(Math.max(m, lo), hi));
  };

  useEffect(() => {
    if (!active.busy) return;
    const startedAt = Date.now();
    setElapsed(0);
    const id = setInterval(() => setElapsed(Date.now() - startedAt), 500);
    return () => clearInterval(id);
  }, [active.busy]);

  const run = async () => {
    if (!catalog || catalog.empty) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setActive({ rows: null, error: null, busy: true });

    try {
      let rows;
      if (tab === "forecast") {
        // Always forward from the data edge; a window narrows what's reported.
        rows = await forecastCatalog(forecastDuration, {
          windowStart: forecastWindowStart,
          signal: controller.signal,
        });
      } else {
        // Accuracy backtests a chosen in-history window.
        const startDate = `${year}-${String(month).padStart(2, "0")}-01`;
        rows = await scoreCatalogAccuracy(startDate, duration, { signal: controller.signal });
      }
      setActive({ rows, error: null, busy: false });
      // A forecast records a run in the ledger - refresh the track record.
      if (tab === "forecast") setLedgerToken((t) => t + 1);
    } catch (err) {
      if (err.name === "AbortError") {
        setActive({ rows: null, error: null, busy: false });
        return;
      }
      setActive({ rows: null, error: err.message, busy: false });
    } finally {
      abortRef.current = null;
    }
  };

  // Import/sync a sales file into the catalog, then reopen onto the fresh state.
  const doImport = async (f) => {
    setActive({ ...active, error: null });
    setImporting(true);
    try {
      await importSales(f);
      await refreshCatalog();
      // Synced sales may have graded past forecasts - refresh the track record.
      setLedgerToken((t) => t + 1);
    } catch (err) {
      setActive({ ...active, error: err.message });
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center gap-6 border-b border-[var(--line)] bg-[var(--surface)] px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <Mark />
          <span className="font-semibold tracking-tight">Insighta</span>
        </div>

        <nav className="flex items-center gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                tab === t.id
                  ? "bg-[var(--surface-3)] text-[var(--ink)]"
                  : "text-[var(--ink-3)] hover:bg-[var(--surface-2)] hover:text-[var(--ink-2)]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="ml-auto rounded-lg p-2 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-72 shrink-0 border-r border-[var(--line)] bg-[var(--surface)]">
          <ControlPanel
            catalog={catalog}
            importing={importing}
            onImport={doImport}
            onReject={(message) => setActive({ ...active, error: message })}
            year={year}
            month={month}
            duration={duration}
            grain={grain}
            bounds={bounds}
            onYear={changeYear}
            onMonth={setMonth}
            onDuration={setDuration}
            onSubmit={run}
            onCancel={() => abortRef.current?.abort()}
            busy={active.busy}
            elapsed={elapsed}
            mode={tab}
            origin={origin}
            fcWindow={fcWindow}
            onWindow={setFcWindow}
            forecastDuration={forecastDuration}
            submitLabel={tab === "forecast" ? "Generate forecast" : "Score accuracy"}
            busyLabel={tab === "forecast" ? "Forecasting…" : "Scoring accuracy…"}
          />
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto p-5">
          {active.error && (
            <div className="mb-4">
              <ErrorNote onDismiss={() => setActive({ ...active, error: null })}>
                {active.error}
              </ErrorNote>
            </div>
          )}

          {tab === "ledger" && <Ledger reloadToken={ledgerToken} />}

          {tab !== "ledger" && active.busy && <RunningState tab={tab} />}

          {tab !== "ledger" && !active.busy && !active.rows && !active.error && (
            <EmptyState tab={tab} hasCatalog={!!catalog && !catalog.empty} />
          )}

          {tab !== "ledger" && !active.busy && active.rows?.length === 0 && (
            <Card className="p-10 text-center text-sm text-[var(--ink-3)]">
              No products could be forecast from your catalog. Import a file with a{" "}
              <span className="font-medium text-[var(--ink-2)]">Product Name</span> column and
              monthly{" "}
              <span className="font-medium text-[var(--ink-2)]">Quantity Sold …</span> columns.
            </Card>
          )}

          {!active.busy && active.rows?.length > 0 && tab === "forecast" && (
            <div className="flex min-h-0 flex-col gap-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <SectionLabel>Inventory plan</SectionLabel>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                  <NumField
                    label="Lead time"
                    title="Default supplier resupply time, in days. Products can override this."
                    value={settings?.default_lead_time_days ?? 14}
                    suffix="d"
                    onCommit={(v) => changeSettings({ default_lead_time_days: v })}
                  />
                  <NumField
                    label="Review every"
                    title="How often you reorder, in days — the order must cover lead time plus this."
                    value={settings?.review_period_days ?? 7}
                    suffix="d"
                    onCommit={(v) => changeSettings({ review_period_days: v })}
                  />
                  <label className="inline-flex items-center gap-1.5 text-xs text-[var(--ink-3)]">
                    <span title="Probability of not stocking out. Higher service level = more safety stock.">
                      Service level
                    </span>
                    <Select
                      className="w-auto py-1"
                      value={service.value}
                      onChange={(e) => {
                        const lvl = SERVICE_LEVELS.find((s) => s.value === Number(e.target.value));
                        setService(lvl);
                        changeSettings({ service_level: lvl.value });
                      }}
                    >
                      {SERVICE_LEVELS.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </Select>
                  </label>
                </div>
              </div>
              <KpiStrip rows={active.rows} service={service} settings={settings} />
              <Card className="p-4">
                <ForecastChart rows={active.rows} service={service} settings={settings} />
              </Card>
              <ResultsTable
                rows={active.rows}
                service={service}
                setService={setService}
                settings={settings}
                onInventoryChange={changeInventory}
                grain={grain}
              />
            </div>
          )}

          {!active.busy && active.rows?.length > 0 && tab === "accuracy" && (
            <AccuracyResults rows={active.rows} />
          )}
        </main>
      </div>
    </div>
  );
}

function RunningState({ tab }) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-[var(--surface)] px-4 py-3">
            <div className="shimmer h-2.5 w-20 rounded bg-[var(--surface-3)]" />
            <div className="shimmer mt-2.5 h-5 w-14 rounded bg-[var(--surface-3)]" />
          </div>
        ))}
      </div>
      <Card className="p-4">
        <SectionLabel className="mb-3">
          {tab === "forecast" ? "Building your forecast" : "Scoring model accuracy"}
        </SectionLabel>
        <div className="flex h-40 items-end gap-2">
          {[45, 70, 35, 85, 55, 65, 40, 75, 50, 60].map((h, i) => (
            <div
              key={i}
              className="shimmer flex-1 rounded-t bg-[var(--surface-3)]"
              style={{ height: `${h}%` }}
            />
          ))}
        </div>
      </Card>
    </div>
  );
}

function EmptyState({ tab, hasCatalog }) {
  return (
    <div className="flex h-full min-h-80 items-center justify-center">
      <div className="max-w-sm text-center">
        <div className="mx-auto flex size-11 items-center justify-center rounded-xl border border-[var(--line)] bg-[var(--surface)]">
          <svg className="size-5 text-[var(--ink-3)]" viewBox="0 0 20 20" fill="none">
            <path
              d="M3 16.5V9M7.5 16.5V4M12 16.5v-5M16.5 16.5V7"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
            />
          </svg>
        </div>
        <h2 className="mt-4 text-sm font-semibold">
          {!hasCatalog
            ? "Your catalog is empty"
            : tab === "forecast"
              ? "No forecast yet"
              : "No accuracy report yet"}
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-2)]">
          {!hasCatalog
            ? "Import a CSV or Excel file of monthly sales to build your catalog. After that, the app remembers it — you just sync new sales."
            : tab === "forecast"
              ? "Pick a start month and length, then generate your forecast."
              : "Pick a start month inside your history, then score the model against what actually happened."}
        </p>
      </div>
    </div>
  );
}

// Compact numeric field for the inventory defaults - commits on blur/Enter so a
// keystroke mid-typing doesn't fire a save (and re-forecast-free recompute).
function NumField({ label, title, value, suffix, onCommit }) {
  const [draft, setDraft] = useState(String(value ?? ""));
  useEffect(() => setDraft(String(value ?? "")), [value]);
  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n) && n >= 0 && n !== Number(value)) onCommit(Math.round(n));
    else setDraft(String(value ?? ""));
  };
  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-[var(--ink-3)]" title={title}>
      <span>{label}</span>
      <span className="inline-flex items-center rounded-md border border-[var(--line-strong)] bg-[var(--surface)] focus-within:border-accent-500">
        <input
          type="number"
          min="0"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          className="tnum w-12 bg-transparent px-1.5 py-1 text-right text-[var(--ink)] outline-none"
        />
        {suffix ? <span className="pr-1.5 text-[var(--ink-3)]">{suffix}</span> : null}
      </span>
    </label>
  );
}

function Mark() {
  return (
    <svg className="size-6" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <rect width="28" height="28" rx="7" className="fill-accent-500" />
      <path
        d="M7.5 18.5 12 13l3.5 3.5L20.5 9"
        stroke="white"
        strokeWidth="2.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg className="size-4.5" viewBox="0 0 20 20" fill="none">
      <circle cx="10" cy="10" r="3.6" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M10 2v1.6M10 16.4V18M18 10h-1.6M3.6 10H2M15.7 4.3l-1.1 1.1M5.4 14.6l-1.1 1.1M15.7 15.7l-1.1-1.1M5.4 5.4 4.3 4.3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg className="size-4.5" viewBox="0 0 20 20" fill="none">
      <path
        d="M16.5 11.8A7 7 0 0 1 8.2 3.5a7 7 0 1 0 8.3 8.3Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}
