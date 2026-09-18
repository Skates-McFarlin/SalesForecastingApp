import { useEffect, useMemo, useState } from "react";
import {
  Area, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { createPurchaseOrder, receivePurchaseOrder, cancelPurchaseOrder } from "../api";
import { formatNumber, reorder, SectionLabel } from "./ui";
import { fbaCarrying } from "../fba";

const money = (n) => `$${Math.round(Number(n) || 0).toLocaleString()}`;
const OVERSTOCK_DAYS = 120; // days of cover before a "no order" SKU reads as overstocked (matches exceptions.js)
const DAY = 86400000;
const fmtDate = (d) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
const addDays = (n) => new Date(Date.now() + n * DAY);
const daysUntil = (iso) => {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : Math.max(0, Math.round((t - Date.now()) / DAY));
};

// The signature view: where this product's stock is heading. Starts at today's
// on-hand, depletes at the forecast daily rate (with a confidence band from its
// spread), and steps back up as each open PO lands. The reorder point and the
// projected stockout are drawn on top, so the decision is visible, not asserted.
function projection(row, d) {
  const r = Math.max(0, Number(row.DailyRate || 0));
  const sigma = Math.max(0, Number(row.DailySigma || 0));
  const onHand = Number(row.OnHand || 0);
  const openPOs = row.OpenPOs || [];

  // Arrivals: each open PO lands on its ETA (or after the mean lead if unknown).
  const arrivals = openPOs
    .map((po) => ({ day: daysUntil(po.expected_on) ?? Math.round(d.leadTimeDays), qty: Number(po.quantity || 0) }))
    .filter((a) => a.qty > 0)
    .sort((a, b) => a.day - b.day);

  // Stockout (no resupply) and horizon.
  const rawStockout = r > 0 ? onHand / r : Infinity;
  const lastEta = arrivals.length ? arrivals[arrivals.length - 1].day : 0;
  const horizon = Math.min(
    180,
    Math.max(Math.round(d.leadTimeDays + (row.reviewDays || 7)) + 10, Math.ceil(rawStockout) + 10, lastEta + 14, 21)
  );

  const data = [];
  let stockoutDay = null;
  for (let day = 0; day <= horizon; day++) {
    const arrived = arrivals.filter((a) => a.day <= day).reduce((s, a) => s + a.qty, 0);
    const expected = Math.max(0, onHand + arrived - r * day);
    const spread = sigma * Math.sqrt(day);
    const low = Math.max(0, onHand + arrived - r * day - 1.6449 * spread);
    const high = onHand + arrived - r * day + 1.6449 * spread;
    if (stockoutDay == null && expected <= 0 && day > 0) stockoutDay = day;
    data.push({ day, date: fmtDate(addDays(day)), expected, band: [low, Math.max(0, high)] });
  }
  // A stockout only "counts" if it happens before the next resupply lands.
  const firstArrival = arrivals.length ? arrivals[0].day : Infinity;
  const stockoutBeforeResupply = stockoutDay != null && stockoutDay < firstArrival;
  return { data, stockoutDay, stockoutBeforeResupply, horizon, arrivals };
}

export default function SkuDrawer({ row, settings, service, onClose, onInventoryChange, onInventoryResult }) {
  // Close on Escape.
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const key = row.Sku || row.ProductName;
  const d = useMemo(() => reorder(row, settings, service.z), [row, settings, service]);
  const proj = useMemo(() => projection({ ...row, reviewDays: settings?.review_period_days }, d), [row, settings, d]);

  // Human rationale: when to order and by when.
  const r = Math.max(0, Number(row.DailyRate || 0));
  const daysToReorder = r > 0 && d.hasInventory ? Math.max(0, (d.position - d.reorderPoint) / r) : null;
  const orderByDate = daysToReorder != null ? addDays(Math.floor(daysToReorder)) : null;
  const cover = d.coverDays;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-[rgba(20,17,12,0.32)] backdrop-blur-[1px]" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-[500px] flex-col overflow-y-auto border-l border-[var(--line)] bg-[var(--surface)] [box-shadow:var(--shadow-lg)] rise">
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-[var(--line)] bg-[color-mix(in_srgb,var(--surface)_88%,transparent)] px-6 py-4 backdrop-blur-md">
          <div className="min-w-0">
            <h2 className="serif truncate text-[22px] font-semibold leading-tight">{row.ProductName}</h2>
            <div className="mt-1 flex items-center gap-2 text-xs text-[var(--ink-3)]">
              {row.Sku && <span className="font-mono">{row.Sku}</span>}
              {row.Category && <span>· {row.Category}</span>}
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="grid size-9 shrink-0 place-items-center rounded-lg text-[var(--ink-3)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)]">
            <svg className="size-4" viewBox="0 0 20 20" fill="none"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
          </button>
        </div>

        <div className="flex flex-col gap-6 px-6 py-6">
          {/* The call */}
          <Rationale row={row} d={d} order={d.order} orderByDate={orderByDate} cover={cover}
            stockoutDay={proj.stockoutBeforeResupply ? proj.stockoutDay : null} unitCost={Number(row.UnitCost) || 0} />

          {/* Projection */}
          <div>
            <SectionLabel className="mb-2.5">Stock projection</SectionLabel>
            <ProjectionChart proj={proj} reorderPoint={d.reorderPoint} />
            <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--ink-3)]">
              <Legend color="var(--color-accent-500)" label="Projected on-hand" />
              <Legend color="color-mix(in srgb, var(--color-accent-500) 20%, transparent)" label="95% range" />
              <Legend color="var(--color-neg-500)" label="Reorder point" dashed />
            </div>
          </div>

          {/* Numbers behind it */}
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-3">
            <Cell label="On hand" value={formatNumber(Number(row.OnHand || 0))} />
            <Cell label="Days of cover" value={cover != null ? formatNumber(Math.round(cover)) : "—"} tone={cover != null && cover < d.leadTimeDays ? "neg" : ""} />
            <Cell label="On order" value={formatNumber(d.onOrder)} />
            <Cell label="Reorder point" value={formatNumber(d.reorderPoint)} />
            <Cell label="Order up to" value={formatNumber(d.orderUpTo)} />
            <Cell label="Lead time" value={`${formatNumber(d.leadTimeDays)}d`} sub={d.leadSource === "learned" ? "learned" : d.leadSource === "typed" ? "set" : "default"} />
          </div>

          {/* Inline inventory edit */}
          <EditInventory row={row} onChange={(patch) => onInventoryChange?.(key, patch)} />

          {/* Purchase orders */}
          <PurchaseOrders row={row} suggested={d.order} onResult={onInventoryResult} />
        </div>
      </aside>
    </div>
  );
}

function Rationale({ row, d, order, orderByDate, cover, stockoutDay, unitCost }) {
  const urgent = d.reorderNow || (stockoutDay != null && stockoutDay <= d.leadTimeDays);
  if (order > 0) {
    return (
      <div className={`rounded-2xl border p-5 ${urgent ? "border-neg-500/35 bg-neg-500/[0.06]" : "border-[var(--line)] bg-[var(--surface-2)]"}`}>
        <div className="display flex flex-wrap items-end gap-x-2.5 text-[24px] font-bold leading-none">
          <span>Order</span>
          <span className={`tnum ${urgent ? "text-neg-500 dark:text-neg-400" : "text-accent-600 dark:text-accent-400"}`}>{formatNumber(order)}</span>
          {orderByDate && <span className="text-[var(--ink-2)]">by {fmtDate(orderByDate)}</span>}
        </div>
        <p className="mt-2.5 text-sm leading-relaxed text-[var(--ink-2)]">
          {stockoutDay != null
            ? <>Projected to run out in <b className="text-[var(--ink)]">{stockoutDay} days</b> — before a new order could arrive. </>
            : d.reorderNow
              ? <>Stock is at or below the reorder point of <b className="text-[var(--ink)]">{formatNumber(d.reorderPoint)}</b>. </>
              : <>Ordering now keeps you above the reorder point through the lead time. </>}
          Brings you up to <b className="text-[var(--ink)]">{formatNumber(d.orderUpTo)}</b>{unitCost > 0 ? <> · about <b className="text-[var(--ink)]">{money(order * unitCost)}</b></> : null}.
        </p>
      </div>
    );
  }
  // Overstocked: no order needed, but sitting on far more than the cycle needs -
  // for an FBA seller that's a storage bleed and aged-surcharge risk, not "well
  // stocked". Surface the same carrying cost the Today card shows.
  if (cover != null && cover >= OVERSTOCK_DAYS) {
    const fba = fbaCarrying(row, Number(row.DailyRate), cover);
    return (
      <div className="rounded-2xl border border-amber-300/60 bg-amber-50 p-5 dark:border-amber-400/25 dark:bg-amber-400/10">
        <div className="display text-[24px] font-bold leading-none text-amber-700 dark:text-amber-400">Overstocked</div>
        <p className="mt-2.5 text-sm leading-relaxed text-[var(--ink-2)]">
          About <b className="text-[var(--ink)]">{formatNumber(Math.round(cover))} days</b> of cover — far more than the reorder cycle needs.
          {fba.monthlyFee ? <> Costing <b className="text-[var(--ink)]">~{money(fba.monthlyFee)}/mo</b> in Amazon fees{fba.modeled ? " (est)" : ""}</> : null}
          {fba.aged ? <>{fba.monthlyFee ? ", with " : " "}<b className="text-[var(--ink)]">{formatNumber(fba.aged.units)}</b> unit{fba.aged.units === 1 ? "" : "s"} past 181 days (aged-surcharge risk)</> : null}
          {fba.monthlyFee || fba.aged ? "." : ""} Pause ordering; consider a promotion or removing the excess.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-pos-500/30 bg-pos-500/[0.06] p-5">
      <div className="display text-[24px] font-bold leading-none text-pos-500 dark:text-pos-400">Well stocked</div>
      <p className="mt-2.5 text-sm leading-relaxed text-[var(--ink-2)]">
        {cover != null ? <>About <b className="text-[var(--ink)]">{formatNumber(Math.round(cover))} days</b> of cover on hand. </> : <>No reorder needed right now. </>}
        Stock sits above the reorder point of <b className="text-[var(--ink)]">{formatNumber(d.reorderPoint)}</b>.
      </p>
    </div>
  );
}

function ProjectionChart({ proj, reorderPoint }) {
  const { data, stockoutDay, stockoutBeforeResupply } = proj;
  const tickEvery = Math.max(1, Math.round(proj.horizon / 6));
  return (
    <div className="h-56 w-full rounded-xl border border-[var(--line)] bg-[var(--surface)] p-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 6, right: 6, bottom: 2, left: 0 }}>
          <defs>
            <linearGradient id="proj-band" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-accent-500)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="var(--color-accent-500)" stopOpacity={0.04} />
            </linearGradient>
          </defs>
          <XAxis dataKey="day" tick={{ fontSize: 10, fill: "var(--ink-3)" }} tickLine={false}
            axisLine={{ stroke: "var(--line)" }} interval={tickEvery - 1}
            tickFormatter={(day) => (day === 0 ? "Today" : data[day]?.date ?? "")} tickMargin={6} />
          <YAxis tick={{ fontSize: 10, fill: "var(--ink-3)" }} tickLine={false} axisLine={false} width={38} tickFormatter={formatNumber} />
          <Tooltip content={<ProjTooltip />} />
          <Area dataKey="band" stroke="none" fill="url(#proj-band)" isAnimationActive={false} />
          <Line dataKey="expected" stroke="var(--color-accent-500)" strokeWidth={2.2} dot={false} isAnimationActive={false} />
          <ReferenceLine y={reorderPoint} stroke="var(--color-neg-500)" strokeDasharray="5 4" strokeWidth={1.3}
            label={{ value: "Reorder", position: "insideTopRight", fontSize: 10, fill: "var(--color-neg-500)" }} />
          {stockoutBeforeResupply && stockoutDay != null && (
            <ReferenceLine x={stockoutDay} stroke="var(--color-neg-500)" strokeWidth={1.3}
              label={{ value: "Stockout", position: "top", fontSize: 10, fill: "var(--color-neg-500)" }} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function ProjTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload.find((x) => x.dataKey === "expected")?.payload;
  if (!p) return null;
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-2 shadow-lg">
      <div className="mb-0.5 text-xs font-semibold">{p.day === 0 ? "Today" : p.date}</div>
      <div className="tnum text-xs text-[var(--ink-2)]">~{formatNumber(p.expected)} on hand</div>
      <div className="tnum text-[11px] text-[var(--ink-3)]">range {formatNumber(p.band[0])}–{formatNumber(p.band[1])}</div>
    </div>
  );
}

function EditInventory({ row, onChange }) {
  const [open, setOpen] = useState(false);
  const fields = [
    { k: "on_hand", label: "On hand", v: row.OnHand },
    { k: "unit_cost", label: "Unit cost", v: row.UnitCost, prefix: "$" },
    { k: "price", label: "Price", v: row.Price, prefix: "$" },
    { k: "lead_time_days", label: "Lead time", v: row.LeadTimeDays, suffix: "d" },
    { k: "moq", label: "Min order", v: row.MOQ },
    { k: "case_pack", label: "Case pack", v: row.CasePack },
  ];
  return (
    <div className="rounded-xl border border-[var(--line)]">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-4 py-3 text-left">
        <SectionLabel>Edit inventory</SectionLabel>
        <svg className={`size-4 text-[var(--ink-3)] transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 20 20" fill="none"><path d="M5 8l5 5 5-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-[var(--line)] px-4 py-4">
          {fields.map((f) => (
            <EditField key={f.k} label={f.label} value={f.v} prefix={f.prefix} suffix={f.suffix}
              onCommit={(val) => onChange({ [f.k]: val })} />
          ))}
        </div>
      )}
    </div>
  );
}

// Show a stored number cleanly (a derived price can carry float noise like
// 321.21999999999997) while keeping full precision for what the user types.
const clean = (v) => (v === "" || v == null ? "" : String(Math.round(Number(v) * 100) / 100));

function EditField({ label, value, prefix, suffix, onCommit }) {
  const [draft, setDraft] = useState(clean(value));
  useEffect(() => setDraft(clean(value)), [value]);
  const commit = () => {
    const raw = String(draft).trim();
    if (raw === "" && (value == null || value === "")) return;
    const n = Number(raw);
    if (raw !== "" && (!Number.isFinite(n) || n < 0)) { setDraft(clean(value)); return; }
    if (clean(value) !== raw) onCommit(raw === "" ? "" : n);
  };
  return (
    <label className="block">
      <span className="text-[11px] font-medium text-[var(--ink-3)]">{label}</span>
      <span className="mt-1 flex items-center rounded-lg border border-[var(--line-strong)] bg-[var(--surface)] px-2.5 focus-within:border-accent-500">
        {prefix && <span className="text-sm text-[var(--ink-3)]">{prefix}</span>}
        <input type="number" min="0" value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          className="tnum w-full bg-transparent py-1.5 text-right text-sm text-[var(--ink)] outline-none" />
        {suffix && <span className="pl-1 text-sm text-[var(--ink-3)]">{suffix}</span>}
      </span>
    </label>
  );
}

function PurchaseOrders({ row, suggested, onResult }) {
  const key = row.Sku || row.ProductName;
  const openPOs = row.OpenPOs || [];
  const [qty, setQty] = useState(suggested > 0 ? String(suggested) : "");
  const [busy, setBusy] = useState(false);
  useEffect(() => setQty(suggested > 0 ? String(suggested) : ""), [suggested]);

  const run = async (fn) => {
    setBusy(true);
    try { const state = await fn(); onResult?.(key, state); } catch { /* keep as-is */ }
    setBusy(false);
  };

  return (
    <div>
      <SectionLabel className="mb-2.5">Purchase orders</SectionLabel>
      {openPOs.length > 0 ? (
        <div className="mb-3 flex flex-col gap-2">
          {openPOs.map((po) => (
            <div key={po.id} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5">
              <div className="min-w-0 text-sm">
                <span className="tnum font-semibold">{formatNumber(po.quantity)}</span> units
                <div className="text-[11px] text-[var(--ink-3)]">
                  placed {po.placed_on}{po.expected_on ? ` · expected ${po.expected_on}` : ""}
                </div>
              </div>
              <div className="flex shrink-0 gap-1.5">
                <button onClick={() => run(() => receivePurchaseOrder(po.id))} disabled={busy}
                  className="rounded-md bg-accent-500 px-2.5 py-1 text-xs font-semibold text-white transition-colors hover:bg-accent-600 disabled:opacity-45">Receive</button>
                <button onClick={() => run(() => cancelPurchaseOrder(po.id))} disabled={busy}
                  className="rounded-md border border-[var(--line-strong)] px-2.5 py-1 text-xs font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)] disabled:opacity-45">Cancel</button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mb-3 text-xs leading-relaxed text-[var(--ink-3)]">
          Nothing on the way. Placing an order tracks it as on-order; receiving it moves the units into on-hand and teaches Insighta this product’s real lead time.
        </p>
      )}
      <div className="flex items-center gap-2">
        <input type="number" min="0" value={qty} placeholder="qty" onChange={(e) => setQty(e.target.value)}
          className="tnum w-24 rounded-lg border border-[var(--line-strong)] bg-[var(--surface)] px-2.5 py-2 text-right text-sm text-[var(--ink)] outline-none focus:border-accent-500" />
        <button onClick={() => run(() => createPurchaseOrder(key, Number(qty)))} disabled={busy || !(Number(qty) > 0)}
          className="rounded-lg bg-accent-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-700 disabled:opacity-45">
          {busy ? "Working…" : "Create PO"}
        </button>
        {suggested > 0 && String(Number(qty)) !== String(suggested) && (
          <button onClick={() => setQty(String(suggested))} className="tnum text-[11px] text-[var(--ink-3)] underline-offset-2 hover:underline">
            use {formatNumber(suggested)}
          </button>
        )}
      </div>
    </div>
  );
}

function Cell({ label, value, sub, tone }) {
  return (
    <div className="bg-[var(--surface)] px-3.5 py-3">
      <SectionLabel>{label}</SectionLabel>
      <div className={`tnum mt-1 text-lg font-semibold ${tone === "neg" ? "text-neg-500 dark:text-neg-400" : ""}`}>{value}</div>
      {sub && <div className="text-[10px] text-[var(--ink-3)]">{sub}</div>}
    </div>
  );
}

function Legend({ color, label, dashed }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {dashed ? (
        <span className="inline-block h-0 w-3.5 border-t-2 border-dashed" style={{ borderColor: color }} />
      ) : (
        <span className="size-2.5 rounded-sm" style={{ background: color }} />
      )}
      {label}
    </span>
  );
}
