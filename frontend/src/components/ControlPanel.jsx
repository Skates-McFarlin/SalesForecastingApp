import FileDrop from "./FileDrop";
import { addMonths, cmp, monthRangeForYear } from "../dates";
import { Button, Field, Select, SectionLabel, Spinner } from "./ui";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const DURATIONS = { monthly: [3, 6, 12, 18, 24], weekly: [4, 8, 13, 26, 52] };

export default function ControlPanel({
  catalog,
  importing,
  onImport,
  onReject,
  year,
  month,
  duration,
  grain,
  bounds,
  onYear,
  onMonth,
  onDuration,
  mode = "forecast", // "forecast" | "accuracy" | "ledger"
  origin, // YYYY-MM-DD: where a forecast starts (the catalog's data edge)
  fcWindow, // null | { from: {y,m}, through: {y,m} }: optional reported window
  onWindow,
  forecastDuration,
  onSubmit,
  onCancel,
  busy,
  elapsed,
  submitLabel,
  busyLabel,
}) {
  const hasCatalog = catalog && !catalog.empty;
  const unitWord = grain === "weekly" ? "weeks" : "months";

  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-5">
      <div>
        <SectionLabel className="mb-1.5">{hasCatalog ? "Your catalog" : "Sales data"}</SectionLabel>
        {hasCatalog && (
          <div className="mb-2 rounded-lg border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5">
            <div className="flex items-baseline justify-between">
              <span className="tnum text-sm font-semibold">
                {catalog.products.toLocaleString()} products
              </span>
              <span className="text-xs text-[var(--ink-3)]">
                {(catalog.categories?.length || 0)} categories
              </span>
            </div>
            <div className="mt-0.5 text-xs text-[var(--ink-3)]">
              {formatSpan(catalog.date_from, catalog.date_to)}
            </div>
          </div>
        )}
        {importing ? (
          <div className="flex items-center gap-2 rounded-lg border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2.5 text-sm">
            <Spinner className="size-3.5 text-accent-500" /> Importing…
          </div>
        ) : (
          <FileDrop file={null} onSelect={onImport} onReject={onReject} />
        )}
        {hasCatalog && !importing && (
          <p className="mt-1.5 text-xs leading-relaxed text-[var(--ink-3)]">
            Drop a file to sync new sales — it merges into your catalog.
          </p>
        )}
      </div>

      {/* Accuracy backtests a chosen in-history window, so it keeps a start date. */}
      {mode === "accuracy" && (
        <AccuracyControls
          bounds={bounds}
          year={year}
          month={month}
          duration={duration}
          grain={grain}
          onYear={onYear}
          onMonth={onMonth}
          onDuration={onDuration}
          busy={busy}
        />
      )}

      {/* Forecast always runs forward from the catalog's data edge; the only
          choice is how far out, via a length or an optional "through" month. */}
      {mode === "forecast" && (
        <ForecastControls
          origin={origin}
          grain={grain}
          duration={duration}
          onDuration={onDuration}
          fcWindow={fcWindow}
          onWindow={onWindow}
          forecastDuration={forecastDuration}
          unitWord={unitWord}
          busy={busy}
        />
      )}

      {mode !== "ledger" && (
        <div className="mt-auto space-y-3 pt-2">
          {busy ? (
            <>
              <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-2)] p-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Spinner className="size-3.5 text-accent-500" />
                  {busyLabel}
                </div>
                <div className="tnum mt-1 text-xs text-[var(--ink-3)]">
                  {formatElapsed(elapsed)} elapsed
                </div>
                <p className="mt-2 text-xs leading-relaxed text-[var(--ink-3)]">
                  Large catalogues take a few minutes — roughly half a second per product.
                </p>
              </div>
              <Button variant="secondary" className="w-full" onClick={onCancel}>
                Cancel
              </Button>
            </>
          ) : (
            <Button className="w-full" onClick={onSubmit} disabled={!hasCatalog || importing}>
              {submitLabel}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function AccuracyControls({ bounds, year, month, duration, grain, onYear, onMonth, onDuration, busy }) {
  const years = [];
  for (let y = bounds.min.y; y <= bounds.max.y; y++) years.push(y);
  const { lo, hi } = monthRangeForYear(bounds, year);
  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Start month">
          <Select value={month} onChange={(e) => onMonth(Number(e.target.value))} disabled={busy}>
            {MONTHS.map((name, i) => (
              <option key={name} value={i + 1} disabled={i + 1 < lo || i + 1 > hi}>
                {name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Year">
          <Select value={year} onChange={(e) => onYear(Number(e.target.value))} disabled={busy}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <Field label="Window length">
        <Select value={duration} onChange={(e) => onDuration(Number(e.target.value))} disabled={busy}>
          {(DURATIONS[grain] || DURATIONS.monthly).map((d) => (
            <option key={d} value={d}>
              {d} {grain === "weekly" ? "weeks" : "months"}
            </option>
          ))}
        </Select>
      </Field>
    </>
  );
}

function ForecastControls({ origin, grain, duration, onDuration, fcWindow, onWindow, forecastDuration, unitWord, busy }) {
  const oParts = origin ? origin.split("-").map(Number) : null; // [y, m, d]
  const edge = oParts ? { y: oParts[0], m: oParts[1] } : null;

  // Default "through" = the edge plus the current length dropdown's horizon.
  const defaultThrough = () => {
    const [oy, om, od] = oParts;
    if (grain === "weekly") {
      const d = new Date(oy, om - 1, od || 1);
      d.setDate(d.getDate() + Math.max(1, duration) * 7);
      return { y: d.getFullYear(), m: d.getMonth() + 1 };
    }
    return addMonths({ y: oy, m: om }, Math.max(0, duration - 1));
  };

  const enableWindow = () => {
    if (!edge) return;
    onWindow({ from: { ...edge }, through: defaultThrough() });
  };

  const years = [];
  if (oParts) for (let y = oParts[0]; y <= oParts[0] + 5; y++) years.push(y);

  // "from" can't precede the data edge; "through" can't precede "from".
  const setFrom = (from) => {
    const f = cmp(from, edge) < 0 ? { ...edge } : from;
    const through = cmp(fcWindow.through, f) < 0 ? { ...f } : fcWindow.through;
    onWindow({ from: f, through });
  };
  const setThrough = (through) => {
    const t = cmp(through, fcWindow.from) < 0 ? { ...fcWindow.from } : through;
    onWindow({ from: fcWindow.from, through: t });
  };

  return (
    <div className="space-y-3">
      {origin && (
        <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2">
          <SectionLabel>Forecasting from</SectionLabel>
          <div className="tnum mt-0.5 text-sm font-medium">{formatOrigin(origin, grain)}</div>
          <div className="mt-0.5 text-[11px] leading-relaxed text-[var(--ink-3)]">
            the {grain === "weekly" ? "week" : "month"} after your latest sales — forecasts run forward from here.
          </div>
        </div>
      )}

      <Field label="Forecast length">
        <Select
          value={duration}
          onChange={(e) => onDuration(Number(e.target.value))}
          disabled={busy || !!fcWindow}
        >
          {(DURATIONS[grain] || DURATIONS.monthly).map((d) => (
            <option key={d} value={d}>
              {d} {unitWord}
            </option>
          ))}
        </Select>
      </Field>

      <div className="rounded-lg border border-[var(--line)] px-3 py-2.5">
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={!!fcWindow}
            onChange={(e) => (e.target.checked ? enableWindow() : onWindow(null))}
            disabled={busy || !oParts}
            className="size-3.5 accent-[var(--accent-500,#4f46e5)]"
          />
          <span className="text-[var(--ink-2)]">…or forecast a specific window</span>
        </label>
        {fcWindow && (
          <div className="mt-2.5 space-y-2">
            <WindowRow
              label="From"
              value={fcWindow.from}
              years={years}
              monthDisabled={(m1) => cmp({ y: fcWindow.from.y, m: m1 }, edge) < 0}
              onChange={setFrom}
              busy={busy}
            />
            <WindowRow
              label="Through"
              value={fcWindow.through}
              years={years}
              monthDisabled={(m1) => cmp({ y: fcWindow.through.y, m: m1 }, fcWindow.from) < 0}
              onChange={setThrough}
              busy={busy}
            />
            <div className="tnum text-[11px] text-[var(--ink-3)]">
              = {forecastDuration} {unitWord} forecast from your data’s edge; reports only this window.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function WindowRow({ label, value, years, monthDisabled, onChange, busy }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 shrink-0 text-[11px] font-medium text-[var(--ink-3)]">{label}</span>
      <Select
        className="py-1.5"
        value={value.m}
        onChange={(e) => onChange({ ...value, m: Number(e.target.value) })}
        disabled={busy}
      >
        {MONTHS.map((name, i) => (
          <option key={name} value={i + 1} disabled={monthDisabled(i + 1)}>
            {name}
          </option>
        ))}
      </Select>
      <Select
        className="w-24 py-1.5"
        value={value.y}
        onChange={(e) => onChange({ ...value, y: Number(e.target.value) })}
        disabled={busy}
      >
        {years.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </Select>
    </div>
  );
}

function formatElapsed(ms) {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

function formatOrigin(iso, grain) {
  const [y, m, d] = iso.split("-").map(Number);
  if (grain === "weekly") return `week of ${MON[m - 1]} ${d}, ${y}`;
  return `${MON[m - 1]} ${y}`;
}

function formatSpan(from, to) {
  if (!from || !to) return "No sales history yet";
  const label = (d) => {
    const [y, m] = d.split("-").map(Number);
    return `${MON[m - 1]} ${y}`;
  };
  return `${label(from)} – ${label(to)}`;
}
