import { reorder, snapOrder } from "./components/ui";

// Phase 4 - budget-constrained buy across the whole catalog. The forecast is now
// an INPUT: given a cash budget, allocate it to maximize expected service, using
// each SKU's demand distribution over its protection interval.
//
// The marginal value of one more unit of a SKU is P(demand > current stock) =
// 1 - F(stock), which is decreasing - so the problem is a separable concave
// knapsack: fund every unit whose value-per-dollar (1-F(y))/cost >= lambda, and
// binary-search lambda to hit the budget (Lagrangian water-filling). Validated to
// match unit-by-unit greedy and beat proportional allocation.
//
// FBA extension: an Amazon seller is capped not only by cash but by a restock /
// capacity limit - how much inbound VOLUME (cubic feet) Amazon's Capacity Manager
// will accept, set by the IPI score. That's a second knapsack constraint on the
// SAME allocation. With two constraints a unit is worth funding when its value
// clears a combined price lamCash*cost + lamVol*size; we nest the water-filling
// (bisect the volume price, and for each solve the cash price to the budget) so
// both caps are met at once. With capacity = Infinity this collapses exactly to
// the single-constraint cash plan above.

// --- standard normal helpers (no deps) ------------------------------------
function erf(x) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}
function normCdf(x) {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}
function normPdf(x) {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
}
// Inverse standard normal CDF (Acklam's rational approximation).
function normInv(p) {
  p = Math.min(1 - 1e-9, Math.max(1e-9, p));
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
  const pl = 0.02425;
  if (p < pl) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p <= 1 - pl) {
    const q = p - 0.5, r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  const q = Math.sqrt(-2 * Math.log(1 - p));
  return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
}
// E[max(0, D - y)] for D ~ Normal(mu, sigma) - the standard normal loss.
function expShortage(y, mu, sigma) {
  const k = (y - mu) / sigma;
  return sigma * (normPdf(k) - k * (1 - normCdf(k)));
}

// Largest ORDERABLE quantity <= raw: a case-pack multiple that still meets the
// minimum order, else 0 (can't reach the minimum without exceeding what the
// budget allocated). Snapping down guarantees we never blow past the cap.
function snapDownOrder(raw, moq, cp) {
  if (raw <= 0) return 0;
  const step = cp > 0 ? cp : 1;
  const q = Math.floor(raw / step + 1e-9) * step;
  if (moq && q < moq) return 0;
  return q;
}

// The next feasible order increment for an item currently ordering `a` units:
// the first unit jumps to the minimum order, then it climbs by whole case packs,
// never past the item's full snapped need. Ranked by expected shortage reduced
// per dollar, so leftover budget/capacity buys the most service.
function nextIncrement(it, a) {
  const step = it.cp > 0 ? it.cp : 1;
  const to = a <= 0 ? it.minOrder : a + step;
  if (to > it.full || to <= a) return null;
  const add = to - a;
  const y = it.q0 + a;
  const gain = expShortage(y, it.mu, it.sigma) - expShortage(y + add, it.mu, it.sigma);
  return { to, dCost: add * it.cost, dVol: add * it.size, density: gain / Math.max(1e-9, add * it.cost) };
}

// Amazon exports never carry COGS (Amazon doesn't know what you paid). When a
// SKU has a selling price but no cost, estimate cost as this fraction of price so
// the buy plan isn't empty right after a pure-Amazon import - clearly flagged in
// the UI, and superseded the instant real costs are imported or typed.
const COST_FROM_PRICE = 0.5;

// Order-up-to for a SKU at combined shadow prices: fund a unit while its
// marginal value 1-F(y) still clears lamCash*cost + lamVol*size.
function targetY(it, lamCash, lamVol = 0) {
  const val = 1 - lamCash * it.cost - lamVol * it.size;
  if (val <= 0) return it.q0; // no unit is worth funding at this price
  return Math.min(it.S, Math.max(it.q0, it.mu + it.sigma * normInv(val)));
}

function median(xs) {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// The size (inbound cubic feet per unit) each SKU consumes against a restock cap,
// and whether the catalog even carries volumes. When most SKUs have a real item
// volume we cap in cubic feet (Amazon's Capacity Manager unit), filling a missing
// volume with the catalog median so it still consumes capacity; otherwise the cap
// degrades to a plain unit count (size = 1).
export function capacityBasis(items) {
  const vols = items.map((it) => it.vol).filter((v) => v > 0);
  if (vols.length >= Math.max(1, items.length * 0.5)) {
    const med = median(vols) || 1;
    for (const it of items) it.size = it.vol > 0 ? it.vol : med;
    return { unit: "cu ft", haveVolume: vols.length };
  }
  for (const it of items) it.size = 1;
  return { unit: "units", haveVolume: vols.length };
}

export function optimizeBudget(rows, settings, z, budget, capacity = Infinity) {
  const R = settings?.review_period_days ?? 7;
  const items = [];
  let noCost = 0;

  for (const row of rows || []) {
    const d = reorder(row, settings, z);
    let cost = Number(row.UnitCost);
    let costEstimated = false;
    const r = Number(row.DailyRate || 0);
    const s = Number(row.DailySigma || 0);
    if (r <= 0) continue;
    if (!(cost > 0)) {
      // No COGS (an Amazon import). Fall back to an estimate from the selling
      // price so this SKU still gets planned; skip only if we have no price either.
      const price = Number(row.Price);
      if (price > 0) {
        cost = price * COST_FROM_PRICE;
        costEstimated = true;
      } else {
        if (d.order > 0) noCost += 1; // wants an order but we can't price it at all
        continue;
      }
    }
    const P = d.leadTimeDays + R;
    const mu = r * P;
    const sigma = Math.max(1e-6, s * Math.sqrt(P));
    const q0 = d.position;
    // Target = the SAME order-up-to the Forecast tab shows (count-aware for
    // intermittent demand), so "Needed" here matches "Suggested order" there.
    // mu/sigma below still drive the normal marginal-value ranking that spreads
    // a tight budget across SKUs (a documented approximation of the allocation).
    const S = Math.max(q0, d.orderUpTo);
    const ideal = Math.max(0, S - q0);
    if (ideal <= 0) continue; // already covered - no order needed
    const vol = Math.max(0, Number(row.ItemVolumeCuft) || 0);
    const moq = Math.max(0, Number(row.MOQ) || 0);
    const cp = Math.max(0, Number(row.CasePack) || 0);
    // full = the full need made ORDERABLE (a case-pack multiple that meets MOQ) -
    // the same snap the Forecast tab applies, so "Needed" here matches its
    // "Suggested order". minOrder = the smallest legal order (first funded unit).
    const full = Math.round(snapOrder(ideal, moq, cp));
    const minOrder = Math.round(snapOrder(1, moq, cp));
    items.push({ key: row.Sku || row.ProductName, name: row.ProductName, sku: row.Sku, cost, costEstimated, mu, sigma, q0, S, ideal, vol, moq, cp, full, minOrder });
  }

  const cap = capacityBasis(items); // assigns it.size (cu ft or units per unit)
  // Reference "full need" cost/volume uses the ORDERABLE (snapped) quantity, so
  // it lines up with what the plan can actually buy.
  const idealCost = items.reduce((a, it) => a + it.cost * it.full, 0);
  const idealVol = items.reduce((a, it) => a + it.size * it.full, 0);
  const capped = Number.isFinite(capacity);
  const covers = items.length === 0 || (budget >= idealCost && (!capped || capacity >= idealVol));

  let ys;
  if (covers) {
    ys = items.map((it) => it.S); // both caps cover everything
  } else {
    const spendAt = (lc, lv) => items.reduce((a, it) => a + it.cost * (targetY(it, lc, lv) - it.q0), 0);
    const volAt = (lc, lv) => items.reduce((a, it) => a + it.size * (targetY(it, lc, lv) - it.q0), 0);
    const cashHi = 1 / Math.min(...items.map((i) => i.cost)); // funds nothing
    const volHi = 1 / Math.min(...items.map((i) => i.size));

    // Cash price that spends exactly the budget at a given volume price (spend is
    // monotone decreasing in lamCash); 0 when the budget doesn't bind there.
    const solveCash = (lv) => {
      if (spendAt(0, lv) <= budget) return 0;
      let lo = 0, hi = cashHi;
      for (let k = 0; k < 64; k++) {
        const mid = (lo + hi) / 2;
        if (spendAt(mid, lv) > budget) lo = mid;
        else hi = mid;
      }
      return hi;
    };

    let lamVol = 0;
    if (capped && volAt(solveCash(0), 0) > capacity) {
      // Capacity binds even after the budget is spent: raise the volume price
      // (which shrinks every order, hence total volume) to meet the cap, keeping
      // the budget solved at each step.
      let lo = 0, hi = volHi;
      for (let k = 0; k < 64; k++) {
        const mid = (lo + hi) / 2;
        if (volAt(solveCash(mid), mid) > capacity) lo = mid;
        else hi = mid;
      }
      lamVol = hi;
    }
    const lamCash = solveCash(lamVol);
    ys = items.map((it) => targetY(it, lamCash, lamVol));
  }

  // Turn the continuous water-fill target into an ORDERABLE plan: every line is a
  // case-pack multiple that meets the SKU's minimum order, or zero. When both caps
  // cover the catalog, order each SKU's full snapped need. When a cap binds, snap
  // each order DOWN to a feasible quantity (so total spend/volume never exceeds the
  // cap the user set) then spend the rounding remainder greedily on the highest
  // service-per-dollar increments that still fit both caps.
  const alloc = items.map((it, i) => (covers ? it.full : snapDownOrder(Math.max(0, ys[i] - it.q0), it.moq, it.cp)));
  if (!covers) {
    let remBudget = budget - alloc.reduce((s, a, i) => s + a * items[i].cost, 0);
    let remCap = capacity - alloc.reduce((s, a, i) => s + a * items[i].size, 0);
    let guard = items.length * 30 + 500; // safety bound; the loop exits when nothing fits
    while (guard-- > 0) {
      let bi = -1, best = null;
      for (let i = 0; i < items.length; i++) {
        const inc = nextIncrement(items[i], alloc[i]);
        if (!inc || inc.dCost > remBudget + 1e-6 || inc.dVol > remCap + 1e-6) continue;
        if (!best || inc.density > best.density) { bi = i; best = inc; }
      }
      if (bi < 0) break;
      alloc[bi] = best.to;
      remBudget -= best.dCost;
      remCap -= best.dVol;
    }
  }

  let allocatedSpend = 0, allocatedVol = 0, shortAfter = 0, shortFull = 0, shortNone = 0, muTot = 0;
  let funded = 0, partial = 0, unfunded = 0, estimatedCount = 0;
  const out = items.map((it, i) => {
    const allocated = alloc[i];
    const spend = allocated * it.cost;
    allocatedSpend += spend;
    allocatedVol += allocated * it.size;
    muTot += it.mu;
    if (it.costEstimated) estimatedCount += 1;
    shortAfter += expShortage(it.q0 + allocated, it.mu, it.sigma);
    shortFull += expShortage(it.S, it.mu, it.sigma);
    shortNone += expShortage(it.q0, it.mu, it.sigma);
    const status = allocated <= 0 ? "unfunded" : allocated >= it.full ? "funded" : "partial";
    if (status === "funded") funded += 1;
    else if (status === "partial") partial += 1;
    else unfunded += 1;
    return { key: it.key, name: it.name, sku: it.sku, cost: it.cost, costEstimated: it.costEstimated, ideal: it.full, allocated, spend, status };
  });

  out.sort((a, b) => b.spend - a.spend || b.ideal - a.ideal);
  const fill = (short) => (muTot > 0 ? 1 - short / muTot : 1);

  return {
    items: out,
    budget,
    idealCost,
    allocatedSpend,
    coverage: idealCost > 0 ? allocatedSpend / idealCost : 1,
    expectedService: fill(shortAfter),
    serviceIfFull: fill(shortFull),
    serviceIfNone: fill(shortNone),
    counts: { funded, partial, unfunded },
    noCost,
    estimatedCount, // SKUs whose cost was estimated from price (no COGS imported)
    costRatio: COST_FROM_PRICE,
    binding: budget < idealCost,
    // FBA restock/capacity constraint (Amazon Capacity Manager).
    capacity,
    capUnit: cap.unit, // "cu ft" | "units"
    idealVol,
    allocatedVol,
    capBinding: capped && capacity < idealVol,
    haveVolume: cap.haveVolume,
  };
}
