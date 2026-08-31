import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatNumber, SectionLabel } from "./ui";

const TOP_N = 12;

export default function ForecastChart({ rows }) {
  const { data, hasPriorYear } = useMemo(() => {
    const sorted = [...rows].sort((a, b) => b.Forecast - a.Forecast).slice(0, TOP_N);
    return {
      data: sorted.map((r) => ({
        name: r.ProductName,
        forecast: r.Forecast,
        lastYear: r["Last Year Actual Sales"],
      })),
      hasPriorYear: rows.some((r) => Number(r["Last Year Actual Sales"]) > 0),
    };
  }, [rows]);

  if (!data.length) return null;

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <SectionLabel>
          {hasPriorYear ? "Forecast vs last year" : "Forecast by product"}
        </SectionLabel>
        <span className="text-xs text-[var(--ink-3)]">
          Top {Math.min(TOP_N, data.length)} by volume
        </span>
      </div>

      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }} barGap={3}>
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
              content={<ChartTooltip hasPriorYear={hasPriorYear} />}
            />
            {/* Animation off: it renders bars at a fraction of their true
                height when StrictMode double-mounts the chart, and a growth
                animation adds nothing to reading the numbers. */}
            {hasPriorYear && (
              <Bar
                dataKey="lastYear"
                radius={[3, 3, 0, 0]}
                fill="var(--line-strong)"
                isAnimationActive={false}
              />
            )}
            <Bar dataKey="forecast" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {data.map((entry) => (
                <Cell key={entry.name} fill="var(--color-accent-500)" />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-2 flex items-center gap-4 text-xs text-[var(--ink-3)]">
        <Swatch color="var(--color-accent-500)" label="Forecast" />
        {hasPriorYear && <Swatch color="var(--line-strong)" label="Last year actual" />}
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

function ChartTooltip({ active, payload, label, hasPriorYear }) {
  if (!active || !payload?.length) return null;
  const forecast = payload.find((p) => p.dataKey === "forecast")?.value;
  const lastYear = payload.find((p) => p.dataKey === "lastYear")?.value;
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-2 shadow-lg">
      <div className="mb-1 text-xs font-semibold">{label}</div>
      <Row label="Forecast" value={forecast} />
      {hasPriorYear && <Row label="Last year" value={lastYear} />}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-6 text-xs">
      <span className="text-[var(--ink-3)]">{label}</span>
      <span className="tnum font-medium">{formatNumber(value)}</span>
    </div>
  );
}
