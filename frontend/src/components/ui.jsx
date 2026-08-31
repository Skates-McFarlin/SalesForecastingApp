export function Card({ className = "", children, ...rest }) {
  return (
    <div
      className={`rounded-xl border bg-[var(--surface)] border-[var(--line)] ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

export function SectionLabel({ children, className = "" }) {
  return (
    <div
      className={`text-[10px] font-semibold uppercase tracking-[0.09em] text-[var(--ink-3)] ${className}`}
    >
      {children}
    </div>
  );
}

export function Button({ variant = "primary", className = "", children, ...rest }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-colors " +
    "disabled:opacity-45 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 " +
    "focus-visible:outline-accent-500";
  const variants = {
    primary: "bg-accent-500 text-white hover:bg-accent-600 active:bg-accent-700 px-4 py-2.5",
    secondary:
      "border border-[var(--line-strong)] text-[var(--ink)] hover:bg-[var(--surface-2)] px-3.5 py-2",
    ghost: "text-[var(--ink-2)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)] px-2.5 py-1.5",
  };
  return (
    <button className={`${base} ${variants[variant]} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <SectionLabel className="mb-1.5">{label}</SectionLabel>
      {children}
      {hint ? <div className="mt-1 text-xs text-[var(--ink-3)]">{hint}</div> : null}
    </label>
  );
}

const controlClasses =
  "w-full rounded-lg border border-[var(--line-strong)] bg-[var(--surface)] px-3 py-2 text-sm " +
  "text-[var(--ink)] outline-none transition-colors focus:border-accent-500 " +
  "focus:ring-2 focus:ring-accent-500/25";

export function Select({ className = "", children, ...rest }) {
  return (
    <select className={`${controlClasses} ${className}`} {...rest}>
      {children}
    </select>
  );
}

export function Input({ className = "", ...rest }) {
  return <input className={`${controlClasses} ${className}`} {...rest} />;
}

export function Spinner({ className = "size-4" }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.22" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Signed percentage, colour-coded, with a fixed-width sign so columns align. */
export function DeltaBadge({ value }) {
  if (value === "N/A" || value === null || value === undefined) {
    return <span className="text-[var(--ink-3)]">—</span>;
  }
  const n = Number(value);
  if (Number.isNaN(n)) return <span className="text-[var(--ink-3)]">—</span>;
  const up = n > 0;
  const flat = n === 0;
  return (
    <span
      className={`tnum inline-flex items-center gap-1 text-sm font-medium ${
        flat
          ? "text-[var(--ink-2)]"
          : up
            ? "text-pos-500 dark:text-pos-400"
            : "text-neg-500 dark:text-neg-400"
      }`}
    >
      {!flat && (
        <svg className="size-3" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path
            d={up ? "M6 10V2M6 2L2.5 5.5M6 2l3.5 3.5" : "M6 2v8M6 10l3.5-3.5M6 10L2.5 6.5"}
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
      {n > 0 ? "+" : ""}
      {n.toFixed(1)}%
    </span>
  );
}

export function Badge({ children, className = "" }) {
  if (!children || children === "unknown") return null;
  return (
    <span
      className={`inline-flex items-center rounded-md border border-[var(--line)] bg-[var(--surface-2)] px-1.5 py-0.5 text-[11px] font-medium text-[var(--ink-2)] ${className}`}
    >
      {children}
    </span>
  );
}

export function ErrorNote({ children, onDismiss }) {
  if (!children) return null;
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-neg-500/35 bg-neg-500/8 px-3 py-2.5 text-sm text-neg-500 dark:text-neg-400">
      <svg className="mt-px size-4 shrink-0" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 5v3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="8" cy="11" r="0.85" fill="currentColor" />
      </svg>
      <span className="flex-1">{children}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="shrink-0 opacity-60 hover:opacity-100"
          aria-label="Dismiss"
        >
          <svg className="size-3.5" viewBox="0 0 14 14" fill="none">
            <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      )}
    </div>
  );
}

export function formatNumber(n) {
  const v = Number(n);
  if (Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
