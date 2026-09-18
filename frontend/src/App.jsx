import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCatalog, importSales, forecastCatalog, scoreCatalogAccuracy,
  fetchSettings, updateSettings, updateProductInventory,
} from "./api";
import { catalogRange } from "./dates";
import AccuracyResults from "./components/AccuracyResults";
import Assistant from "./components/Assistant";
import Exceptions from "./components/Exceptions";
import FileDrop from "./components/FileDrop";
import ForecastChart from "./components/ForecastChart";
import KpiStrip from "./components/KpiStrip";
import Ledger from "./components/Ledger";
import OrderPlan from "./components/OrderPlan";
import ResultsTable from "./components/ResultsTable";
import SkuDrawer from "./components/SkuDrawer";
import { Button, ErrorNote, formatNumber, SectionLabel, Select, SERVICE_LEVELS } from "./components/ui";

const VIEWS = [
  { id: "today", label: "Today" },
  { id: "forecast", label: "Forecast" },
  { id: "buying", label: "Buying" },
  { id: "track", label: "Track record" },
];

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthYear = (s) => {
  if (!s) return "";
  const [y, m] = s.split("-").map(Number);
  return `${MON[(m || 1) - 1]} ${y}`;
};
const emptyRun = { rows: null, error: null, busy: false };

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("insighta-theme") ?? "light");
  const [view, setView] = useState("today");
  const [trackView, setTrackView] = useState("track"); // track record | backtest

  const [forecast, setForecast] = useState(emptyRun);
  const [accuracy, setAccuracy] = useState(emptyRun);
  const [service, setService] = useState(SERVICE_LEVELS[1]); // 95%
  const [settings, setSettings] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [dataRange, setDataRange] = useState(null);
  const [importing, setImporting] = useState(false);
  const [ledgerToken, setLedgerToken] = useState(0);
  const [showImport, setShowImport] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [openSku, setOpenSku] = useState(null); // key of the drilled-in product
  const abortRef = useRef(null);
  const autoRan = useRef(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("insighta-theme", theme);
  }, [theme]);

  const refreshCatalog = () =>
    fetchCatalog()
      .then((c) => { setCatalog(c); setDataRange(catalogRange(c)); return c; })
      .catch(() => setCatalog({ empty: true, products: 0 }));

  useEffect(() => {
    refreshCatalog();
    fetchSettings()
      .then((s) => {
        setSettings(s);
        const match = SERVICE_LEVELS.find((lvl) => lvl.value === s.service_level);
        if (match) setService(match);
      })
      .catch(() => setSettings({ default_lead_time_days: 14, review_period_days: 7, service_level: 0.95, holding_cost_rate: 0.25 }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const grain = catalog?.grain === "weekly" ? "weekly" : "monthly";
  const hasCatalog = !!catalog && !catalog.empty;
  const rangeLabel = hasCatalog && catalog.date_from && catalog.date_to
    ? `${monthYear(catalog.date_from)} – ${monthYear(catalog.date_to)}` : null;
  const horizon = grain === "weekly" ? 8 : 12;

  const changeSettings = (patch) => {
    setSettings((s) => ({ ...s, ...patch }));
    updateSettings(patch).catch(() => {});
  };

  const INV_TO_ROW = {
    on_hand: "OnHand", on_order: "OnOrder", lead_time_days: "LeadTimeDays",
    unit_cost: "UnitCost", price: "Price", moq: "MOQ", case_pack: "CasePack",
  };
  const applyInventory = (key, state) => {
    if (!state) return;
    setForecast((f) => ({ ...f, rows: f.rows?.map((r) => ((r.Sku || r.ProductName) === key ? { ...r, ...state } : r)) }));
  };
  const changeInventory = (key, patch) => {
    const rowPatch = {};
    for (const [k, v] of Object.entries(patch)) rowPatch[INV_TO_ROW[k] ?? k] = v === "" ? null : v;
    setForecast((f) => ({ ...f, rows: f.rows?.map((r) => ((r.Sku || r.ProductName) === key ? { ...r, ...rowPatch } : r)) }));
    updateProductInventory(key, patch).then((s) => applyInventory(key, s)).catch(() => {});
  };

  // The catalog forecast — Today, Forecast and Buying are lenses on this one run.
  const runForecast = async () => {
    if (!hasCatalog) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setForecast({ rows: null, error: null, busy: true });
    try {
      const rows = await forecastCatalog(horizon, { signal: controller.signal });
      setForecast({ rows, error: null, busy: false });
      setLedgerToken((t) => t + 1);
    } catch (err) {
      if (err.name === "AbortError") { setForecast({ rows: null, error: null, busy: false }); return; }
      setForecast({ rows: null, error: err.message, busy: false });
    } finally { abortRef.current = null; }
  };

  const runAccuracy = async () => {
    if (!hasCatalog || !dataRange) return;
    setAccuracy({ rows: null, error: null, busy: true });
    try {
      const start = `${dataRange.min_year}-${String(dataRange.min_month).padStart(2, "0")}-01`;
      const rows = await scoreCatalogAccuracy(start, horizon);
      setAccuracy({ rows, error: null, busy: false });
    } catch (err) {
      setAccuracy({ rows: null, error: err.message, busy: false });
    }
  };

  // Today is the app: scan once automatically when the catalog is ready.
  useEffect(() => {
    if (hasCatalog && !autoRan.current && !forecast.rows && !forecast.busy) {
      autoRan.current = true;
      runForecast();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasCatalog]);

  const doImport = async (f) => {
    setImporting(true);
    try {
      await importSales(f);
      await refreshCatalog();
      autoRan.current = false; // re-scan against the fresh catalog
      setLedgerToken((t) => t + 1);
      setShowImport(false);
    } catch (err) {
      setForecast((s) => ({ ...s, error: err.message }));
    } finally { setImporting(false); }
  };

  const rows = forecast.rows;
  const rowCount = rows?.length ?? 0;

  return (
    <div className="min-h-full">
      <TopBar
        view={view} onView={setView}
        hasCatalog={hasCatalog} products={catalog?.products} rangeLabel={rangeLabel}
        onSync={() => setShowImport(true)} onSettings={() => setShowSettings(true)}
        theme={theme} onTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
      />

      <main className="mx-auto max-w-[1160px] px-8 pb-24 pt-8">
        {forecast.error && (
          <div className="mb-5"><ErrorNote onDismiss={() => setForecast((s) => ({ ...s, error: null }))}>{forecast.error}</ErrorNote></div>
        )}

        {!hasCatalog ? (
          <FirstRun onImport={() => setShowImport(true)} />
        ) : view === "today" ? (
          <Today
            forecast={forecast} settings={settings} service={service}
            onInventoryResult={applyInventory} onRun={runForecast}
            onAsk={() => setView("assistant")} onOpenForecast={() => setView("forecast")}
            onOpenSku={setOpenSku}
          />
        ) : view === "assistant" ? (
          <AssistantView rows={rows} settings={settings} service={service} catalog={catalog} onBack={() => setView("today")} />
        ) : view === "forecast" ? (
          <ForecastView
            forecast={forecast} settings={settings} service={service} setService={setService}
            changeSettings={changeSettings} changeInventory={changeInventory}
            applyInventory={applyInventory} grain={grain} onRun={runForecast}
          />
        ) : view === "buying" ? (
          <Section title="Buying" busy={forecast.busy} rows={rows} onRun={runForecast}
            desc="Plan a budgeted buy, then turn it into purchase orders you can track.">
            <OrderPlan rows={rows || []} settings={settings} service={service}
              onInventoryResult={applyInventory} onOpenSku={setOpenSku} />
          </Section>
        ) : view === "track" ? (
          <TrackView
            trackView={trackView} setTrackView={setTrackView}
            accuracy={accuracy} ledgerToken={ledgerToken} onRunBacktest={runAccuracy}
          />
        ) : null}
      </main>

      {showImport && (
        <Modal title="Import data" onClose={() => setShowImport(false)}>
          <ImportPanel importing={importing} onImport={doImport} onReject={(m) => setForecast((s) => ({ ...s, error: m }))} rangeLabel={rangeLabel} products={catalog?.products} />
        </Modal>
      )}
      {showSettings && settings && (
        <Modal title="Settings" onClose={() => setShowSettings(false)}>
          <SettingsPanel settings={settings} service={service} onService={(lvl) => { setService(lvl); changeSettings({ service_level: lvl.value }); }} onChange={changeSettings} />
        </Modal>
      )}
      {openSku && (() => {
        const row = rows?.find((r) => (r.Sku || r.ProductName) === openSku);
        return row ? (
          <SkuDrawer row={row} settings={settings} service={service}
            onClose={() => setOpenSku(null)}
            onInventoryChange={changeInventory} onInventoryResult={applyInventory} />
        ) : null;
      })()}
    </div>
  );
}

/* ------------------------------------------------------------------ Top bar */
function TopBar({ view, onView, hasCatalog, products, rangeLabel, onSync, onSettings, theme, onTheme }) {
  return (
    <header className="sticky top-0 z-20 flex items-center gap-4 border-b border-[var(--line)] bg-[color-mix(in_srgb,var(--surface)_80%,transparent)] px-6 py-2.5 backdrop-blur-md">
      <div className="flex items-center gap-2.5">
        <Mark />
        <span className="serif text-[20px] font-semibold">Insighta</span>
      </div>
      <div className="mx-1 h-5 w-px bg-[var(--line)]" />
      <nav className="flex items-center gap-0.5">
        {VIEWS.map((v) => (
          <button key={v.id} onClick={() => onView(v.id)}
            className={`rounded-lg px-3 py-1.5 text-[13px] font-semibold transition-colors ${
              view === v.id || (view === "assistant" && v.id === "today")
                ? "bg-accent-50 text-accent-700 dark:bg-accent-600/15 dark:text-accent-300"
                : "text-[var(--ink-3)] hover:bg-[var(--surface-2)] hover:text-[var(--ink-2)]"}`}>
            {v.label}
          </button>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2.5">
        {hasCatalog && (
          <button onClick={onSync} title="Import or sync data"
            className="hidden items-center gap-2 rounded-full border border-[var(--line)] px-3 py-1.5 text-xs font-semibold text-[var(--ink-2)] transition-colors hover:border-accent-500 hover:bg-[var(--surface-2)] md:inline-flex">
            <span className="size-1.5 rounded-full bg-pos-500" />
            <span className="tnum">{formatNumber(products)}</span> products
            {rangeLabel && <span className="text-[var(--ink-3)]">· {rangeLabel}</span>}
          </button>
        )}
        <IconBtn onClick={onSync} title="Import data" label="Import data">
          <svg viewBox="0 0 20 20" fill="none"><path d="M10 13V3m0 0L6.5 6.5M10 3l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /><path d="M3.5 12.5v3a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5v-3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        </IconBtn>
        <IconBtn onClick={onSettings} title="Settings" label="Settings">
          <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="2.6" stroke="currentColor" strokeWidth="1.6" /><path d="M10 2.6v2.1M10 15.3v2.1M17.4 10h-2.1M4.7 10H2.6M15.2 4.8l-1.5 1.5M6.3 13.7l-1.5 1.5M15.2 15.2l-1.5-1.5M6.3 6.3 4.8 4.8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
        </IconBtn>
        <IconBtn onClick={onTheme} title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} label="Toggle theme">
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </IconBtn>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------- Today */
function Today({ forecast, settings, service, onInventoryResult, onRun, onAsk, onOpenForecast, onOpenSku }) {
  if (forecast.busy) return <TodaySkeleton />;
  if (!forecast.rows) return <ScanPrompt onRun={onRun} />;
  return (
    <div className="grid gap-x-8 gap-y-7 lg:grid-cols-[minmax(0,1fr)_384px]">
      <div className="flex min-w-0 flex-col gap-7">
        <Exceptions rows={forecast.rows} settings={settings} service={service}
          onInventoryResult={onInventoryResult} onOpenForecast={onOpenForecast} onOpenSku={onOpenSku} />
        <div>
          <SectionLabel className="mb-2.5">Portfolio</SectionLabel>
          <KpiStrip rows={forecast.rows} service={service} settings={settings} />
        </div>
      </div>
      {/* The assistant rides alongside as a co-pilot, staying in view however long
          the triage list runs, rather than sinking to the bottom of the page. */}
      <aside className="h-fit lg:sticky lg:top-[72px]">
        <AskInsighta onAsk={onAsk} />
      </aside>
    </div>
  );
}

const PROMPTS = [
  "What should I reorder this week?",
  "Which SKUs are overstocked?",
  "Plan a $20k buy",
  "How accurate were we last quarter?",
];
function AskInsighta({ onAsk }) {
  return (
    <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface-2)] p-7">
      <div className="serif text-[20px] font-semibold">Ask Insighta</div>
      <div className="mt-1.5 flex items-center gap-2 text-xs text-[var(--ink-3)]">
        <svg className="size-3.5 text-pos-500" viewBox="0 0 20 20" fill="none"><path d="M4 10.5 8.5 15 16 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
        Every figure is computed from your data — Insighta phrases the answer, it never invents a number.
      </div>
      <button onClick={onAsk}
        className="mt-4 flex w-full items-center gap-3.5 rounded-xl border-[1.5px] bg-[var(--surface)] px-5 py-4 text-left transition-colors hover:border-accent-500"
        style={{ borderColor: "color-mix(in srgb, var(--color-accent-600) 38%, var(--line))" }}>
        <svg className="size-6 shrink-0 text-accent-600" viewBox="0 0 24 24" fill="none"><path d="M12 3l1.8 4.9L18.7 9.7 13.8 11.5 12 16.4 10.2 11.5 5.3 9.7 10.2 7.9 12 3Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" fill="currentColor" /></svg>
        <span className="flex-1 text-base text-[var(--ink-3)]">Ask anything about your inventory, forecasts, or what to do next…</span>
      </button>
      <div className="mt-4 flex flex-wrap gap-2.5">
        {PROMPTS.map((p) => (
          <button key={p} onClick={onAsk}
            className="rounded-full border border-[var(--line)] bg-[var(--surface)] px-3.5 py-2 text-[13px] font-medium text-[var(--ink-2)] transition-colors hover:border-accent-500 hover:text-accent-600">
            {p}
          </button>
        ))}
      </div>
    </section>
  );
}

function AssistantView({ rows, settings, service, catalog, onBack }) {
  return (
    <div className="flex flex-col gap-4">
      <button onClick={onBack} className="inline-flex w-fit items-center gap-1.5 text-[13px] font-semibold text-[var(--ink-3)] hover:text-[var(--ink)]">
        <svg className="size-4" viewBox="0 0 20 20" fill="none"><path d="M12 5l-5 5 5 5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
        Back to Today
      </button>
      {rows?.length ? (
        <Assistant rows={rows} settings={settings} service={service} catalog={catalog} />
      ) : (
        <Empty title="Ask Insighta" desc="Scan your catalog first, then ask about what needs you, how a product's doing, or what to reorder." />
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Forecast */
function ForecastView({ forecast, settings, service, setService, changeSettings, changeInventory, applyInventory, grain, onRun }) {
  if (forecast.busy) return <TodaySkeleton />;
  if (!forecast.rows?.length) return <ScanPrompt onRun={onRun} title="No forecast yet" />;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionLabel>Inventory plan</SectionLabel>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <NumField label="Lead time" value={settings?.default_lead_time_days ?? 14} suffix="d" onCommit={(v) => changeSettings({ default_lead_time_days: v })} />
          <NumField label="Review every" value={settings?.review_period_days ?? 7} suffix="d" onCommit={(v) => changeSettings({ review_period_days: v })} />
          <label className="inline-flex items-center gap-1.5 text-xs text-[var(--ink-3)]">
            <span>Service level</span>
            <Select className="w-auto py-1" value={service.value}
              onChange={(e) => { const lvl = SERVICE_LEVELS.find((s) => s.value === Number(e.target.value)); setService(lvl); changeSettings({ service_level: lvl.value }); }}>
              {SERVICE_LEVELS.map((s) => (<option key={s.value} value={s.value}>{s.label}</option>))}
            </Select>
          </label>
        </div>
      </div>
      <KpiStrip rows={forecast.rows} service={service} settings={settings} />
      <div className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-4"><ForecastChart rows={forecast.rows} service={service} settings={settings} /></div>
      <ResultsTable rows={forecast.rows} service={service} setService={setService} settings={settings}
        onInventoryChange={changeInventory} onInventoryResult={applyInventory} grain={grain} />
    </div>
  );
}

/* ------------------------------------------------------------- Track record */
function TrackView({ trackView, setTrackView, accuracy, ledgerToken, onRunBacktest }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <SectionLabel>{trackView === "backtest" ? "Backtest" : ""}</SectionLabel>
        <Segmented value={trackView} onChange={setTrackView}
          options={[{ id: "track", label: "Track record" }, { id: "backtest", label: "Backtest" }]} />
      </div>
      {trackView === "track" ? (
        <Ledger reloadToken={ledgerToken} />
      ) : accuracy.busy ? (
        <TodaySkeleton />
      ) : accuracy.rows?.length ? (
        <AccuracyResults rows={accuracy.rows} />
      ) : accuracy.error ? (
        <BacktestPrompt onRun={onRunBacktest} cta="Try again"
          msg={<span className="text-neg-500 dark:text-neg-400">Backtest failed: {accuracy.error}</span>} />
      ) : accuracy.rows ? (
        // Ran, but nothing was scoreable (rows === []): usually too little history.
        <BacktestPrompt onRun={onRunBacktest} cta="Run again"
          msg="Not enough history to backtest yet — each product needs enough past periods to hold some out and score against. Import a longer sales history (e.g. a wider Amazon Orders date range) and try again." />
      ) : (
        <BacktestPrompt onRun={onRunBacktest} cta="Run backtest"
          msg="Score the model against what actually happened in your history — an honest, out-of-sample backtest." />
      )}
    </div>
  );
}

function BacktestPrompt({ msg, cta, onRun }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-12 text-center">
      <p className="max-w-md text-sm text-[var(--ink-2)]">{msg}</p>
      <Button onClick={onRun}>{cta}</Button>
    </div>
  );
}

/* ------------------------------------------------------------ small pieces */
function Section({ title, desc, busy, rows, onRun, children }) {
  if (busy) return <TodaySkeleton />;
  if (!rows?.length) return <ScanPrompt onRun={onRun} title={`No data for ${title.toLowerCase()} yet`} desc={desc} />;
  return (
    <div className="flex flex-col gap-4">
      <div><SectionLabel className="mb-1">{title}</SectionLabel>{desc && <p className="max-w-2xl text-sm text-[var(--ink-2)]">{desc}</p>}</div>
      {children}
    </div>
  );
}

function IconBtn({ onClick, title, label, children }) {
  return (
    <button onClick={onClick} title={title} aria-label={label}
      className="grid size-9 place-items-center rounded-lg border border-[var(--line)] bg-[var(--surface)] text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--ink)] [&_svg]:size-[17px]">
      {children}
    </button>
  );
}

function NumField({ label, value, suffix, onCommit }) {
  const [draft, setDraft] = useState(String(value ?? ""));
  useEffect(() => setDraft(String(value ?? "")), [value]);
  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n) && n >= 0 && n !== Number(value)) onCommit(Math.round(n));
    else setDraft(String(value ?? ""));
  };
  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-[var(--ink-3)]">
      <span>{label}</span>
      <span className="inline-flex items-center rounded-md border border-[var(--line-strong)] bg-[var(--surface)] focus-within:border-accent-500">
        <input type="number" min="0" value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          className="tnum w-12 bg-transparent px-1.5 py-1 text-right text-[var(--ink)] outline-none" />
        {suffix ? <span className="pr-1.5 text-[var(--ink-3)]">{suffix}</span> : null}
      </span>
    </label>
  );
}

function Segmented({ value, onChange, options }) {
  return (
    <div className="inline-flex rounded-lg border border-[var(--line-strong)] bg-[var(--surface-2)] p-0.5 text-xs font-semibold">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          className={`rounded-md px-2.5 py-1 transition-colors ${value === o.id ? "bg-[var(--surface)] text-[var(--ink)]" : "text-[var(--ink-3)] hover:text-[var(--ink-2)]"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-[rgba(20,17,12,0.28)] p-4 pt-24" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl border border-[var(--line)] bg-[var(--surface)] [box-shadow:var(--shadow)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--line)] px-5 py-3.5">
          <span className="serif text-lg font-semibold">{title}</span>
          <button onClick={onClose} aria-label="Close" className="grid size-8 place-items-center rounded-lg text-[var(--ink-3)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)]">
            <svg className="size-4" viewBox="0 0 20 20" fill="none"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

// What the importer accepts, in the order a seller usually adds them. Each file
// is optional and additive - import as many as you have and they compound.
const IMPORT_SOURCES = [
  { t: "Amazon Orders report", d: "sales history → forecasts" },
  { t: "FBA Inventory report", d: "current on-hand" },
  { t: "Storage Fees + Inventory Age", d: "real fee & aged-surcharge warnings" },
  { t: "A SKU + Unit Cost sheet", d: "your COGS, for buy plans" },
];

function ImportPanel({ importing, onImport, onReject, rangeLabel, products }) {
  const [file, setFile] = useState(null);
  return (
    <div className="flex flex-col gap-3.5">
      {products != null ? (
        <p className="text-sm text-[var(--ink-2)]">
          Your catalog has <b className="text-[var(--ink)]">{formatNumber(products)}</b> products{rangeLabel ? ` (${rangeLabel})` : ""}. Drop another export — newer sales, stock, fees, or costs — and it merges in. The app re-scans automatically.
        </p>
      ) : (
        <p className="text-sm text-[var(--ink-2)]">
          Drop any Seller Central export and it builds your catalog. Import as many as you have — each adds to the picture.
        </p>
      )}
      <ul className="flex flex-col gap-1.5 rounded-xl border border-[var(--line)] bg-[var(--surface-2)] p-3.5">
        {IMPORT_SOURCES.map((s) => (
          <li key={s.t} className="flex items-start gap-2 text-[13px]">
            <svg className="mt-0.5 size-3.5 shrink-0 text-pos-500" viewBox="0 0 20 20" fill="none"><path d="M4 10.5 8.5 15 16 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
            <span><b className="font-semibold text-[var(--ink)]">{s.t}</b> <span className="text-[var(--ink-3)]">— {s.d}</span></span>
          </li>
        ))}
      </ul>
      <FileDrop file={file} onSelect={setFile} onReject={onReject} />
      <Button disabled={!file || importing} onClick={() => file && onImport(file)}>
        {importing ? "Importing…" : "Import file"}
      </Button>
      <p className="text-center text-[11px] text-[var(--ink-3)]">
        Files are read on this computer and never uploaded. A plain CSV/Excel (Shopify, Square, any POS) works too.
      </p>
    </div>
  );
}

function SettingsPanel({ settings, service, onService, onChange }) {
  return (
    <div className="flex flex-col gap-4">
      <SettingRow label="Default lead time" hint="Typical supplier resupply time. Products can override it.">
        <NumField label="" value={settings.default_lead_time_days ?? 14} suffix="d" onCommit={(v) => onChange({ default_lead_time_days: v })} />
      </SettingRow>
      <SettingRow label="Review every" hint="How often you reorder. Orders must cover lead time plus this.">
        <NumField label="" value={settings.review_period_days ?? 7} suffix="d" onCommit={(v) => onChange({ review_period_days: v })} />
      </SettingRow>
      <SettingRow label="Service level" hint="Probability of not stocking out. Higher = more safety stock.">
        <Select className="w-auto py-1" value={service.value} onChange={(e) => onService(SERVICE_LEVELS.find((s) => s.value === Number(e.target.value)))}>
          {SERVICE_LEVELS.map((s) => (<option key={s.value} value={s.value}>{s.label}</option>))}
        </Select>
      </SettingRow>
      <SettingRow label="Holding cost / yr" hint="Annual cost to hold a unit, as a fraction of its cost.">
        <NumField label="" value={Math.round((settings.holding_cost_rate ?? 0.25) * 100)} suffix="%" onCommit={(v) => onChange({ holding_cost_rate: v / 100 })} />
      </SettingRow>
    </div>
  );
}
function SettingRow({ label, hint, children }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div><div className="text-sm font-semibold">{label}</div><div className="mt-0.5 text-xs text-[var(--ink-3)]">{hint}</div></div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

/* --------------------------------------------------------------- states */
function ScanPrompt({ onRun, title = "See what needs you", desc = "Scan your catalog to surface stockout risks, overdue deliveries, overstock, and sharp demand shifts — ranked by dollars at risk." }) {
  return (
    <div className="flex min-h-80 items-center justify-center">
      <div className="max-w-sm text-center">
        <div className="mx-auto grid size-12 place-items-center rounded-2xl border border-[var(--line)] bg-[var(--surface)] text-[var(--ink-3)]">
          <svg className="size-6" viewBox="0 0 20 20" fill="none"><path d="M10 2.5a4.5 4.5 0 0 0-4.5 4.5c0 3.5-1.5 4.5-1.5 4.5h12s-1.5-1-1.5-4.5A4.5 4.5 0 0 0 10 2.5ZM8.5 15a1.5 1.5 0 0 0 3 0" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </div>
        <h2 className="serif mt-4 text-xl font-semibold">{title}</h2>
        <p className="mt-2 text-sm leading-relaxed text-[var(--ink-2)]">{desc}</p>
        <Button className="mt-5" onClick={onRun}>Scan my catalog</Button>
      </div>
    </div>
  );
}

function FirstRun({ onImport }) {
  return (
    <div className="flex min-h-80 items-center justify-center">
      <div className="max-w-sm text-center">
        <div className="mx-auto grid size-12 place-items-center rounded-2xl border border-[var(--line)] bg-[var(--surface)] text-[var(--ink-3)]">
          <svg className="size-6" viewBox="0 0 24 24" fill="none"><path d="M12 15.5V4m0 0L7.5 8.5M12 4l4.5 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        </div>
        <h2 className="serif mt-4 text-xl font-semibold">Welcome to Insighta</h2>
        <p className="mt-2 text-sm leading-relaxed text-[var(--ink-2)]">Import your Amazon Seller Central exports — orders, FBA inventory, fees — to build your catalog. Add your costs and the app plans your buys. Your data stays on this computer.</p>
        <Button className="mt-5" onClick={onImport}>Import your data</Button>
      </div>
    </div>
  );
}

function Empty({ title, desc }) {
  return (
    <div className="flex min-h-60 items-center justify-center rounded-2xl border border-[var(--line)] bg-[var(--surface)]">
      <div className="max-w-sm text-center"><h2 className="serif text-lg font-semibold">{title}</h2><p className="mt-1.5 text-sm text-[var(--ink-2)]">{desc}</p></div>
    </div>
  );
}

function TodaySkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="shimmer h-9 w-56 rounded-lg bg-[var(--surface-3)]" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => (<div key={i} className="h-20 rounded-xl border border-[var(--line)] bg-[var(--surface)]"><div className="shimmer m-3.5 h-3 w-20 rounded bg-[var(--surface-3)]" /><div className="shimmer mx-3.5 h-6 w-14 rounded bg-[var(--surface-3)]" /></div>))}</div>
      <div className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5"><div className="shimmer h-40 rounded bg-[var(--surface-3)]" /></div>
    </div>
  );
}

/* ------------------------------------------------------------------- marks */
function Mark() {
  return (
    <svg className="size-7" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <rect width="28" height="28" rx="8" className="fill-accent-600" />
      <path d="M6 18.5 10.5 13.5 13.7 16.5 18.7 9.5" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="19.4" cy="8.9" r="1.7" fill="white" />
    </svg>
  );
}
function SunIcon() {
  return (<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="3.6" stroke="currentColor" strokeWidth="1.5" /><path d="M10 2v1.6M10 16.4V18M18 10h-1.6M3.6 10H2M15.7 4.3l-1.1 1.1M5.4 14.6l-1.1 1.1M15.7 15.7l-1.1-1.1M5.4 5.4 4.3 4.3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>);
}
function MoonIcon() {
  return (<svg viewBox="0 0 20 20" fill="none"><path d="M16.5 11.8A7 7 0 0 1 8.2 3.5a7 7 0 1 0 8.3 8.3Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></svg>);
}
