import { useMemo } from "react";
import { DeltaBadge, formatNumber, SectionLabel } from "./ui";

export default function KpiStrip({ rows }) {
  const stats = useMemo(() => {
    const forecast = rows.reduce((sum, r) => sum + Number(r.Forecast || 0), 0);
    const lastYear = rows.reduce((sum, r) => sum + Number(r["Last Year Actual Sales"] || 0), 0);
    const categories = new Set(rows.map((r) => r.Category).filter((c) => c && c !== "unknown"));
    const coverages = rows.map((r) => r.HistoryMonths).filter((m) => typeof m === "number");
    const avgCoverage = coverages.length
      ? coverages.reduce((sum, m) => sum + m, 0) / coverages.length
      : null;
    return {
      forecast,
      lastYear,
      change: lastYear > 0 ? ((forecast - lastYear) / lastYear) * 100 : "N/A",
      products: rows.length,
      categories: categories.size,
      avgCoverage,
    };
  }, [rows]);

  const hasPriorYear = stats.lastYear > 0;

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
      <Kpi label="Forecast units" value={formatNumber(stats.forecast)} />
      {/* Second tile always exists so the grid never reshapes between runs -
          it just shows the most useful thing available for this dataset. */}
      {hasPriorYear ? (
        <Kpi
          label="Vs last year"
          value={<DeltaBadge value={stats.change} />}
          sub={`${formatNumber(stats.lastYear)} last year`}
        />
      ) : (
        <Kpi
          label="Data coverage"
          value={stats.avgCoverage != null ? `${stats.avgCoverage.toFixed(0)} mo` : "—"}
          sub="Avg. history per product"
        />
      )}
      <Kpi label="Products" value={formatNumber(stats.products)} />
      <Kpi
        label="Categories"
        value={stats.categories ? formatNumber(stats.categories) : "—"}
      />
    </div>
  );
}

function Kpi({ label, value, sub }) {
  return (
    <div className="bg-[var(--surface)] px-4 py-3">
      <SectionLabel>{label}</SectionLabel>
      <div className="tnum mt-1.5 text-xl font-semibold tracking-tight">{value}</div>
      {sub ? <div className="mt-0.5 text-xs text-[var(--ink-3)]">{sub}</div> : null}
    </div>
  );
}
