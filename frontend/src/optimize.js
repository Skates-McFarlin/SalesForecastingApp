import { reorder } from "./components/ui";

// Phase 4 - budget-constrained buy across the whole catalog. The forecast is now
// an INPUT: given a cash budget, allocate it to maximize expected service, using
// each SKU's demand distribution over its protection interval.
//
// The marginal value of one more unit of a SKU is P(demand > current stock) =
// 1 - F(stock), which is decreasing - so the problem is a separable concave
// knapsack: fund every unit whose value-per-dollar (1-F(y))/cost >= lambda, and
// binary-search lambda to hit the budget (Lagrangian water-filling). Validated to
// match unit-by-unit greedy and beat proportional allocation.

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

function targetY(it, lam) {
  const val = 1 - lam * it.cost;
  if (val <= 0) return it.q0; // no unit is worth funding at this price
  return Math.min(it.S, Math.max(it.q0, it.mu + it.sigma * normInv(val)));
}

export function optimizeBudget(rows, settings, z, budget) {
  const R = settings?.review_period_days ?? 7;
  const items = [];
  let noCost = 0;

  for (const row of rows || []) {
    const d = reorder(row, settings, z);
    const cost = Number(row.UnitCost);
    const r = Number(row.DailyRate || 0);
    const s = Number(row.DailySigma || 0);
    if (r <= 0) continue;
    if (!(cost > 0)) {
      if (d.order > 0) noCost += 1; // wants an order but we can't price it
      continue;
    }
    const P = d.leadTimeDays + R;
    const mu = r * P;
    const sigma = Math.max(1e-6, s * Math.sqrt(P));
    const q0 = d.position;
    const S = mu + z * sigma;
    const ideal = Math.max(0, S - q0);
    if (ideal <= 0) continue; // already covered - no order needed
    items.push({ key: row.Sku || row.ProductName, name: row.ProductName, sku: row.Sku, cost, mu, sigma, q0, S, ideal });
  }

  const idealCost = items.reduce((a, it) => a + it.cost * it.ideal, 0);

  let ys;
  if (budget >= idealCost || items.length === 0) {
    ys = items.map((it) => it.S); // budget covers everything
  } else {
    const minCost = Math.min(...items.map((i) => i.cost));
    let lo = 0, hi = 1 / minCost; // hi funds nothing beyond position
    for (let k = 0; k < 80; k++) {
      const mid = (lo + hi) / 2;
      const spend = items.reduce((a, it) => a + it.cost * (targetY(it, mid) - it.q0), 0);
      if (spend > budget) lo = mid;
      else hi = mid;
    }
    ys = items.map((it) => targetY(it, hi));
  }

  let allocatedSpend = 0, shortAfter = 0, shortFull = 0, shortNone = 0, muTot = 0;
  let funded = 0, partial = 0, unfunded = 0;
  const out = items.map((it, i) => {
    const allocated = Math.max(0, Math.round(ys[i] - it.q0));
    const spend = allocated * it.cost;
    allocatedSpend += spend;
    muTot += it.mu;
    shortAfter += expShortage(it.q0 + allocated, it.mu, it.sigma);
    shortFull += expShortage(it.S, it.mu, it.sigma);
    shortNone += expShortage(it.q0, it.mu, it.sigma);
    const idealRound = Math.round(it.ideal);
    const status = allocated <= 0 ? "unfunded" : allocated >= idealRound ? "funded" : "partial";
    if (status === "funded") funded += 1;
    else if (status === "partial") partial += 1;
    else unfunded += 1;
    return { key: it.key, name: it.name, sku: it.sku, cost: it.cost, ideal: idealRound, allocated, spend, status };
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
    binding: budget < idealCost,
  };
}
