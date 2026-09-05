import { useEffect, useMemo, useState } from "react";
import {
  fetchSummary, createPurchaseOrder, receivePurchaseOrder, cancelPurchaseOrder,
} from "../api";
import {
  Badge, DeltaBadge, formatNumber, Input, reorder, SectionLabel,
  Select, SERVICE_LEVELS, Spinner,
} from "./ui";

const BASE_COLUMNS = [
  { key: "ProductName", label: "Product", align: "left" },
  { key: "Forecast", label: "Forecast", align: "right" },
  { key: "__order", label: "Suggested order", align: "right" },
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

function exportCsv(rows, service, settings) {
  const headers = [
    "Product", "SKU", "Category", "On hand", "On order", "Lead time (d)",
    "Cover (d)", "Forecast", `Suggested order (${service.label})`, "Order up to",
    "Reorder now", "Share of total", "Last year", "Change",
  ];
  const total = rows.reduce((sum, r) => sum + Number(r.Forecast || 0), 0);
  const lines = [headers.map(csvCell).join(",")];
  for (const r of rows) {
    const share = total > 0 ? ((Number(r.Forecast || 0) / total) * 100).toFixed(1) + "%" : "";
    const d = reorder(r, settings, service.z);
    lines.push(
      [
        r.ProductName,
        r.Sku || "",
        r.Category || "",
        r.OnHand ?? "",
        r.OnOrder ?? "",
        d.leadTimeDays,
        d.coverDays == null ? "" : Math.round(d.coverDays),
        r.Forecast,
        d.order,
        d.orderUpTo,
        d.hasInventory ? (d.reorderNow ? "yes" : "no") : "",
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

export default function ResultsTable({ rows, service, setService, settings, onInventoryChange, onInventoryResult, grain = "monthly" }) {
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
      if (key === "__order") {
        return reorder(row, settings, service.z).order;
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
  }, [rows, query, category, effectiveSort, totalForecast, service, settings]);

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
          onClick={() => exportCsv(visible, service, settings)}
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
        <p className="mb-2 flex items-center gap-1.5 text-[11px] text-[var(--ink-3)]">
          <svg className="size-3 shrink-0" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.2" />
            <path d="M7 6.2v3.2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            <circle cx="7" cy="4.4" r="0.6" fill="currentColor" />
          </svg>
          No prior-year comparison — the forecast starts beyond this file's history. Start within your
          data's range to see year-over-year change.
        </p>
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
                dec={reorder(row, settings, service.z)}
                service={service}
                settings={settings}
                onInventoryChange={onInventoryChange}
                onInventoryResult={onInventoryResult}
                isMover={moverIds.has(row.PredictionId)}
                isOpen={expanded === row.PredictionId}
                summary={summaries[row.PredictionId]}
                onToggle={() => toggle(row)}
                grain={grain}
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
function RowGroup({ row, columnCount, showComparison, share, dec, service, settings, onInventoryChange, onInventoryResult, isMover, isOpen, summary, onToggle, grain = "monthly" }) {
  const changeValue = row["% Change from Previous Year"];
  const unitDelta =
    changeValue !== "N/A" ? Number(row.Forecast) - Number(row["Last Year Actual Sales"]) : null;
  const unit = grain === "weekly" ? "wk" : "mo";
  const reviewDays = settings?.review_period_days ?? 7;
  const leadNote =
    dec.leadSource === "learned"
      ? `learned from ${dec.leadObs} order${dec.leadObs === 1 ? "" : "s"}`
      : dec.leadSource === "typed"
        ? "you set"
        : "default";

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
            {dec.reorderNow && <ReorderBadge />}
            {row.HasDataGap && <GapBadge />}
            {isMover && <MoverBadge />}
          </div>
        </td>
        <td className="tnum px-3 py-2.5 text-right font-medium">{formatNumber(row.Forecast)}</td>
        <td className="tnum px-3 py-2.5 text-right font-semibold text-accent-600 dark:text-accent-400">
          {formatNumber(dec.order)}
          {dec.hasInventory && (
            <div className="tnum mt-0.5 text-[11px] font-normal text-[var(--ink-3)]">
              {dec.coverDays == null ? "" : `${Math.round(dec.coverDays)}d cover`}
            </div>
          )}
        </td>
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
              <MiniStat
                label="Suggested order"
                value={formatNumber(dec.order)}
                sub={`order up to ${formatNumber(dec.orderUpTo)}`}
                accent
              />
              <MiniStat
                label="Position"
                value={dec.hasInventory ? formatNumber(dec.position) : "—"}
                sub={dec.hasInventory ? "on hand + on order" : "set on-hand below"}
              />
              <MiniStat
                label="Cover"
                value={dec.coverDays == null ? "—" : `${Math.round(dec.coverDays)} days`}
                sub={`reorder at ${formatNumber(dec.reorderPoint)}`}
              />
              <MiniStat label="Lead time" value={`${dec.leadTimeDays} days`} sub={`${leadNote} · +${reviewDays}d review`} />
            </div>

            <p className="mb-3 text-xs leading-relaxed text-[var(--ink-3)]">
              {dec.hasInventory ? (
                <>
                  You hold{" "}
                  <span className="font-medium text-[var(--ink-2)]">{formatNumber(dec.position)}</span>{" "}
                  (on hand + on order). To cover demand through the {dec.leadTimeDays}-day lead time plus
                  the review cycle at ~{service.label} service, stock up to{" "}
                  <span className="font-medium text-[var(--ink-2)]">{formatNumber(dec.orderUpTo)}</span> — an order of{" "}
                  <span className="font-medium text-accent-600 dark:text-accent-400">{formatNumber(dec.order)}</span>
                  {dec.reorderNow ? " now" : ""}.
                </>
              ) : (
                <>
                  Set this product’s <span className="font-medium text-[var(--ink-2)]">on-hand</span> below to
                  ground the order in what you already have. Until then, it shows the full order-up-to level of{" "}
                  <span className="font-medium text-accent-600 dark:text-accent-400">{formatNumber(dec.order)}</span>{" "}
                  for the {dec.leadTimeDays}-day lead time at ~{service.label} service.
                </>
              )}
            </p>

            <InventoryEditor
              row={row}
              defaultLeadTime={settings?.default_lead_time_days}
              onChange={onInventoryChange}
            />

            <PurchaseOrders row={row} suggestedOrder={dec.order} onResult={onInventoryResult} />

            <PriceWhatIf
              elasticity={row.Elasticity}
              source={row.ElasticitySource}
              forecast={Number(row.Forecast || 0)}
            />

            <ForecastBasis method={row.ForecastMethod} model={row.ForecastModel} />

            {row.ForecastCorrection && <CorrectionNote c={row.ForecastCorrection} />}

            <div className="mb-3 text-[11px] text-[var(--ink-3)]">
              Forecast {formatNumber(row.Forecast)}
              {row.ForecastLow != null && row.ForecastHigh != null
                ? ` (range ${formatNumber(row.ForecastLow)}–${formatNumber(row.ForecastHigh)})`
                : ""}{" "}
              · <HistoryValue months={row.HistoryMonths} unit={unit} /> history
            </div>

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

function MiniStat({ label, value, sub, accent }) {
  return (
    <div className="bg-[var(--surface)] px-3 py-2">
      <SectionLabel>{label}</SectionLabel>
      <div className={`tnum mt-1 text-sm font-semibold ${accent ? "text-accent-600 dark:text-accent-400" : ""}`}>
        {value}
      </div>
      {sub ? <div className="tnum mt-0.5 text-[10px] text-[var(--ink-3)]">{sub}</div> : null}
    </div>
  );
}

const INV_FIELDS = [
  { key: "on_hand", row: "OnHand", label: "On hand" },
  { key: "lead_time_days", row: "LeadTimeDays", label: "Lead time (d)" },
  { key: "unit_cost", row: "UnitCost", label: "Unit cost" },
  { key: "moq", row: "MOQ", label: "MOQ" },
  { key: "case_pack", row: "CasePack", label: "Case pack" },
];

// Per-SKU inventory editor - edits persist to the catalog and recompute the
// order instantly (no re-forecast). An empty field clears that value.
function InventoryEditor({ row, defaultLeadTime, onChange }) {
  const key = row.Sku || row.ProductName;
  return (
    <div className="mb-3 rounded-lg border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5">
      <div className="flex items-baseline justify-between">
        <SectionLabel>Inventory</SectionLabel>
        {row.InventoryUpdatedAt && (
          <span className="text-[10px] text-[var(--ink-3)]">
            on-hand as of {new Date(row.InventoryUpdatedAt).toLocaleDateString()}
          </span>
        )}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
        {INV_FIELDS.map((f) => (
          <InvInput
            key={f.key}
            label={f.label}
            value={row[f.row]}
            placeholder={
              f.key === "lead_time_days" && row[f.row] == null ? `${defaultLeadTime ?? ""}` : ""
            }
            onCommit={(v) => onChange?.(key, { [f.key]: v })}
          />
        ))}
      </div>
    </div>
  );
}

function InvInput({ label, value, placeholder, onCommit }) {
  const [draft, setDraft] = useState(value == null ? "" : String(value));
  useEffect(() => setDraft(value == null ? "" : String(value)), [value]);
  const commit = () => {
    const cur = value == null ? "" : String(value);
    if (draft === cur) return;
    if (draft === "") return onCommit(""); // clear the value
    const n = Number(draft);
    if (Number.isFinite(n) && n >= 0) onCommit(n);
    else setDraft(cur);
  };
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-medium tracking-wide text-[var(--ink-3)] uppercase">
        {label}
      </span>
      <input
        type="number"
        min="0"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
        className="tnum w-full rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2 py-1 text-right text-sm text-[var(--ink)] outline-none focus:border-accent-500"
      />
    </label>
  );
}

// The closed loop (Phase 5): shows when this SKU's forecast was adjusted from its
// own track record — a learned bias and/or a recalibrated interval.
function CorrectionNote({ c }) {
  const bias = c.bias != null && c.bias !== 1 ? c.bias : null;
  const width = c.width != null && c.width !== 1 ? c.width : null;
  if (!bias && !width) return null;
  const parts = [];
  if (bias) parts.push(`forecast ${bias > 1 ? "+" : ""}${Math.round((bias - 1) * 100)}%`);
  if (width) parts.push(width > 1 ? "wider interval" : "tighter interval");
  return (
    <div className="mb-3 flex items-center gap-1.5 text-[11px] text-accent-600 dark:text-accent-400">
      <svg className="size-3 shrink-0" viewBox="0 0 14 14" fill="none">
        <path d="M2 7a5 5 0 0 1 8.5-3.5M12 7a5 5 0 0 1-8.5 3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        <path d="M10.5 1.5v2h-2M3.5 12.5v-2h2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Adjusted from your track record — {parts.join(", ")} (learned over {c.n} cycle{c.n === 1 ? "" : "s"})
    </div>
  );
}

function ReorderBadge() {
  return (
    <span
      title="Stock is at or below the reorder point — order now"
      className="inline-flex items-center gap-1 rounded-md border border-neg-500/40 bg-neg-500/10 px-1.5 py-0.5 text-[11px] font-medium text-neg-500 dark:text-neg-400"
    >
      <svg className="size-3" viewBox="0 0 14 14" fill="none">
        <path d="M7 1.5 13 12.5H1L7 1.5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        <path d="M7 5.5v3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        <circle cx="7" cy="10.2" r="0.6" fill="currentColor" />
      </svg>
      Reorder now
    </span>
  );
}

// Purchase orders (Phase 2.5) - place a replenishment order (tracked as on-order)
// and receive it (moves units into on-hand, and teaches the app this product's
// real lead time). Each action returns the product's refreshed inventory state,
// which the caller merges into the row so the order recomputes live.
function PurchaseOrders({ row, suggestedOrder, onResult }) {
  const key = row.Sku || row.ProductName;
  const openPOs = row.OpenPOs || [];
  const [qty, setQty] = useState(suggestedOrder > 0 ? String(suggestedOrder) : "");
  const [busy, setBusy] = useState(false);

  const run = async (fn) => {
    setBusy(true);
    try {
      const state = await fn();
      onResult?.(key, state);
    } catch {
      /* leave the row as-is on failure */
    }
    setBusy(false);
  };

  return (
    <div className="mb-3 rounded-lg border border-[var(--line)] px-3 py-2.5">
      <SectionLabel className="mb-2">Purchase orders</SectionLabel>
      {openPOs.length > 0 ? (
        <div className="mb-2.5 space-y-1.5">
          {openPOs.map((po) => (
            <div key={po.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="tnum text-[var(--ink-2)]">
                {formatNumber(po.quantity)} units
                <span className="text-[var(--ink-3)]">
                  {" "}· placed {po.placed_on}
                  {po.expected_on ? ` · expected ${po.expected_on}` : ""}
                </span>
              </span>
              <span className="flex gap-1.5">
                <button
                  onClick={(e) => { e.stopPropagation(); run(() => receivePurchaseOrder(po.id)); }}
                  disabled={busy}
                  className="rounded-md bg-accent-500 px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-accent-600 disabled:opacity-45"
                >
                  Receive
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); run(() => cancelPurchaseOrder(po.id)); }}
                  disabled={busy}
                  className="rounded-md border border-[var(--line-strong)] px-2 py-1 text-xs font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)] disabled:opacity-45"
                >
                  Cancel
                </button>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="mb-2.5 text-[11px] leading-relaxed text-[var(--ink-3)]">
          Nothing on the way. Placing an order tracks it as on-order; receiving it moves the units
          into on-hand and teaches the app this product’s real lead time.
        </p>
      )}
      <div className="flex items-center gap-2">
        <input
          type="number"
          min="0"
          value={qty}
          placeholder="qty"
          onChange={(e) => setQty(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          className="tnum w-20 rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2 py-1 text-right text-sm text-[var(--ink)] outline-none focus:border-accent-500"
        />
        <button
          onClick={(e) => { e.stopPropagation(); run(() => createPurchaseOrder(key, Number(qty))); }}
          disabled={busy || !(Number(qty) > 0)}
          className="rounded-md border border-accent-500 px-2.5 py-1 text-xs font-medium text-accent-600 transition-colors hover:bg-accent-500/10 disabled:opacity-45 dark:text-accent-400"
        >
          Create PO
        </button>
        {suggestedOrder > 0 && (
          <button
            onClick={(e) => { e.stopPropagation(); setQty(String(suggestedOrder)); }}
            className="tnum text-[11px] text-[var(--ink-3)] underline-offset-2 hover:underline"
          >
            use suggested {formatNumber(suggestedOrder)}
          </button>
        )}
      </div>
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

const PRICE_DELTAS = [-0.1, 0.1, 0.15, 0.2, 0.3];

// Live "what-if a price change" using the SKU's estimated price elasticity:
// %change in demand = elasticity x %change in price. Client-side, so the
// projection updates instantly as the user tries different price moves.
function PriceWhatIf({ elasticity, source, forecast }) {
  const [delta, setDelta] = useState(-0.1);
  if (elasticity == null) return null;
  const demandChange = elasticity * delta; // fraction
  const projected = Math.max(0, Math.round(forecast * (1 + demandChange)));
  const strength = Math.abs(elasticity) >= 1 ? "elastic" : "inelastic";
  const pct = (x) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(0)}%`;
  return (
    <div className="mb-3 rounded-lg border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <SectionLabel>
          Price sensitivity{source && source !== "own" ? ` · ${source} estimate` : ""}
        </SectionLabel>
        <span className="tnum text-[11px] text-[var(--ink-3)]">
          elasticity {elasticity} ({strength})
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-sm">
        <span className="text-[var(--ink-2)]">If price</span>
        <select
          value={delta}
          onChange={(e) => setDelta(Number(e.target.value))}
          className="rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-1.5 py-0.5 text-sm"
        >
          {PRICE_DELTAS.map((d) => (
            <option key={d} value={d}>
              {pct(d)}
            </option>
          ))}
        </select>
        <span className="text-[var(--ink-2)]">→ demand</span>
        <span
          className={`tnum font-medium ${
            demandChange > 0 ? "text-pos-500 dark:text-pos-400" : "text-neg-500 dark:text-neg-400"
          }`}
        >
          {pct(demandChange)}
        </span>
        <span className="tnum text-[var(--ink-3)]">≈ {formatNumber(projected)} units</span>
      </div>
    </div>
  );
}

function HistoryValue({ months, unit = "mo" }) {
  if (months == null) return <span className="text-[var(--ink-3)]">—</span>;
  const word = unit === "wk" ? "week" : "month";
  const thin = unit === "mo" && months < THIN_HISTORY_MONTHS;
  return (
    <span
      title={
        thin
          ? `Only ${months} ${word}s of sales history — forecast may be less reliable`
          : `${months} ${word}s of sales history`
      }
      className={thin ? "font-medium text-amber-600 dark:text-amber-400" : ""}
    >
      {months} {unit}
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
