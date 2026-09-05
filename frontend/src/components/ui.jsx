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

// A small stat tile (label + value + optional subtext) used across the summary
// strips. Sits inside a gap-px grid so tiles read as one panel.
export function Stat({ label, value, sub, accent }) {
  return (
    <div className="bg-[var(--surface)] px-4 py-3">
      <SectionLabel>{label}</SectionLabel>
      <div className={`tnum mt-1 text-lg font-semibold ${accent ? "text-accent-600 dark:text-accent-400" : ""}`}>
        {value}
      </div>
      {sub ? <div className="mt-0.5 text-[11px] text-[var(--ink-3)]">{sub}</div> : null}
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

// Service levels (probability of not stocking out) and their z-multipliers, used
// to size safety stock from the forecast's demand spread.
export const SERVICE_LEVELS = [
  { value: 0.9, label: "90%", z: 1.2816 },
  { value: 0.95, label: "95%", z: 1.6449 },
  { value: 0.99, label: "99%", z: 2.3263 },
];

// --- distribution-aware safety stock for low-count (intermittent) demand ---
// A normal z*sigma safety stock under-delivers the stated service level on
// intermittent demand: it's symmetric, but on-and-off demand is right-skewed
// (many zeros, occasional spikes), so the true upper quantile sits higher.
// For low-count demand we instead take the quantile of a COUNT distribution -
// negative binomial when overdispersed (var > mean, the intermittent signature),
// Poisson otherwise. Measured on real retail this closes most of the stated-vs-
// achieved service gap (e.g. order-to-95% delivered ~87% under normal, ~91% here).
function logGamma(x) { // Lanczos
  const c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028,
    771.32342877765313, -176.61502916214059, 12.507343278686905,
    -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - logGamma(1 - x);
  x -= 1; let a = c[0]; const t = x + 7.5;
  for (let i = 1; i < 9; i++) a += c[i] / (x + i);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}
function normalCdf(z) { // Abramowitz-Stegun 26.2.17
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989422804 * Math.exp(-z * z / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return z > 0 ? 1 - p : p;
}
const COUNT_MAX = 120; // above this the normal approximation (CLT) is fine and exact
// Smallest integer S with CDF(S) >= tau for demand over the protection window.
function countQuantile(tau, mean, varr) {
  if (mean <= 0) return 0;
  const od = varr > mean * 1.05;            // overdispersed -> negative binomial
  let r = 0, p = 0;
  if (od) { r = (mean * mean) / (varr - mean); p = mean / varr; }
  const cap = Math.ceil(mean + 12 * Math.sqrt(Math.max(varr, mean)) + 20);
  let cum = 0;
  for (let k = 0; k <= cap; k++) {
    const logPmf = od
      ? logGamma(k + r) - logGamma(k + 1) - logGamma(r) + r * Math.log(p) + k * Math.log(1 - p)
      : -mean + k * Math.log(mean) - logGamma(k + 1); // Poisson
    cum += Math.exp(logPmf);
    if (cum >= tau) return k;
  }
  return cap;
}

// Round a raw order up to the case pack, then up to the minimum order quantity.
function snapOrder(qty, moq, casePack) {
  if (qty <= 0) return 0;
  if (casePack && casePack > 0) qty = Math.ceil(qty / casePack) * casePack;
  if (moq && qty < moq) {
    qty = moq;
    if (casePack && casePack > 0) qty = Math.ceil(qty / casePack) * casePack;
  }
  return qty;
}

// Grounded reorder decision (Phase 2) - the client-side mirror of the backend's
// reorder_policy(), so editing on-hand / lead time / service level updates the
// recommendation instantly without re-forecasting. Periodic-review base stock:
// order up to (demand over lead time + review period + safety), net of the stock
// you already have and have coming. Keep in lock-step with inventory_controller.
export function reorder(row, settings, z) {
  const r = Math.max(0, Number(row.DailyRate || 0));
  const s = Math.max(0, Number(row.DailySigma || 0));
  // Lead time precedence: learned from received POs -> typed -> business default.
  let leadDays = settings?.default_lead_time_days ?? 14;
  let leadSource = "default";
  if (row.LeadLearned != null) {
    leadDays = row.LeadLearned;
    leadSource = "learned";
  } else if (row.LeadTimeDays != null && row.LeadTimeDays !== "") {
    leadDays = row.LeadTimeDays;
    leadSource = "typed";
  }
  const L = Math.max(0, Number(leadDays));
  const R = Math.max(1, Number(settings?.review_period_days ?? 7));
  const P = L + R;

  const hasInventory = row.OnHand != null && row.OnHand !== "";
  const position = Number(row.OnHand || 0) + Number(row.OnOrder || 0);

  // Order-up-to = the service-level quantile of demand over the protection
  // window P (and lead time L for the reorder point). Count-aware for low-count
  // demand (honest on intermittent SKUs), normal for high-volume where it's fine.
  const tau = normalCdf(z);
  const upTo = (mu, sd) =>
    mu > 0 && mu <= COUNT_MAX ? countQuantile(tau, mu, sd * sd) : mu + z * sd;
  const orderUpTo = upTo(r * P, s * Math.sqrt(P));
  const reorderPoint = upTo(r * L, s * Math.sqrt(L));
  const safety = Math.max(0, orderUpTo - r * P);
  const order = snapOrder(Math.max(0, orderUpTo - position), Number(row.MOQ) || 0, Number(row.CasePack) || 0);
  const coverDays = hasInventory && r > 0 ? Number(row.OnHand) / r : null;

  return {
    order: Math.round(order),
    safety: Math.round(safety),
    orderUpTo: Math.round(orderUpTo),
    reorderPoint: Math.round(reorderPoint),
    position: Math.round(position),
    leadTimeDays: L,
    leadSource,
    leadObs: Number(row.LeadObs || 0),
    onOrder: Math.round(Number(row.OnOrder || 0)),
    coverDays,
    // Only flag/gate on stock position when we actually know the on-hand.
    reorderNow: hasInventory ? position <= reorderPoint : false,
    hasInventory,
  };
}
