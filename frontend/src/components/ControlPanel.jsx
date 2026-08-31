import FileDrop from "./FileDrop";
import { Button, Field, Select, SectionLabel, Spinner } from "./ui";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DURATIONS = [3, 6, 12, 18, 24];

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 11 }, (_, i) => CURRENT_YEAR - 5 + i);

export default function ControlPanel({
  file,
  onFile,
  onReject,
  year,
  month,
  duration,
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
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-5">
      <div>
        <SectionLabel className="mb-1.5">Sales data</SectionLabel>
        <FileDrop file={file} onSelect={onFile} onReject={onReject} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Start month">
          <Select value={month} onChange={(e) => onMonth(Number(e.target.value))} disabled={busy}>
            {MONTHS.map((name, i) => (
              <option key={name} value={i + 1}>
                {name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Year">
          <Select value={year} onChange={(e) => onYear(Number(e.target.value))} disabled={busy}>
            {YEARS.map((y) => (
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
          {DURATIONS.map((d) => (
            <option key={d} value={d}>
              {d} months
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
          <Button className="w-full" onClick={onSubmit} disabled={!file}>
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
