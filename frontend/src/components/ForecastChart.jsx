import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatNumber, recommendation, SectionLabel } from "./ui";

const TOP_N = 12;

// The chart tells the inventory story: for the biggest lines, how much to order
// split into the base forecast and the safety-stock buffer on top (which grows
// with uncertainty and the service level). Stacked, the bar height IS the
// suggested order.
export default function ForecastChart({ rows, service }) {
  const data = useMemo(() => {
    return [...rows]
      .map((r) => {
        const forecast = Number(r.Forecast || 0);
        const rec = recommendation(r, service.z);
        return { name: r.ProductName, sku: r.Sku, forecast, safety: rec.safety, order: rec.order };
      })
      .sort((a, b) => b.order - a.order)
      .slice(0, TOP_N);
  }, [rows, service]);

  if (!data.length) return null;

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <SectionLabel>Suggested order by product</SectionLabel>
        <span className="text-xs text-[var(--ink-3)]">Top {Math.min(TOP_N, data.length)} by order</span>
      </div>

      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 11, fill: "var(--ink-3)" }}
              tickLine={false}
              axisLine={{ stroke: "var(--line)" }}
              interval={0}
              height={48}
              angle={-32}
              textAnchor="end"
              tickFormatter={(v) => (v.length > 14 ? `${v.slice(0, 13)}…` : v)}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "var(--ink-3)" }}
              tickLine={false}
              axisLine={false}
              width={44}
              tickFormatter={formatNumber}
            />
            <Tooltip
              cursor={{ fill: "color-mix(in srgb, var(--ink) 6%, transparent)" }}
              content={<ChartTooltip service={service} />}
            />
            <Bar dataKey="forecast" stackId="a" fill="var(--color-accent-500)" isAnimationActive={false} />
            <Bar
              dataKey="safety"
              stackId="a"
              fill="color-mix(in srgb, var(--color-accent-500) 32%, transparent)"
              radius={[3, 3, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-2 flex items-center gap-4 text-xs text-[var(--ink-3)]">
        <Swatch color="var(--color-accent-500)" label="Forecast demand" />
        <Swatch color="color-mix(in srgb, var(--color-accent-500) 32%, transparent)" label={`Safety stock (${service.label})`} />
      </div>
    </div>
  );
}

function Swatch({ color, label }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="size-2.5 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}

function ChartTooltip({ active, payload, label, service }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-2 shadow-lg">
      <div className="mb-1 text-xs font-semibold">{label}</div>
      <Row label="Forecast" value={d.forecast} />
      <Row label={`Safety (${service.label})`} value={d.safety} />
      <div className="mt-1 border-t border-[var(--line)] pt-1">
        <Row label="Suggested order" value={d.order} strong />
      </div>
    </div>
  );
}

function Row({ label, value, strong }) {
  return (
    <div className="flex items-center justify-between gap-6 text-xs">
      <span className="text-[var(--ink-3)]">{label}</span>
      <span className={`tnum ${strong ? "font-semibold text-accent-600 dark:text-accent-400" : "font-medium"}`}>
        {formatNumber(value)}
      </span>
    </div>
  );
}
