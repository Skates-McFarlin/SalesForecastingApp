import { useMemo } from "react";
import { formatNumber, recommendation, SectionLabel } from "./ui";

// Centered on the decision the app exists to make: how much to order and how
// much of that is safety buffer, at the chosen service level - not just the
// raw forecast.
export default function KpiStrip({ rows, service }) {
  const stats = useMemo(() => {
    let forecast = 0, order = 0, safety = 0;
    for (const r of rows) {
      forecast += Number(r.Forecast || 0);
      const rec = recommendation(r, service.z);
      order += rec.order;
      safety += rec.safety;
    }
    return { forecast, order, safety, products: rows.length };
  }, [rows, service]);

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
      <Kpi label="Forecast demand" value={formatNumber(stats.forecast)} sub="units over horizon" />
      <Kpi
        label="Suggested order"
        value={formatNumber(stats.order)}
        sub={`to meet ${service.label} of demand`}
        accent
      />
      <Kpi
        label="Safety stock"
        value={formatNumber(stats.safety)}
        sub={`buffer at ${service.label} service`}
      />
      <Kpi label="Products" value={formatNumber(stats.products)} sub="SKUs forecast" />
    </div>
  );
}

function Kpi({ label, value, sub, accent }) {
  return (
    <div className="bg-[var(--surface)] px-4 py-3">
      <SectionLabel>{label}</SectionLabel>
      <div
        className={`tnum mt-1.5 text-xl font-semibold tracking-tight ${
          accent ? "text-accent-600 dark:text-accent-400" : ""
        }`}
      >
        {value}
      </div>
      {sub ? <div className="mt-0.5 text-xs text-[var(--ink-3)]">{sub}</div> : null}
    </div>
  );
}
