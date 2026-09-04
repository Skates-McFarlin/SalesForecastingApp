import FileDrop from "./FileDrop";
import { monthRangeForYear } from "../dates";
import { Button, Field, Select, SectionLabel, Spinner } from "./ui";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

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
  onSubmit,
  onCancel,
  busy,
  elapsed,
  submitLabel,
  busyLabel,
}) {
  const hasCatalog = catalog && !catalog.empty;
  // The selectable start-date window comes from the stored catalog's coverage.
  const years = [];
  for (let y = bounds.min.y; y <= bounds.max.y; y++) years.push(y);
  const { lo, hi } = monthRangeForYear(bounds, year);
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

      <Field label="Forecast length">
        <Select
          value={duration}
          onChange={(e) => onDuration(Number(e.target.value))}
          disabled={busy}
        >
          {(DURATIONS[grain] || DURATIONS.monthly).map((d) => (
            <option key={d} value={d}>
              {d} {grain === "weekly" ? "weeks" : "months"}
            </option>
          ))}
        </Select>
      </Field>

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
    </div>
  );
}

function formatElapsed(ms) {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function formatSpan(from, to) {
  if (!from || !to) return "No sales history yet";
  const label = (d) => {
    const [y, m] = d.split("-").map(Number);
    return `${MON[m - 1]} ${y}`;
  };
  return `${label(from)} – ${label(to)}`;
}
