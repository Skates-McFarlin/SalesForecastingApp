import { useMemo, useState } from "react";
import { formatNumber, Input, SectionLabel } from "./ui";

const parseMape = (row) => Number(String(row["Error Metrics"].MAPE).replace("%", ""));

export default function AccuracyResults({ rows }) {
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows
      .filter((r) => !q || r.ProductName.toLowerCase().includes(q))
      .sort((a, b) => parseMape(b) - parseMape(a)); // least accurate first - that's what needs attention
  }, [rows, query]);

  const avgMape = useMemo(
    () => (rows.length ? rows.reduce((s, r) => s + parseMape(r), 0) / rows.length : 0),
    [rows]
  );

  return (
    <div className="flex min-h-0 flex-col gap-4">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-2)] px-4 py-3 text-xs leading-relaxed text-[var(--ink-2)]">
        <span className="font-medium text-[var(--ink)]">How this works.</span> The model is retrained
        using only data from before your start date, then its predictions are scored against what
        actually happened. Lower error means the model handles that product well.{" "}
        <span className="font-medium text-[var(--ink)]">MAE</span> and{" "}
        <span className="font-medium text-[var(--ink)]">RMSE</span> are in units;{" "}
        <span className="font-medium text-[var(--ink)]">MAPE</span> is the average error as a
        percentage.
      </div>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-3">
        <Kpi label="Products scored" value={formatNumber(rows.length)} />
        <Kpi label="Average MAPE" value={`${avgMape.toFixed(1)}%`} />
        <Kpi
          label="Within 20% error"
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
              {["Product", "Predicted", "Actual", "MAE", "RMSE", "MAPE"].map((h, i) => (
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
            {visible.map((row) => {
              const mape = parseMape(row);
              return (
                <tr
                  key={row.ProductName}
                  className="border-b border-[var(--line)] hover:bg-[var(--surface-2)]"
                >
                  <td className="px-3 py-2.5 font-medium">{row.ProductName}</td>
                  <td className="tnum px-3 py-2.5 text-right">{formatNumber(row.Forecast)}</td>
                  <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">
                    {formatNumber(row["Actual Sales"])}
                  </td>
                  <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">
                    {row["Error Metrics"].MAE}
                  </td>
                  <td className="tnum px-3 py-2.5 text-right text-[var(--ink-2)]">
                    {row["Error Metrics"].RMSE}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <MapeBadge value={mape} />
                  </td>
                </tr>
              );
            })}
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

function MapeBadge({ value }) {
  if (Number.isNaN(value)) return <span className="text-[var(--ink-3)]">—</span>;
  const tone =
    value <= 20
      ? "text-pos-500 dark:text-pos-400"
      : value <= 50
        ? "text-[var(--ink-2)]"
        : "text-neg-500 dark:text-neg-400";
  return <span className={`tnum text-sm font-medium ${tone}`}>{value.toFixed(1)}%</span>;
}

function Kpi({ label, value }) {
  return (
    <div className="bg-[var(--surface)] px-4 py-3">
      <SectionLabel>{label}</SectionLabel>
      <div className="tnum mt-1.5 text-xl font-semibold tracking-tight">{value}</div>
    </div>
  );
}
