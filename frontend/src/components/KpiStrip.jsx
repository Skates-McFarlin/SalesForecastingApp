import { useMemo } from "react";
import { DeltaBadge, formatNumber, SectionLabel } from "./ui";

export default function KpiStrip({ rows }) {
  const stats = useMemo(() => {
    const forecast = rows.reduce((sum, r) => sum + Number(r.Forecast || 0), 0);
    const lastYear = rows.reduce((sum, r) => sum + Number(r["Last Year Actual Sales"] || 0), 0);
    const categories = new Set(rows.map((r) => r.Category).filter((c) => c && c !== "unknown"));
    return {
      forecast,
      lastYear,
      change: lastYear > 0 ? ((forecast - lastYear) / lastYear) * 100 : "N/A",
      products: rows.length,
      categories: categories.size,
    };
  }, [rows]);

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
      <Kpi label="Forecast units" value={formatNumber(stats.forecast)} />
      <Kpi
        label="Vs last year"
        value={<DeltaBadge value={stats.change} />}
        sub={stats.lastYear > 0 ? `${formatNumber(stats.lastYear)} last year` : "No prior period"}
      />
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
