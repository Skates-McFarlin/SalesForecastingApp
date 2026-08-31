import { useMemo, useState } from "react";
import { fetchSummary } from "../api";
import { Badge, DeltaBadge, formatNumber, Input, SectionLabel, Select, Spinner } from "./ui";

const COLUMNS = [
  { key: "ProductName", label: "Product", align: "left" },
  { key: "Forecast", label: "Forecast", align: "right" },
  { key: "Last Year Actual Sales", label: "Last year", align: "right" },
  { key: "% Change from Previous Year", label: "Change", align: "right" },
];

export default function ResultsTable({ rows }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [sort, setSort] = useState({ key: "Forecast", dir: "desc" });
  const [expanded, setExpanded] = useState(null);
  const [summaries, setSummaries] = useState({});

  const categories = useMemo(
    () => [...new Set(rows.map((r) => r.Category).filter((c) => c && c !== "unknown"))].sort(),
    [rows]
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = rows.filter(
      (r) =>
        (!q || r.ProductName.toLowerCase().includes(q)) &&
        (category === "all" || r.Category === category)
    );
    const { key, dir } = sort;
    return [...filtered].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      const an = typeof av === "number" ? av : Number(av);
      const bn = typeof bv === "number" ? bv : Number(bv);
      let cmp;
      if (!Number.isNaN(an) && !Number.isNaN(bn)) cmp = an - bn;
      else if (Number.isNaN(an) && Number.isNaN(bn)) cmp = String(av).localeCompare(String(bv));
      else cmp = Number.isNaN(an) ? 1 : -1; // push N/A to the bottom either way
      return dir === "asc" ? cmp : -cmp;
    });
  }, [rows, query, category, sort]);

  const noPriorYear = rows.every((r) => r["% Change from Previous Year"] === "N/A");

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
    setSort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" }));

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
            placeholder="Search products"
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
        <span className="tnum ml-auto text-xs text-[var(--ink-3)]">
          {visible.length === rows.length
            ? `${rows.length} products`
            : `${visible.length} of ${rows.length}`}
        </span>
      </div>

      {noPriorYear && (
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
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={`px-3 py-2.5 font-medium ${
                    col.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  <button
                    onClick={() => setSortKey(col.key)}
                    className={`inline-flex items-center gap-1 text-[10px] font-semibold tracking-[0.09em] uppercase transition-colors hover:text-[var(--ink)] ${
                      sort.key === col.key ? "text-[var(--ink)]" : "text-[var(--ink-3)]"
                    }`}
                  >
                    {col.label}
                    <SortArrow active={sort.key === col.key} dir={sort.dir} />
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <RowGroup
                key={row.PredictionId}
                row={row}
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
    </div>
  );
}

/* Rendered as sibling <tr>s so an expanded summary spans the full width. */
function RowGroup({ row, isOpen, summary, onToggle }) {
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
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge>{row.Category}</Badge>
            <Badge>{row.Seasonality}</Badge>
          </div>
        </td>
        <td className="tnum px-3 py-2.5 text-right font-medium">{formatNumber(row.Forecast)}</td>
        <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">
          {formatNumber(row["Last Year Actual Sales"])}
        </td>
        <td className="px-3 py-2.5 text-right">
          <DeltaBadge value={row["% Change from Previous Year"]} />
        </td>
      </tr>
      {isOpen && (
        <tr className="border-b border-[var(--line)] bg-accent-500/4">
          <td />
          <td colSpan={4} className="px-3 pt-1 pb-4">
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
