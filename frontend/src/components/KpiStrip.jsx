import { useMemo } from "react";
import { formatNumber, reorder, SectionLabel } from "./ui";

// Centered on the decision the app exists to make: how much to order now, given
// what's on hand and how long resupply takes - not just the raw forecast.
export default function KpiStrip({ rows, service, settings }) {
  const stats = useMemo(() => {
    let forecast = 0, order = 0, reorderCount = 0, grounded = 0;
    for (const r of rows) {
      forecast += Number(r.Forecast || 0);
      const d = reorder(r, settings, service.z);
      order += d.order;
      if (d.hasInventory) {
        grounded += 1;
        if (d.reorderNow) reorderCount += 1;
      }
    }
    return { forecast, order, reorderCount, grounded, products: rows.length };
  }, [rows, service, settings]);

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
      <Kpi label="Forecast demand" value={formatNumber(stats.forecast)} sub="units over horizon" />
      <Kpi
        label="Suggested order"
        value={formatNumber(stats.order)}
        sub={`to order now at ${service.label} service`}
        accent
      />
      <Kpi
        label="Reorder now"
        value={stats.grounded ? formatNumber(stats.reorderCount) : "—"}
        sub={stats.grounded ? `of ${formatNumber(stats.grounded)} with stock set` : "set on-hand to enable"}
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
