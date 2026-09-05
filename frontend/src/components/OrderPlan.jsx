import { useEffect, useMemo, useState } from "react";
import { optimizeBudget } from "../optimize";
import { Card, formatNumber, SectionLabel, Stat } from "./ui";

const money = (n) => `$${Math.round(Number(n) || 0).toLocaleString()}`;
const pct = (x) => `${(x * 100).toFixed(1)}%`;

// Phase 4 - the forecast becomes an input. Given a cash budget, allocate it
// across the whole catalog to maximize expected service (fill rate), spending
// each dollar where it buys the most. Live: drag the budget and watch service
// and the per-SKU allocation move.
export default function OrderPlan({ rows, settings, service }) {
  // The unconstrained plan (budget = Infinity) sets the "fully funded" cost.
  const full = useMemo(
    () => optimizeBudget(rows, settings, service.z, Infinity),
    [rows, settings, service]
  );
  const ideal = Math.round(full.idealCost);

  const [budget, setBudget] = useState(null);
  useEffect(() => {
    // Start fully funded whenever the underlying plan changes.
    setBudget(ideal);
  }, [ideal]);

  const b = budget == null ? ideal : budget;
  const plan = useMemo(
    () => optimizeBudget(rows, settings, service.z, b),
    [rows, settings, service, b]
  );

  if (!ideal) {
    return (
      <Card className="p-10 text-center text-sm text-[var(--ink-2)]">
        Nothing to buy right now — every product with a unit cost is already covered for its
        lead time. Set unit costs and on-hand on the Forecast tab to plan a budgeted buy.
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <SectionLabel className="mb-1">Budget plan</SectionLabel>
        <p className="max-w-2xl text-sm leading-relaxed text-[var(--ink-2)]">
          Fully restocking the catalog costs <span className="font-medium text-[var(--ink)]">{money(ideal)}</span>.
          Set a budget and the app spends it where it buys the most service — using each product’s demand
          distribution, not a flat split.
        </p>
      </div>

      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="text-sm font-medium">Budget</label>
          <div className="flex items-center gap-2">
            <span className="text-sm text-[var(--ink-3)]">$</span>
            <input
              type="number"
              min="0"
              max={ideal}
              value={b}
              onChange={(e) => setBudget(Math.max(0, Math.min(ideal, Number(e.target.value))))}
              className="tnum w-32 rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2 py-1 text-right text-sm outline-none focus:border-accent-500"
            />
            <div className="ml-1 hidden gap-1 sm:flex">
              {[0.25, 0.5, 0.75, 1].map((f) => (
                <button
                  key={f}
                  onClick={() => setBudget(Math.round(ideal * f))}
                  className="rounded-md border border-[var(--line-strong)] px-2 py-1 text-xs text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)]"
                >
                  {f * 100}%
                </button>
              ))}
            </div>
          </div>
        </div>
        <input
          type="range"
          min="0"
          max={ideal}
          step={Math.max(1, Math.round(ideal / 200))}
          value={b}
          onChange={(e) => setBudget(Number(e.target.value))}
          className="mt-3 w-full accent-accent-500"
        />
      </Card>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
        <Stat label="Allocated" value={money(plan.allocatedSpend)} sub={`of ${money(ideal)} needed`} accent />
        <Stat label="Coverage" value={pct(plan.coverage)} sub={`${formatNumber(plan.counts.funded)} funded · ${formatNumber(plan.counts.partial)} partial`} />
        <Stat
          label="Expected service"
          value={pct(plan.expectedService)}
          sub={`${pct(plan.serviceIfNone)} if you skip → ${pct(plan.serviceIfFull)} fully funded`}
        />
        <Stat label="Not funded" value={formatNumber(plan.counts.unfunded)} sub="orders skipped" />
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <SectionLabel>Allocation by product</SectionLabel>
          {plan.noCost > 0 && (
            <span className="text-[11px] text-[var(--ink-3)]">
              {formatNumber(plan.noCost)} product{plan.noCost === 1 ? "" : "s"} excluded (no unit cost)
            </span>
          )}
        </div>
        <div className="overflow-x-auto rounded-xl border border-[var(--line)]">
          <table className="w-full border-collapse text-sm">
            <thead className="bg-[var(--surface-2)]">
              <tr className="border-b border-[var(--line)] text-[10px] font-semibold tracking-[0.09em] text-[var(--ink-3)] uppercase">
                <th className="px-3 py-2 text-left">Product</th>
                <th className="px-3 py-2 text-right">Unit cost</th>
                <th className="px-3 py-2 text-right">Needed</th>
                <th className="px-3 py-2 text-right">Funded</th>
                <th className="px-3 py-2 text-right">Spend</th>
                <th className="px-3 py-2 text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {plan.items.map((it) => (
                <tr key={it.key} className="border-b border-[var(--line)] last:border-b-0">
                  <td className="px-3 py-2">
                    <div className="font-medium">{it.name}</div>
                    {it.sku && <div className="tnum text-[11px] text-[var(--ink-3)]">{it.sku}</div>}
                  </td>
                  <td className="tnum px-3 py-2 text-right text-[var(--ink-2)]">{money(it.cost)}</td>
                  <td className="tnum px-3 py-2 text-right text-[var(--ink-2)]">{formatNumber(it.ideal)}</td>
                  <td className="tnum px-3 py-2 text-right font-medium">{formatNumber(it.allocated)}</td>
                  <td className="tnum px-3 py-2 text-right text-accent-600 dark:text-accent-400">{money(it.spend)}</td>
                  <td className="px-3 py-2 text-right">
                    <StatusBadge status={it.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    funded: { t: "Funded", c: "text-pos-500 dark:text-pos-400" },
    partial: { t: "Partial", c: "text-amber-600 dark:text-amber-400" },
    unfunded: { t: "Skipped", c: "text-[var(--ink-3)]" },
  };
  const s = map[status] || map.unfunded;
  return <span className={`text-xs font-medium ${s.c}`}>{s.t}</span>;
}
