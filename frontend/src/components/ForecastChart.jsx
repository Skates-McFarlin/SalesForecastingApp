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
import { formatNumber, reorder, SectionLabel } from "./ui";

const TOP_N = 12;

// The chart tells the inventory story: for the lines needing the most, the stock
// you already have (on hand + on order) plus the suggested order on top. Stacked,
// the bar height is the order-up-to target; the accent segment is what to buy.
export default function ForecastChart({ rows, service, settings }) {
  const data = useMemo(() => {
    return [...rows]
      .map((r) => {
        const d = reorder(r, settings, service.z);
        return {
          name: r.ProductName, sku: r.Sku,
          position: d.position, order: d.order, orderUpTo: d.orderUpTo,
        };
      })
      .sort((a, b) => b.order - a.order)
      .slice(0, TOP_N);
  }, [rows, service, settings]);

  if (!data.length) return null;

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <SectionLabel>Suggested order by product</SectionLabel>
        <span className="text-xs text-[var(--ink-3)]">Top {Math.min(TOP_N, data.length)} by order</span>
      </div>

      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 11, fill: "var(--ink-3)" }}
              tickLine={false}
              axisLine={{ stroke: "var(--line)" }}
              interval={0}
              height={96}
              angle={-35}
              textAnchor="end"
              tickMargin={6}
              tickFormatter={(v) => (v.length > 22 ? `${v.slice(0, 21)}…` : v)}
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
              content={<ChartTooltip />}
            />
            <Bar
              dataKey="position"
              stackId="a"
              fill="color-mix(in srgb, var(--ink) 20%, transparent)"
              isAnimationActive={false}
            />
            <Bar
              dataKey="order"
              stackId="a"
              fill="var(--color-accent-500)"
              radius={[3, 3, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-2 flex items-center gap-4 text-xs text-[var(--ink-3)]">
        <Swatch color="color-mix(in srgb, var(--ink) 20%, transparent)" label="On hand + on order" />
        <Swatch color="var(--color-accent-500)" label="Suggested order" />
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

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-2 shadow-lg">
      <div className="mb-1 text-xs font-semibold">{label}</div>
      <Row label="On hand + on order" value={d.position} />
      <Row label="Order up to" value={d.orderUpTo} />
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
