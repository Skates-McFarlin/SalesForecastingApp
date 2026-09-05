import { useMemo, useState } from "react";
import { formatNumber, Input, SectionLabel, Stat } from "./ui";

const parseMape = (row) => Number(String(row["Error Metrics"].MAPE).replace("%", ""));
// MASE is null when undefined (flat training series); keep those out of stats/sort.
const parseMase = (row) => {
  const v = row["Error Metrics"].MASE;
  return v == null ? null : Number(v);
};

export default function AccuracyResults({ rows }) {
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows
      .filter((r) => !q || r.ProductName.toLowerCase().includes(q))
      // Least accurate first — that's what needs attention. Sort by MASE (scale-
      // free, honest on intermittent SKUs); rows without a MASE fall to the bottom.
      .sort((a, b) => {
        const ma = parseMase(a), mb = parseMase(b);
        if (ma == null && mb == null) return parseMape(b) - parseMape(a);
        if (ma == null) return 1;
        if (mb == null) return -1;
        return mb - ma;
      });
  }, [rows, query]);

  const scored = useMemo(() => rows.map(parseMase).filter((v) => v != null), [rows]);
  const avgMase = scored.length ? scored.reduce((s, v) => s + v, 0) / scored.length : null;
  const beatNaive = scored.filter((v) => v < 1).length;

  return (
    <div className="flex min-h-0 flex-col gap-4">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-2)] px-4 py-3 text-xs leading-relaxed text-[var(--ink-2)]">
        <span className="font-medium text-[var(--ink)]">How this works.</span> The model is retrained
        using only data from before your start date, then its predictions are scored against what
        actually happened.{" "}
        <span className="font-medium text-[var(--ink)]">MASE</span> is the headline: it scales error
        against a naive one-step forecast, so it’s comparable across products and honest on
        intermittent, low-volume SKUs — <span className="font-medium text-[var(--ink)]">below 1.0
        means the model beats naive</span>. <span className="font-medium text-[var(--ink)]">MAE</span>{" "}
        and <span className="font-medium text-[var(--ink)]">RMSE</span> are in units;{" "}
        <span className="font-medium text-[var(--ink)]">MAPE</span> is the average percentage error
        (it can distort on near-zero demand).
      </div>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
        <Stat label="Products scored" value={formatNumber(rows.length)} />
        <Stat label="Average MASE" value={avgMase == null ? "—" : avgMase.toFixed(2)} sub="lower is better · 1.0 = naive" />
        <Stat
          label="Beat naive"
          value={scored.length ? `${beatNaive} of ${scored.length}` : "—"}
          sub="MASE below 1.0"
          accent
        />
        <Stat
          label="Within 20% (MAPE)"
          value={`${rows.filter((r) => parseMape(r) <= 20).length} of ${rows.length}`}
        />
      </div>

      <div className="flex items-center gap-2">
        <Input
          className="max-w-xs"
          placeholder="Search products"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="ml-auto text-xs text-[var(--ink-3)]">Least accurate first</span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-[var(--line)]">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-[var(--surface-2)]">
            <tr className="border-b border-[var(--line)]">
              {["Product", "Predicted", "Actual", "MASE", "MAE", "RMSE", "MAPE"].map((h, i) => (
                <th
                  key={h}
                  className={`px-3 py-2.5 text-[10px] font-semibold tracking-[0.09em] text-[var(--ink-3)] uppercase ${
                    i === 0 ? "text-left" : "text-right"
                  }`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr
                key={row.Sku || `${row.ProductName}-${i}`}
                className="border-b border-[var(--line)] hover:bg-[var(--surface-2)]"
              >
                <td className="px-3 py-2.5 font-medium">{row.ProductName}</td>
                <td className="tnum px-3 py-2.5 text-right">{formatNumber(row.Forecast)}</td>
                <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">
                  {formatNumber(row["Actual Sales"])}
                </td>
                <td className="px-3 py-2.5 text-right">
                  <MaseBadge value={parseMase(row)} />
                </td>
                <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">
                  {row["Error Metrics"].MAE}
                </td>
                <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">
                  {row["Error Metrics"].RMSE}
                </td>
                <td className="tnum px-3 py-2.5 text-right text-[var(--ink-3)]">
                  {row["Error Metrics"].MAPE}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!visible.length && (
          <div className="p-10 text-center text-sm text-[var(--ink-3)]">
            No products match your search.
          </div>
        )}
      </div>
    </div>
  );
}

// Scale-free skill: <1 beats naive (good), 1–2 workable, >2 poor. — when undefined.
function MaseBadge({ value }) {
  if (value == null || Number.isNaN(value)) return <span className="text-[var(--ink-3)]">—</span>;
  const tone =
    value < 1
      ? "text-pos-500 dark:text-pos-400"
      : value <= 2
        ? "text-[var(--ink-2)]"
        : "text-neg-500 dark:text-neg-400";
  return <span className={`tnum text-sm font-medium ${tone}`}>{value.toFixed(2)}</span>;
}
