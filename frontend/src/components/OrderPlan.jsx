import { useEffect, useMemo, useState } from "react";
import { optimizeBudget } from "../optimize";
import { createPurchaseOrder, receivePurchaseOrder, cancelPurchaseOrder } from "../api";
import { Button, Card, formatNumber, SectionLabel, Stat } from "./ui";

const money = (n) => `$${Math.round(Number(n) || 0).toLocaleString()}`;
const pct = (x) => `${(x * 100).toFixed(1)}%`;

// Phase 4 - the forecast becomes an input. Given a cash budget, allocate it
// across the whole catalog to maximize expected service (fill rate), spending
// each dollar where it buys the most. Live: drag the budget and watch service
// and the per-SKU allocation move.
export default function OrderPlan({ rows, settings, service, onInventoryResult, onOpenSku }) {
  // The unconstrained plan (budget = Infinity) sets the "fully funded" cost.
  const full = useMemo(
    () => optimizeBudget(rows, settings, service.z, Infinity),
    [rows, settings, service]
  );
  const ideal = Math.round(full.idealCost);
  // Amazon restock/capacity ceiling (cubic feet of inbound). Only offered when
  // the catalog carries item volumes - i.e. an FBA seller imported the storage
  // report; a cash-only seller sees exactly the plan they saw before.
  const hasCapacity = full.haveVolume > 0 && full.idealVol > 0;
  const idealCap = Math.ceil(full.idealVol);

  const [budget, setBudget] = useState(null);
  const [capacity, setCapacity] = useState(null);
  useEffect(() => {
    // Start fully funded / uncapped whenever the underlying plan changes.
    setBudget(ideal);
    setCapacity(idealCap);
  }, [ideal, idealCap]);

  const b = budget == null ? ideal : budget;
  const cap = !hasCapacity ? Infinity : capacity == null ? idealCap : capacity;
  const plan = useMemo(
    () => optimizeBudget(rows, settings, service.z, b, cap),
    [rows, settings, service, b, cap]
  );

  // Every open PO across the catalog, so Buying is where orders live end to end.
  const openOrders = useMemo(() => {
    const out = [];
    for (const r of rows) {
      const key = r.Sku || r.ProductName;
      for (const po of r.OpenPOs || []) out.push({ ...po, key, name: r.ProductName, sku: r.Sku });
    }
    return out.sort((a, b) => (a.expected_on || "9999").localeCompare(b.expected_on || "9999"));
  }, [rows]);

  const buyable = plan.items.filter((it) => it.allocated > 0);

  // Turn the budget plan into real, trackable purchase orders in one action.
  const [commit, setCommit] = useState({ busy: false, done: null, error: null });
  const createPOs = async () => {
    setCommit({ busy: true, done: null, error: null });
    let made = 0, spent = 0, failed = 0;
    for (const it of buyable) {
      try {
        const state = await createPurchaseOrder(it.key, it.allocated);
        onInventoryResult?.(it.key, state);
        made += 1; spent += it.spend;
      } catch { failed += 1; }
    }
    setCommit({ busy: false, done: { made, spent, failed }, error: failed ? `${failed} order${failed === 1 ? "" : "s"} failed` : null });
  };

  const poResult = async (key, fn) => {
    try { const state = await fn(); onInventoryResult?.(key, state); } catch { /* keep as-is */ }
  };

  if (!ideal && openOrders.length === 0) {
    return (
      <Card className="p-10 text-center text-sm text-[var(--ink-2)]">
        Nothing to buy right now — everything priced is already covered for its lead time.
        If products are missing, import a sheet with on-hand (and ideally SKU + Unit Cost)
        columns, or set them on the Forecast tab, to plan a budgeted buy.
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {ideal > 0 && (<>
      <div>
        <SectionLabel className="mb-1">Budget plan</SectionLabel>
        <p className="max-w-2xl text-sm leading-relaxed text-[var(--ink-2)]">
          Fully restocking the catalog costs <span className="font-medium text-[var(--ink)]">{money(ideal)}</span>
          {hasCapacity && <> and sends <span className="font-medium text-[var(--ink)]">{formatNumber(idealCap)} {full.capUnit}</span> into FBA</>}.
          Set a budget{hasCapacity && " and an Amazon restock limit"} and the app spends {hasCapacity ? "both" : "it"} where {hasCapacity ? "they buy" : "it buys"} the most service — using each product’s demand
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

      {hasCapacity && (
        <Card className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <label className="text-sm font-medium">Amazon restock limit</label>
              <div className="text-[11px] text-[var(--ink-3)]">
                Inbound capacity Amazon will accept ({full.capUnit}) — set by your IPI score in Capacity Manager.
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min="0"
                max={idealCap}
                value={Math.round(cap)}
                onChange={(e) => setCapacity(Math.max(0, Math.min(idealCap, Number(e.target.value))))}
                className="tnum w-32 rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2 py-1 text-right text-sm outline-none focus:border-accent-500"
              />
              <span className="text-sm text-[var(--ink-3)]">{full.capUnit}</span>
            </div>
          </div>
          <input
            type="range"
            min="0"
            max={idealCap}
            step={Math.max(1, Math.round(idealCap / 200))}
            value={Math.round(cap)}
            onChange={(e) => setCapacity(Number(e.target.value))}
            className="mt-3 w-full accent-accent-500"
          />
        </Card>
      )}

      <div className={`grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] ${hasCapacity ? "sm:grid-cols-5" : "sm:grid-cols-4"}`}>
        <Stat label="Allocated" value={money(plan.allocatedSpend)} sub={`of ${money(ideal)} needed`} accent />
        {hasCapacity && (
          <Stat
            label="Capacity used"
            value={`${formatNumber(Math.round(plan.allocatedVol))} ${full.capUnit}`}
            sub={plan.capBinding ? `restock limit binding` : `of ${formatNumber(idealCap)} available`}
          />
        )}
        <Stat label="Coverage" value={pct(plan.coverage)} sub={`${formatNumber(plan.counts.funded)} funded · ${formatNumber(plan.counts.partial)} partial`} />
        <Stat
          label="Expected service"
          value={pct(plan.expectedService)}
          sub={`${pct(plan.serviceIfNone)} if you skip → ${pct(plan.serviceIfFull)} fully funded`}
        />
        <Stat label="Not funded" value={formatNumber(plan.counts.unfunded)} sub="orders skipped" />
      </div>

      {/* Commit: the plan becomes real orders you can track and receive. */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--line)] bg-[var(--surface-2)] p-4">
        <div className="min-w-0">
          <div className="text-sm font-semibold">
            {commit.done
              ? `Created ${formatNumber(commit.done.made)} purchase order${commit.done.made === 1 ? "" : "s"} · ${money(commit.done.spent)} committed`
              : `Place ${formatNumber(buyable.length)} order${buyable.length === 1 ? "" : "s"} for ${money(plan.allocatedSpend)}`}
          </div>
          <div className="mt-0.5 text-xs text-[var(--ink-3)]">
            {commit.error
              ? <span className="text-neg-500 dark:text-neg-400">{commit.error}</span>
              : commit.done
                ? "Tracked below as on-order. Receive them as they arrive to update on-hand."
                : "Turns this allocation into tracked purchase orders — on-order goes up and stockout risks clear."}
          </div>
        </div>
        <Button onClick={createPOs} disabled={commit.busy || buyable.length === 0}>
          {commit.busy ? "Placing…" : commit.done ? "Place again" : "Create these POs"}
        </Button>
      </div>

      {plan.estimatedCount > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-300/60 bg-amber-50 px-4 py-3 text-xs dark:border-amber-400/25 dark:bg-amber-400/10">
          <span className="text-[var(--ink-2)]">
            <span className="font-semibold text-amber-700 dark:text-amber-400">{formatNumber(plan.estimatedCount)} product{plan.estimatedCount === 1 ? "" : "s"}</span> use an estimated cost
            ({Math.round(plan.costRatio * 100)}% of price) — Amazon exports don’t include your COGS.
          </span>
          <span className="text-[var(--ink-3)]">
            Import a sheet with <span className="tnum">SKU</span> + <span className="tnum">Unit Cost</span> columns to use real costs.
          </span>
        </div>
      )}

      <div>
        <div className="mb-2 flex items-center justify-between">
          <SectionLabel>Allocation by product</SectionLabel>
          {plan.noCost > 0 && (
            <span className="text-[11px] text-[var(--ink-3)]">
              {formatNumber(plan.noCost)} product{plan.noCost === 1 ? "" : "s"} excluded (no price or cost)
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
                <tr key={it.key}
                  onClick={() => onOpenSku?.(it.key)}
                  className={`border-b border-[var(--line)] last:border-b-0 ${onOpenSku ? "cursor-pointer hover:bg-[var(--surface-2)]" : ""}`}>
                  <td className="px-3 py-2">
                    <div className="font-medium">{it.name}</div>
                    {it.sku && <div className="tnum text-[11px] text-[var(--ink-3)]">{it.sku}</div>}
                  </td>
                  <td className="tnum px-3 py-2 text-right text-[var(--ink-2)]">
                    {money(it.cost)}
                    {it.costEstimated && <span className="ml-1 text-[10px] text-amber-600 dark:text-amber-400" title="Estimated from price - no COGS imported">est</span>}
                  </td>
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
      </>)}

      <OpenOrders orders={openOrders} onReceive={(key, id) => poResult(key, () => receivePurchaseOrder(id))}
        onCancel={(key, id) => poResult(key, () => cancelPurchaseOrder(id))} onOpenSku={onOpenSku} />
    </div>
  );
}

// The other half of Buying: orders already on the way. Consolidated here so a
// plan flows plan -> PO -> track -> receive without hunting through the table.
function OpenOrders({ orders, onReceive, onCancel, onOpenSku }) {
  const [busyId, setBusyId] = useState(null);
  if (!orders.length) return null;
  const totalUnits = orders.reduce((s, o) => s + Number(o.quantity || 0), 0);
  const run = async (id, fn) => { setBusyId(id); await fn(); setBusyId(null); };
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <SectionLabel>On the way</SectionLabel>
        <span className="text-[11px] text-[var(--ink-3)]">
          {formatNumber(orders.length)} open order{orders.length === 1 ? "" : "s"} · {formatNumber(totalUnits)} units
        </span>
      </div>
      <div className="overflow-hidden rounded-xl border border-[var(--line)]">
        {orders.map((o) => (
          <div key={o.id} className="flex items-center gap-3 border-b border-[var(--line)] px-4 py-3 last:border-b-0 hover:bg-[var(--surface-2)]">
            <button onClick={() => onOpenSku?.(o.key)} className={`min-w-0 flex-1 text-left ${onOpenSku ? "cursor-pointer" : "cursor-default"}`}>
              <div className="truncate font-medium">{o.name}</div>
              <div className="text-[11px] text-[var(--ink-3)]">
                <span className="tnum">{formatNumber(o.quantity)}</span> units · placed {o.placed_on}
                {o.expected_on ? <> · <span className="text-[var(--ink-2)]">expected {o.expected_on}</span></> : null}
              </div>
            </button>
            <div className="flex shrink-0 gap-1.5">
              <button onClick={() => run(o.id, () => onReceive(o.key, o.id))} disabled={busyId === o.id}
                className="rounded-md bg-accent-500 px-2.5 py-1 text-xs font-semibold text-white transition-colors hover:bg-accent-600 disabled:opacity-45">Receive</button>
              <button onClick={() => run(o.id, () => onCancel(o.key, o.id))} disabled={busyId === o.id}
                className="rounded-md border border-[var(--line-strong)] px-2.5 py-1 text-xs font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)] disabled:opacity-45">Cancel</button>
            </div>
          </div>
        ))}
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
