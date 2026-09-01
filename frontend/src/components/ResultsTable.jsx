import { useEffect, useMemo, useState } from "react";
import { fetchSummary } from "../api";
import { Badge, DeltaBadge, formatNumber, Input, SectionLabel, Select, Spinner } from "./ui";

const BASE_COLUMNS = [
  { key: "ProductName", label: "Product", align: "left" },
  { key: "Forecast", label: "Forecast", align: "right" },
  { key: "__share", label: "Share", align: "right" },
];

const COMPARISON_COLUMNS = [
  { key: "Last Year Actual Sales", label: "Last year", align: "right" },
  { key: "% Change from Previous Year", label: "Change", align: "right" },
];

const THIN_HISTORY_MONTHS = 6;
const MOVER_COUNT = 3;
const PAGE_SIZE_OPTIONS = [25, 50, 100];

// "Biggest mover" means largest swing either direction, so this must be an
// absolute value - a -40% decline is as much a mover as a +40% gain, and a
// signed sort would silently rank every decline below every gain.
const changeMagnitude = (value) => Math.abs(Number(String(value).replace("%", "")));

function csvCell(value) {
  const s = value == null ? "" : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function exportCsv(rows) {
  const headers = [
    "Product", "SKU", "Category", "History (mo)", "Forecast",
    "Share of total", "Last year", "Change",
  ];
  const total = rows.reduce((sum, r) => sum + Number(r.Forecast || 0), 0);
  const lines = [headers.map(csvCell).join(",")];
  for (const r of rows) {
    const share = total > 0 ? ((Number(r.Forecast || 0) / total) * 100).toFixed(1) + "%" : "";
    lines.push(
      [
        r.ProductName,
        r.Sku || "",
        r.Category || "",
        r.HistoryMonths ?? "",
        r.Forecast,
        share,
        r["Last Year Actual Sales"],
        r["% Change from Previous Year"] === "N/A" ? "N/A" : `${r["% Change from Previous Year"]}%`,
      ]
        .map(csvCell)
        .join(",")
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `forecast-results-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ResultsTable({ rows }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  // null = use the computed default for this dataset; a real value once the
  // user clicks a column header. Reset on every new forecast run below.
  const [sort, setSort] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[1]);
  const [expanded, setExpanded] = useState(null);
  const [summaries, setSummaries] = useState({});

  useEffect(() => {
    setSort(null);
    setPage(1);
  }, [rows]);

  const categories = useMemo(
    () => [...new Set(rows.map((r) => r.Category).filter((c) => c && c !== "unknown"))].sort(),
    [rows]
  );

  const hasComparison = rows.some((r) => r["% Change from Previous Year"] !== "N/A");
  // Last Year/Change are only worth their own columns when at least one row
  // has something to show - with zero comparable rows they'd just repeat
  // "0"/"-" down the whole table, which the banner below already explains.
  const columns = hasComparison ? [...BASE_COLUMNS, ...COMPARISON_COLUMNS] : BASE_COLUMNS;

  const totalForecast = useMemo(() => rows.reduce((sum, r) => sum + Number(r.Forecast || 0), 0), [rows]);

  // The biggest movers land first by default - that's what "biggest mover"
  // should mean, not just a badge wherever Forecast-descending put it. With
  // no comparison data anywhere there's no "mover" concept, so fall back to
  // Forecast.
  const effectiveSort = sort ?? (hasComparison ? { key: "__abs_change", dir: "desc" } : { key: "Forecast", dir: "desc" });

  const moverIds = useMemo(() => {
    if (!hasComparison) return new Set();
    return new Set(
      [...rows]
        .filter((r) => r["% Change from Previous Year"] !== "N/A")
        .sort((a, b) => changeMagnitude(b["% Change from Previous Year"]) - changeMagnitude(a["% Change from Previous Year"]))
        .slice(0, MOVER_COUNT)
        .map((r) => r.PredictionId)
    );
  }, [rows, hasComparison]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = rows.filter(
      (r) =>
        (!q ||
          r.ProductName.toLowerCase().includes(q) ||
          (r.Sku || "").toLowerCase().includes(q)) &&
        (category === "all" || r.Category === category)
    );
    const { key, dir } = effectiveSort;
    const valueOf = (row) => {
      if (key === "__abs_change") {
        return row["% Change from Previous Year"] === "N/A" ? NaN : changeMagnitude(row["% Change from Previous Year"]);
      }
      if (key === "__share") {
        return totalForecast > 0 ? Number(row.Forecast || 0) / totalForecast : 0;
      }
      return row[key];
    };
    return [...filtered].sort((a, b) => {
      const av = valueOf(a);
      const bv = valueOf(b);
      const an = typeof av === "number" ? av : Number(av);
      const bn = typeof bv === "number" ? bv : Number(bv);
      let cmp;
      if (!Number.isNaN(an) && !Number.isNaN(bn)) cmp = an - bn;
      else if (Number.isNaN(an) && Number.isNaN(bn)) cmp = String(av).localeCompare(String(bv));
      else cmp = Number.isNaN(an) ? 1 : -1; // push N/A to the bottom either way
      return dir === "asc" ? cmp : -cmp;
    });
  }, [rows, query, category, effectiveSort, totalForecast]);

  // Search/sort/filter reach every row regardless of page - only what's
  // rendered changes. Re-clamp whenever the filtered set or page size shifts
  // out from under the current page (e.g. a search narrows past the last page).
  const pageCount = pageSize === "all" ? 1 : Math.max(1, Math.ceil(visible.length / pageSize));
  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const pageRows = useMemo(() => {
    if (pageSize === "all") return visible;
    const start = (page - 1) * pageSize;
    return visible.slice(start, start + pageSize);
  }, [visible, page, pageSize]);

  const toggle = async (row) => {
    const id = row.PredictionId;
    if (expanded === id) {
      setExpanded(null);
      return;
    }
    setExpanded(id);
    if (summaries[id]?.text || summaries[id]?.loading) return;

    setSummaries((s) => ({ ...s, [id]: { loading: true } }));
    try {
      const text = await fetchSummary(id);
      setSummaries((s) => ({ ...s, [id]: { text } }));
    } catch (err) {
      setSummaries((s) => ({ ...s, [id]: { error: err.message } }));
    }
  };

  const setSortKey = (key) =>
    setSort((s) => ({ key, dir: s?.key === key && s.dir === "desc" ? "asc" : "desc" }));

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1">
          <svg
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--ink-3)]"
            viewBox="0 0 16 16"
            fill="none"
          >
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <Input
            className="pl-9"
            placeholder="Search products or SKUs"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {categories.length > 1 && (
          <Select
            className="w-auto min-w-40"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="all">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        )}
        <button
          onClick={() => exportCsv(visible)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line-strong)] px-3 py-2 text-xs font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
        >
          <svg className="size-3.5" viewBox="0 0 14 14" fill="none">
            <path d="M7 1.5v8M7 9.5 4 6.5M7 9.5l3-3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M1.5 10.5v1a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          Export CSV
        </button>
        <span className="tnum ml-auto text-xs text-[var(--ink-3)]">
          {visible.length === rows.length
            ? `${rows.length} products`
            : `${visible.length} of ${rows.length}`}
        </span>
      </div>

      {!hasComparison && (
        <div className="mb-3 rounded-lg border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5 text-xs leading-relaxed text-[var(--ink-2)]">
          <span className="font-medium text-[var(--ink)]">No year-over-year comparison.</span> Your
          forecast starts beyond the history in this file, so there's no matching prior-year period
          to compare against. Pick a start date within — or just after — your data's range to see
          change figures.
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-[var(--line)]">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-[var(--surface-2)]">
            <tr className="border-b border-[var(--line)]">
              <th className="w-8" />
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`px-3 py-2.5 font-medium ${
                    col.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  <button
                    onClick={() => setSortKey(col.key)}
                    className={`inline-flex items-center gap-1 text-[10px] font-semibold tracking-[0.09em] uppercase transition-colors hover:text-[var(--ink)] ${
                      effectiveSort.key === col.key ? "text-[var(--ink)]" : "text-[var(--ink-3)]"
                    }`}
                  >
                    {col.label}
                    <SortArrow active={effectiveSort.key === col.key} dir={effectiveSort.dir} />
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row) => (
              <RowGroup
                key={row.PredictionId}
                row={row}
                columnCount={columns.length}
                showComparison={hasComparison}
                share={totalForecast > 0 ? (Number(row.Forecast || 0) / totalForecast) * 100 : 0}
                isMover={moverIds.has(row.PredictionId)}
                isOpen={expanded === row.PredictionId}
                summary={summaries[row.PredictionId]}
                onToggle={() => toggle(row)}
              />
            ))}
          </tbody>
        </table>

        {!visible.length && (
          <div className="p-10 text-center text-sm text-[var(--ink-3)]">
            No products match your filters.
          </div>
        )}
      </div>

      {visible.length > PAGE_SIZE_OPTIONS[0] && (
        <div className="mt-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 text-xs text-[var(--ink-3)]">
            Rows per page
            <Select
              className="w-auto py-1"
              value={pageSize}
              onChange={(e) => {
                const v = e.target.value;
                setPageSize(v === "all" ? "all" : Number(v));
                setPage(1);
              }}
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
              <option value="all">All</option>
            </Select>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-md border border-[var(--line-strong)] px-2 py-1 font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)] disabled:opacity-40"
            >
              Prev
            </button>
            <span className="tnum text-[var(--ink-3)]">
              Page {page} of {pageCount}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              disabled={page >= pageCount}
              className="rounded-md border border-[var(--line-strong)] px-2 py-1 font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)] disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* Rendered as sibling <tr>s so an expanded summary spans the full width. */
function RowGroup({ row, columnCount, showComparison, share, isMover, isOpen, summary, onToggle }) {
  const changeValue = row["% Change from Previous Year"];
  const unitDelta =
    changeValue !== "N/A" ? Number(row.Forecast) - Number(row["Last Year Actual Sales"]) : null;

  return (
    <>
      <tr
        onClick={onToggle}
        className={`cursor-pointer border-b border-[var(--line)] transition-colors ${
          isOpen ? "bg-accent-500/6" : "hover:bg-[var(--surface-2)]"
        }`}
      >
        <td className="pl-3">
          <svg
            className={`size-3.5 text-[var(--ink-3)] transition-transform ${isOpen ? "rotate-90" : ""}`}
            viewBox="0 0 14 14"
            fill="none"
          >
            <path d="m5 3 4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </td>
        <td className="px-3 py-2.5">
          <div className="font-medium">{row.ProductName}</div>
          {row.Sku && <div className="tnum mt-0.5 text-[11px] text-[var(--ink-3)]">{row.Sku}</div>}
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge>{row.Category}</Badge>
            {row.HasDataGap && <GapBadge />}
            {isMover && <MoverBadge />}
          </div>
        </td>
        <td className="tnum px-3 py-2.5 text-right font-medium">{formatNumber(row.Forecast)}</td>
        <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">{share.toFixed(1)}%</td>
        {showComparison && (
          <>
            <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">
              {formatNumber(row["Last Year Actual Sales"])}
            </td>
            <td className="px-3 py-2.5 text-right">
              <DeltaBadge value={changeValue} />
              {unitDelta !== null && (
                <div className="tnum mt-0.5 text-[11px] text-[var(--ink-3)]">
                  {unitDelta > 0 ? "+" : ""}
                  {formatNumber(unitDelta)} units
                </div>
              )}
            </td>
          </>
        )}
      </tr>
      {isOpen && (
        <tr className="border-b border-[var(--line)] bg-accent-500/4">
          <td />
          <td colSpan={columnCount} className="px-3 pt-3 pb-4">
            <div className="mb-3 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
              <MiniStat label="Forecast" value={formatNumber(row.Forecast)} />
              <MiniStat
                label="Vs last year"
                value={changeValue === "N/A" ? "—" : <DeltaBadge value={changeValue} />}
              />
              <MiniStat
                label="Confidence range"
                value={
                  row.ForecastLow != null && row.ForecastHigh != null
                    ? `${formatNumber(row.ForecastLow)}–${formatNumber(row.ForecastHigh)}`
                    : "—"
                }
              />
              <MiniStat label="History" value={<HistoryValue months={row.HistoryMonths} />} />
            </div>

            <ForecastBasis method={row.ForecastMethod} model={row.ForecastModel} />

            <SectionLabel className="mb-2">AI analysis</SectionLabel>
            {summary?.loading && (
              <div className="flex items-center gap-2 text-sm text-[var(--ink-2)]">
                <Spinner className="size-3.5 text-accent-500" />
                Writing an analysis for this product…
              </div>
            )}
            {summary?.error && (
              <div className="text-sm text-neg-500 dark:text-neg-400">{summary.error}</div>
            )}
            {summary?.text && (
              <p className="max-w-3xl text-sm leading-relaxed text-[var(--ink-2)]">
                {summary.text}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="bg-[var(--surface)] px-3 py-2">
      <SectionLabel>{label}</SectionLabel>
      <div className="tnum mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}

// Explains how a forecast was produced. A mature SKU uses an ensemble of
// statistical models + a global learner (the unremarkable default, shown
// muted); a thin/new SKU is the interesting case - its seasonal shape was
// inferred/borrowed rather than measured, so the number carries more
// assumption (shown amber).
function ForecastBasis({ method, model }) {
  const cold = model === "seasonal-borrowed";
  let text;
  if (cold) {
    if (method === "category seasonality")
      text = "New product — seasonal shape borrowed from its category";
    else if (method === "overall seasonality")
      text = "New product — seasonal shape borrowed from the whole catalog";
    else if (method && method.startsWith("seasonal prior"))
      text = `New product — seasonal shape inferred from its type (${method.slice(method.indexOf("(") + 1, -1)})`;
    else text = "Limited history — trend only, no seasonal shape applied";
  } else if (model === "intermittent") {
    text = "Erratic on-and-off demand — blended with intermittent-demand models (Croston/TSB)";
  } else if (model === "ensemble") {
    text = "Ensemble of statistical models + a cross-product learner";
  } else if (model) {
    text = `Forecast model: ${model}`;
  } else {
    return null;
  }
  const borrowed = cold;

  return (
    <div
      className={`mb-3 flex items-center gap-1.5 text-[11px] ${
        borrowed ? "text-amber-600 dark:text-amber-400" : "text-[var(--ink-3)]"
      }`}
    >
      <svg className="size-3 shrink-0" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.2" />
        <path d="M7 6.2v3.2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        <circle cx="7" cy="4.4" r="0.6" fill="currentColor" />
      </svg>
      {text}
    </div>
  );
}

function HistoryValue({ months }) {
  if (months == null) return <span className="text-[var(--ink-3)]">—</span>;
  const thin = months < THIN_HISTORY_MONTHS;
  return (
    <span
      title={
        thin
          ? `Only ${months} month${months === 1 ? "" : "s"} of sales history — forecast may be less reliable`
          : `${months} months of sales history`
      }
      className={thin ? "font-medium text-amber-600 dark:text-amber-400" : ""}
    >
      {months} mo
    </span>
  );
}

function GapBadge() {
  return (
    <span
      title="Includes a gap of zero sales in the middle of its history — possibly a stockout, not low demand"
      className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400"
    >
      <svg className="size-3" viewBox="0 0 14 14" fill="none">
        <path d="M7 1.5 13 12.5H1L7 1.5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        <path d="M7 5.5v3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        <circle cx="7" cy="10.2" r="0.6" fill="currentColor" />
      </svg>
      Gap
    </span>
  );
}

function MoverBadge() {
  return (
    <span
      title="One of the largest year-over-year swings in this run"
      className="inline-flex items-center gap-1 rounded-md border border-accent-500/40 bg-accent-500/10 px-1.5 py-0.5 text-[11px] font-medium text-accent-600 dark:text-accent-400"
    >
      <svg className="size-3" viewBox="0 0 14 14" fill="none">
        <path
          d="M2 9.5 5.5 6l2.5 2.5L12 4.5M12 4.5H8.5M12 4.5V8"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      Mover
    </span>
  );
}

function SortArrow({ active, dir }) {
  return (
    <svg
      className={`size-2.5 transition-opacity ${active ? "opacity-100" : "opacity-0"}`}
      viewBox="0 0 10 10"
      fill="none"
      aria-hidden="true"
    >
      <path
        d={dir === "asc" ? "M5 8V2M5 2 2 5M5 2l3 3" : "M5 2v6M5 8l3-3M5 8 2 5"}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
