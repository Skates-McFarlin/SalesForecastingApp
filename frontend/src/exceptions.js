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

export function deriveExceptions(rows, settings, z) {
  const items = [];
  let missingStock = 0;
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  for (const row of rows || []) {
    const d = reorder(row, settings, z);
    const key = row.Sku || row.ProductName;
    if (!d.hasInventory) missingStock += 1;

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
      });
    } else if (pc != null && pc >= SURGE) {
      candidates.push({
        type: "surge", severity: "medium", tprio: 1,
        title: "Demand surging",
        detail: `forecast +${pc.toFixed(0)}% vs last year`,
        action: "Make sure supply can keep up",
        magnitude: num(row.Forecast),
      });
    }

    // Sitting on far more than the reorder cycle needs - cash tied up.
    if (d.hasInventory && d.coverDays != null && d.coverDays >= OVERSTOCK_DAYS && d.order === 0) {
      const cash = row.UnitCost ? d.position * num(row.UnitCost) : null;
      candidates.push({
        type: "overstock",
        severity: d.coverDays >= OVERSTOCK_DAYS * 2 ? "medium" : "low",
        tprio: 0,
        title: "Overstocked",
        detail: `${Math.round(d.coverDays)}d of cover${cash ? ` · ~$${fmt(cash)} tied up` : ""}`,
        action: "Pause ordering; consider a promotion",
        magnitude: cash || d.position,
      });
    }

    if (!candidates.length) continue;
    candidates.sort((a, b) => RANK[b.severity] - RANK[a.severity] || b.tprio - a.tprio);
    items.push({ key, name: row.ProductName, sku: row.Sku, category: row.Category, ...candidates[0] });
  }

  items.sort((a, b) => RANK[b.severity] - RANK[a.severity] || (b.magnitude || 0) - (a.magnitude || 0));

  const byType = {};
  for (const it of items) byType[it.type] = (byType[it.type] || 0) + 1;
  return { items, byType, missingStock, total: items.length };
}
