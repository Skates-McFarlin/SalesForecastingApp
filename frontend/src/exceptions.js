import { reorder } from "./components/ui";

// Phase 3 - the "what needs you" triage. Turns each SKU's forecast + inventory
// state into at most one actionable exception, ranked by urgency. Pure
// derivation from data already computed (reorder decision, YoY change, open POs),
// so it recomputes live as inventory/POs change.

const SURGE = 30; // % vs last year to call demand "surging"
const COLLAPSE = 30; // % drop to call it "falling"
const OVERSTOCK_DAYS = 120; // days of cover before flagging overstock
const RANK = { critical: 3, high: 2, medium: 1, low: 0 };

function num(n) {
  const v = Number(n);
  return Number.isNaN(v) ? 0 : v;
}
function fmt(n) {
  const v = Number(n);
  return Number.isNaN(v) ? "—" : Math.round(v).toLocaleString();
}
function pctChange(row) {
  const v = row["% Change from Previous Year"];
  return v === "N/A" || v == null ? null : Number(v);
}

// Per-unit economics: margin when both price and cost are known, plus the raw
// cost and price. Business-impact ranks on DOLLARS, not units - a stockout on a
// $2 item and a $200 item are not the same problem. Falls back gracefully:
// margin -> cost -> price (revenue at risk, when a file carries selling prices
// but no cost) -> nothing (those items rank by urgency at the bottom).
function perUnit(row) {
  const price = Number(row.Price), cost = Number(row.UnitCost);
  const hasP = row.Price != null && !Number.isNaN(price) && price > 0;
  const hasC = row.UnitCost != null && !Number.isNaN(cost) && cost > 0;
  const margin = hasP && hasC && price > cost ? price - cost : null;
  return { margin, cost: hasC ? cost : null, price: hasP ? price : null };
}
function money(n) {
  return n == null ? null : `$${Math.round(n).toLocaleString()}`;
}

// How much to trust a speculative demand-MOVE flag when ranking: the measured
// predictive LIFT (hit-rate minus base rate) of the trend/shift signals in that
// DIRECTION, scaled to 0..1. Directional matters - on real data a down-move
// (collapse) is modestly predictive while an up-move (surge) is anti-predictive
// (fires on spikes that revert), so surge is suppressed. Grounded exceptions
// (stockout/overdue/overstock) are current facts and keep full weight. Falls back
// to 1.0 (no gating) when the backtest hasn't run / lacks history.
const LIFT_FULL = 0.2; // lift at which a signal earns full weight (drift ~+0.20)
function demandMoveWeight(reliability, dir) {
  const w = reliability?.weights;
  if (!w || Object.keys(w).length === 0) return 1;   // not graded yet -> ungated
  const lift = Math.max(w[`trend_${dir}`] ?? 0, w[`shift_${dir}`] ?? 0);
  return Math.min(1, Math.max(0, lift / LIFT_FULL));
}

export function deriveExceptions(rows, settings, z, reliability = null) {
  const items = [];
  const surgeWeight = demandMoveWeight(reliability, "up");     // usually ~0 (anti-predictive)
  const collapseWeight = demandMoveWeight(reliability, "down");
  let missingStock = 0;
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  for (const row of rows || []) {
    const d = reorder(row, settings, z);
    const key = row.Sku || row.ProductName;
    if (!d.hasInventory) missingStock += 1;

    const pu = perUnit(row);
    const lostVal = pu.margin ?? pu.cost ?? pu.price; // $/unit of not supplying (margin > cost > revenue)
    const capVal = pu.cost ?? pu.price ?? pu.margin;  // $/unit of capital exposure
    const candidates = [];

    // A purchase order whose expected arrival has passed.
    const overdue = (row.OpenPOs || []).filter(
      (po) => po.expected_on && new Date(po.expected_on) < today
    );
    if (overdue.length) {
      const qty = overdue.reduce((s, po) => s + num(po.quantity), 0);
      candidates.push({
        type: "overdue", severity: "high", tprio: 5,
        title: "Delivery overdue",
        detail: `${fmt(qty)} units expected ${overdue[0].expected_on}, not yet received`,
        action: "Follow up with your supplier",
        magnitude: qty,
        impactUsd: capVal != null ? qty * capVal : null,   // capital in limbo
      });
    }

    // Stock at/below the reorder point - critical if it won't last the lead time.
    if (d.hasInventory && d.reorderNow) {
      const willStockOut = d.coverDays != null && d.coverDays < d.leadTimeDays;
      candidates.push({
        type: "stockout",
        severity: willStockOut ? "critical" : "high",
        tprio: willStockOut ? 6 : 4,
        title: willStockOut ? "Will run out before resupply" : "Below reorder point",
        detail: willStockOut
          ? `${Math.round(d.coverDays)}d of cover vs ${d.leadTimeDays}d to resupply`
          : `${d.coverDays != null ? Math.round(d.coverDays) + "d cover · " : ""}position ${fmt(d.position)} ≤ reorder point ${fmt(d.reorderPoint)}`,
        action: `Order ${fmt(d.order)}`,
        order: d.order,
        magnitude: d.order,
        // Margin you protect by ordering (or the capital it takes, if no price).
        impactUsd: lostVal != null ? d.order * lostVal : null,
      });
    }

    // Demand shifting sharply vs the same period last year.
    const pc = pctChange(row);
    if (pc != null && pc <= -COLLAPSE) {
      candidates.push({
        type: "collapse", severity: "medium", tprio: 2,
        title: "Demand falling",
        detail: `forecast ${pc.toFixed(0)}% vs last year`,
        action: "Ease off ordering; consider clearing stock",
        magnitude: num(row.Forecast),
        // Revenue/cost exposure of the declining line over the horizon.
        impactUsd: lostVal != null ? num(row.Forecast) * lostVal : null,
      });
    } else if (pc != null && pc >= SURGE) {
      candidates.push({
        type: "surge", severity: "medium", tprio: 1,
        title: "Demand surging",
        detail: `forecast +${pc.toFixed(0)}% vs last year`,
        action: "Make sure supply can keep up",
        magnitude: num(row.Forecast),
        // Upside at risk if you can't supply the extra demand.
        impactUsd: lostVal != null
          ? num(row.Forecast) * Math.min(pc / 100, 1) * lostVal : null,
      });
    }

    // Sitting on far more than the reorder cycle needs - cash tied up.
    if (d.hasInventory && d.coverDays != null && d.coverDays >= OVERSTOCK_DAYS && d.order === 0) {
      const cash = capVal != null ? d.position * capVal : null;
      candidates.push({
        type: "overstock",
        severity: d.coverDays >= OVERSTOCK_DAYS * 2 ? "medium" : "low",
        tprio: 0,
        title: "Overstocked",
        detail: `${Math.round(d.coverDays)}d of cover${cash ? ` · ~$${fmt(cash)} tied up` : ""}`,
        action: "Pause ordering; consider a promotion",
        magnitude: cash || d.position,
        impactUsd: cash,   // capital tied up in excess stock
      });
    }

    if (!candidates.length) continue;
    candidates.sort((a, b) => RANK[b.severity] - RANK[a.severity] || b.tprio - a.tprio);
    const chosen = candidates[0];
    // Surface the dollar figure inline when we can price it.
    if (chosen.impactUsd != null && chosen.type !== "overstock") {
      chosen.detail += ` · ~${money(chosen.impactUsd)} at risk`;
    }
    // Ranking value = dollars at risk, but a speculative demand-move flag
    // (surge/collapse) is discounted by how often such signals actually pan out,
    // so a reliable stockout outranks a big-but-flaky "+40% surge". Display still
    // shows the true dollars; only the RANK is reliability-weighted.
    const w = chosen.type === "surge" ? surgeWeight
      : chosen.type === "collapse" ? collapseWeight : 1;
    chosen.rankUsd = chosen.impactUsd != null ? chosen.impactUsd * w : null;
    items.push({ key, name: row.ProductName, sku: row.Sku, category: row.Category, ...chosen });
  }

  // Rank by reliability-weighted DOLLARS at risk (business impact, gated by how
  // often a signal type pans out), urgency as the tiebreaker so a critical run-out
  // still floats within a band. Unpriced items fall to the bottom, ranked as before.
  items.sort((a, b) =>
    (b.rankUsd != null) - (a.rankUsd != null) ||
    (b.rankUsd || 0) - (a.rankUsd || 0) ||
    RANK[b.severity] - RANK[a.severity] ||
    (b.magnitude || 0) - (a.magnitude || 0));

  const byType = {};
  let totalImpact = 0, priced = 0;
  for (const it of items) {
    byType[it.type] = (byType[it.type] || 0) + 1;
    if (it.impactUsd != null) { totalImpact += it.impactUsd; priced += 1; }
  }
  return { items, byType, missingStock, total: items.length,
           totalImpact: priced ? Math.round(totalImpact) : null, priced };
}
