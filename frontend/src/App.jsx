import { useEffect, useRef, useState } from "react";
import { fetchErrorMetrics, generateForecast } from "./api";
import AccuracyResults from "./components/AccuracyResults";
import ControlPanel from "./components/ControlPanel";
import ForecastChart from "./components/ForecastChart";
import KpiStrip from "./components/KpiStrip";
import ResultsTable from "./components/ResultsTable";
import { Card, ErrorNote, SectionLabel, Select, SERVICE_LEVELS } from "./components/ui";

const TABS = [
  { id: "forecast", label: "Forecast" },
  { id: "accuracy", label: "Accuracy" },
];

const emptyRun = { rows: null, error: null, busy: false };

export default function App() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem("insighta-theme") ?? "light"
  );
  const [tab, setTab] = useState("forecast");

  const [file, setFile] = useState(null);
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(1);
  const [duration, setDuration] = useState(12);

  const [forecast, setForecast] = useState(emptyRun);
  const [accuracy, setAccuracy] = useState(emptyRun);
  const [service, setService] = useState(SERVICE_LEVELS[1]); // 95% default
  const [elapsed, setElapsed] = useState(0);
  const abortRef = useRef(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("insighta-theme", theme);
  }, [theme]);

  const active = tab === "forecast" ? forecast : accuracy;
  const setActive = tab === "forecast" ? setForecast : setAccuracy;

  useEffect(() => {
    if (!active.busy) return;
    const startedAt = Date.now();
    setElapsed(0);
    const id = setInterval(() => setElapsed(Date.now() - startedAt), 500);
    return () => clearInterval(id);
  }, [active.busy]);

  const run = async () => {
    if (!file) return;
    const startDate = `${year}-${String(month).padStart(2, "0")}-01`;
    const controller = new AbortController();
    abortRef.current = controller;
    setActive({ rows: null, error: null, busy: true });

    const request = tab === "forecast" ? generateForecast : fetchErrorMetrics;
    try {
      const rows = await request(file, startDate, duration, { signal: controller.signal });
      setActive({ rows, error: null, busy: false });
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
            file={file}
            onFile={(f) => {
              setFile(f);
              setActive({ ...active, error: null });
            }}
            onReject={(message) => setActive({ ...active, error: message })}
            year={year}
            month={month}
            duration={duration}
            onYear={setYear}
            onMonth={setMonth}
            onDuration={setDuration}
            onSubmit={run}
            onCancel={() => abortRef.current?.abort()}
            busy={active.busy}
            elapsed={elapsed}
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

          {active.busy && <RunningState tab={tab} />}

          {!active.busy && !active.rows && !active.error && <EmptyState tab={tab} hasFile={!!file} />}

          {!active.busy && active.rows?.length === 0 && (
            <Card className="p-10 text-center text-sm text-[var(--ink-3)]">
              No products could be forecast from this file. Check that it has a{" "}
              <span className="font-medium text-[var(--ink-2)]">Product Name</span> column and
              monthly{" "}
              <span className="font-medium text-[var(--ink-2)]">Quantity Sold …</span> columns.
            </Card>
          )}

          {!active.busy && active.rows?.length > 0 && tab === "forecast" && (
            <div className="flex min-h-0 flex-col gap-5">
              <div className="flex items-center justify-between gap-3">
                <SectionLabel>Inventory plan</SectionLabel>
                <label className="inline-flex items-center gap-1.5 text-xs text-[var(--ink-3)]">
                  <span title="Probability of not stocking out. Higher service level = more safety stock.">
                    Service level
                  </span>
                  <Select
                    className="w-auto py-1"
                    value={service.value}
                    onChange={(e) =>
                      setService(SERVICE_LEVELS.find((s) => s.value === Number(e.target.value)))
                    }
                  >
                    {SERVICE_LEVELS.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </Select>
                </label>
              </div>
              <KpiStrip rows={active.rows} service={service} />
              <Card className="p-4">
                <ForecastChart rows={active.rows} service={service} />
              </Card>
              <ResultsTable rows={active.rows} service={service} setService={setService} />
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

function EmptyState({ tab, hasFile }) {
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
          {tab === "forecast" ? "No forecast yet" : "No accuracy report yet"}
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-2)]">
          {hasFile
            ? tab === "forecast"
              ? "Pick a start month and length, then generate your forecast."
              : "Pick a start month inside your data's history, then score the model against what actually happened."
            : "Upload a CSV or Excel file of monthly sales to get started."}
        </p>
      </div>
    </div>
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
