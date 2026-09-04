// Start-date math for the picker. A "date" here is { y, m } with m in 1..12.

const THIS_YEAR = new Date().getFullYear();

export function cmp(a, b) {
  return a.y * 12 + a.m - (b.y * 12 + b.m);
}

export function addMonths({ y, m }, n) {
  const idx = y * 12 + (m - 1) + n;
  return { y: Math.floor(idx / 12), m: (idx % 12) + 1 };
}

// Turn the stored catalog's summary (date_from / date_to as YYYY-MM-DD) into
// the {min_year, min_month, max_year, max_month} shape the pickers expect, or
// null when the catalog is empty / has no dated history yet.
export function catalogRange(catalog) {
  if (!catalog || catalog.empty || !catalog.date_from || !catalog.date_to) return null;
  const [minY, minM] = catalog.date_from.split("-").map(Number);
  const [maxY, maxM] = catalog.date_to.split("-").map(Number);
  return { min_year: minY, min_month: minM, max_year: maxY, max_month: maxM };
}

// Given a file's detected coverage (or null before one is inspected) and the
// active tab, return the selectable start-date window and a sensible default.
//   - Accuracy backtests against real history, so the start must sit INSIDE the
//     data; we default to scoring the last 12 months.
//   - Forecasts run forward, so the window reaches ~5 years past the data's end
//     and defaults to the first month with no history yet.
export function dateBounds(range, tab) {
  if (!range) {
    return {
      min: { y: THIS_YEAR, m: 1 },
      max: { y: THIS_YEAR + 9, m: 12 },
      def: { y: THIS_YEAR, m: 1 },
    };
  }
  const dataStart = { y: range.min_year, m: range.min_month };
  const dataEnd = { y: range.max_year, m: range.max_month };

  if (tab === "accuracy") {
    let def = addMonths(dataEnd, -11);
    if (cmp(def, dataStart) < 0) def = dataStart;
    return { min: dataStart, max: dataEnd, def };
  }
  return { min: dataStart, max: addMonths(dataEnd, 60), def: addMonths(dataEnd, 1) };
}

// The months selectable for a given year within a window (both dropdowns share
// one window, so only the edge years are partially disabled).
export function monthRangeForYear(bounds, year) {
  const lo = year === bounds.min.y ? bounds.min.m : 1;
  const hi = year === bounds.max.y ? bounds.max.m : 12;
  return { lo, hi };
}
