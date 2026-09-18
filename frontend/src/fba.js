// Amazon FBA fee economics - the carrying cost that generic overstock ("cash
// tied up") misses. Two bleeds hurt an FBA seller: the monthly STORAGE fee on
// every cubic foot sitting in the warehouse, and the AGED-inventory surcharge
// once a unit passes 181 days. We use the seller's own imported numbers when we
// have them (Amazon's Storage Fees / Inventory Age reports), and fall back to a
// documented estimate from item volume + Amazon's published schedule otherwise.
//
// The schedule is standard-size, US, and approximate - Amazon revises it and
// oversize differs - so anything modeled is labeled "est." and these constants
// are meant to be easy to update.

const STORAGE_OFFPEAK = 0.87; // $/cu ft / mo, standard-size, Jan-Sep
const STORAGE_PEAK = 2.4; // $/cu ft / mo, standard-size, Oct-Dec (peak)
const AGED_RATE = 1.5; // $/cu ft / mo, representative 181+ day aged-inventory surcharge
const AGED_DAY = 181; // day a unit enters the aged-surcharge band

function num(n) {
  const v = Number(n);
  return Number.isNaN(v) ? null : v;
}

// Standard-size monthly storage rate for the month a date falls in (peak in Q4).
function storageRate(date = new Date()) {
  const m = date.getMonth(); // 0-11
  return m >= 9 ? STORAGE_PEAK : STORAGE_OFFPEAK;
}

// Monthly storage cost for what's on hand. Real Amazon figure if the seller
// imported the Storage Fees report; else modeled from per-unit volume x on-hand
// x the month's rate. Returns null when we have neither.
export function storageMonthly(row, date = new Date()) {
  const real = num(row.StorageFeeMonthly);
  if (real != null && real >= 0) return { usd: real, modeled: false };
  const vol = num(row.ItemVolumeCuft);
  const onHand = num(row.OnHand);
  if (vol != null && vol > 0 && onHand != null && onHand > 0) {
    return { usd: vol * onHand * storageRate(date), modeled: true };
  }
  return null;
}

// Units at aged-surcharge risk. Prefer Amazon's own count (Inventory Age
// report's 181+ bands); otherwise project forward - at the current sell-through
// rate, the units that still won't have sold by day 181 are the ones that will
// age. dailyRate is units/day; coverDays is current days of cover.
export function agedUnits(row, dailyRate, coverDays) {
  const real = num(row.UnitsAged);
  if (real != null && real > 0) return { units: real, modeled: false };
  const onHand = num(row.OnHand);
  const r = num(dailyRate);
  if (onHand != null && r != null && r > 0 && coverDays != null && coverDays > AGED_DAY) {
    const willSellBy181 = r * AGED_DAY;
    const aging = Math.max(0, onHand - willSellBy181);
    if (aging >= 1) return { units: Math.round(aging), modeled: true };
  }
  return null;
}

// Estimated monthly aged-inventory surcharge on the aging units. Needs per-unit
// volume; without it we can flag the unit count but not the dollars.
export function agedSurchargeMonthly(row, agedUnitCount) {
  const vol = num(row.ItemVolumeCuft);
  if (vol != null && vol > 0 && agedUnitCount > 0) return vol * AGED_RATE * agedUnitCount;
  return null;
}

// The full FBA carrying picture for a SKU: monthly storage bleed, units aging,
// and the estimated monthly aged surcharge - plus a single monthly $ that folds
// the two fee streams together for ranking. Any of these can be null.
export function fbaCarrying(row, dailyRate, coverDays, date = new Date()) {
  const storage = storageMonthly(row, date);
  const aged = agedUnits(row, dailyRate, coverDays);
  const surcharge = aged ? agedSurchargeMonthly(row, aged.units) : null;
  const monthlyFee =
    storage || surcharge ? (storage?.usd || 0) + (surcharge || 0) : null;
  return {
    storage, // { usd, modeled } | null
    aged, // { units, modeled } | null
    surcharge, // number | null  (est monthly aged surcharge)
    monthlyFee, // number | null  (storage + aged surcharge, for ranking)
    modeled: Boolean(storage?.modeled || aged?.modeled),
  };
}
