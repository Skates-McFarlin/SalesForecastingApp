import { useEffect, useMemo, useState } from "react";
import { createPurchaseOrder, fetchSignalReliability } from "../api";
import { deriveExceptions } from "../exceptions";
import { formatNumber, SectionLabel } from "./ui";

// Per-severity accent used on the leading icon chip and the title colour.
const SEV = {
  critical: { text: "text-neg-500 dark:text-neg-400", chip: "bg-neg-500/10 text-neg-500 dark:text-neg-400", ring: "ring-neg-500/20", label: "Critical" },
  high: { text: "text-amber-600 dark:text-amber-400", chip: "bg-amber-500/12 text-amber-600 dark:text-amber-400", ring: "ring-amber-500/20", label: "High" },
  medium: { text: "text-amber-600 dark:text-amber-400", chip: "bg-amber-400/12 text-amber-600 dark:text-amber-400", ring: "ring-amber-400/20", label: "Medium" },
  low: { text: "text-[var(--ink-2)]", chip: "bg-[var(--surface-3)] text-[var(--ink-3)]", ring: "ring-[var(--line)]", label: "Low" },
};

function TypeIcon({ type }) {
  const p = {
    stockout: "M10 4.5v6M10 14.2v.3M10 2.2 2.2 16h15.6L10 2.2Z",
    overdue: "M10 5.5V10l3 2M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z",
    surge: "M4 13.5 8.5 9l3 3L16.5 6.5M12.5 6.5h4v4",
    collapse: "M4 6.5 8.5 11l3-3 5 5.5M12.5 13.5h4v-4",
    overstock: "M3.5 6.5 10 3l6.5 3.5M3.5 6.5 10 10l6.5-3.5M3.5 6.5v7L10 17l6.5-3.5v-7M10 10v7",
  }[type] || "M10 5v6M10 14.2v.3";
  return (
    <svg className="size-[18px]" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d={p} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// Phase 3 - the app leads with "here's what needs you" rather than making the
// seller go hunting. Derived live from the current forecast + inventory, so
// ordering a stockout item drops it off the list.
export default function Exceptions({ rows, settings, service, onInventoryResult, onOpenForecast, onOpenSku }) {
  // The signal layer's realized reliability, used to discount speculative
  // demand-move flags when ranking (grounded stockouts keep full weight).
  const [reliability, setReliability] = useState(null);
  useEffect(() => {
    let live = true;
    fetchSignalReliability().then((r) => live && setReliability(r)).catch(() => {});
    return () => { live = false; };
  }, [rows]);

  const { items, byType, missingStock, total, totalImpact } = useMemo(
    () => deriveExceptions(rows, settings, service.z, reliability),
    [rows, settings, service, reliability]
  );

  const summary = [
    { key: "stockout", label: "Stockout risk", n: byType.stockout || 0, tone: "text-neg-500 dark:text-neg-400", dot: "bg-neg-500" },
    { key: "overdue", label: "Overdue", n: byType.overdue || 0, tone: "text-amber-600 dark:text-amber-400", dot: "bg-amber-500" },
    { key: "surge", label: "Demand shift", n: (byType.surge || 0) + (byType.collapse || 0), tone: "text-[var(--ink)]", dot: "bg-accent-500" },
    { key: "overstock", label: "Overstock", n: byType.overstock || 0, tone: "text-[var(--ink)]", dot: "bg-amber-400" },
  ];

  return (
    <div className="flex flex-col gap-6">
      {/* Headline — lead with the money, in human language. */}
      <div className="rise">
        <SectionLabel className="mb-2">What needs you</SectionLabel>
        {total > 0 ? (
          <>
            <h1 className="display flex flex-wrap items-end gap-x-2.5 gap-y-1 text-[26px] font-bold leading-none">
              {totalImpact != null ? (
                <>
                  <span className="tnum text-neg-500 dark:text-neg-400">${formatNumber(totalImpact)}</span>
                  <span>at risk</span>
                </>
              ) : (
                <span>{formatNumber(total)} products need attention</span>
              )}
            </h1>
            <p className="mt-2 text-sm text-[var(--ink-2)]">
              Across {formatNumber(total)} of {formatNumber(rows.length)} products
              {totalImpact != null ? " — ranked by dollars of margin and capital at risk." : ", ranked by urgency."}
            </p>
          </>
        ) : (
          <h1 className="display text-[26px] font-bold leading-none">You&rsquo;re in good shape</h1>
        )}
      </div>

      {total > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {summary.map((s) => (
            <div
              key={s.key}
              className="rounded-xl border border-[var(--line)] bg-[var(--surface)] p-3.5 [box-shadow:var(--shadow-sm)]"
            >
              <div className="flex items-center justify-between">
                <SectionLabel>{s.label}</SectionLabel>
                <span className={`size-1.5 rounded-full ${s.n ? s.dot : "bg-[var(--line-strong)]"}`} aria-hidden="true" />
              </div>
              <div className={`tnum mt-1.5 text-[26px] font-bold leading-none ${s.n ? s.tone : "text-[var(--ink-3)]"}`}>
                {formatNumber(s.n)}
              </div>
            </div>
          ))}
        </div>
      )}

      {total === 0 ? (
        <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-12 text-center [box-shadow:var(--shadow-sm)]">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-pos-500/10 text-pos-500 dark:text-pos-400">
            <svg className="size-6" viewBox="0 0 20 20" fill="none">
              <path d="M4 10.5 8.5 15 16 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="text-base font-semibold">All clear</div>
          <p className="max-w-sm text-sm text-[var(--ink-2)]">
            No stockout risks, overdue deliveries, or sharp demand shifts across your catalog.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface)] [box-shadow:var(--shadow-sm)]">
          {items.map((it, i) => (
            <ExceptionRow key={it.key} it={it} first={i === 0} onInventoryResult={onInventoryResult} onOpenSku={onOpenSku} />
          ))}
        </div>
      )}

      {missingStock > 0 && (
        <p className="text-xs text-[var(--ink-3)]">
          {formatNumber(missingStock)} product{missingStock === 1 ? "" : "s"} have no on-hand set, so their
          stockout risk can&rsquo;t be assessed.{" "}
          <button onClick={onOpenForecast} className="font-medium text-accent-600 underline-offset-2 hover:underline dark:text-accent-400">
            Set stock on the Forecast tab
          </button>
          .
        </p>
      )}
    </div>
  );
}

function ExceptionRow({ it, first, onInventoryResult, onOpenSku }) {
  const sev = SEV[it.severity] || SEV.low;
  const [busy, setBusy] = useState(false);

  const order = async (e) => {
    e.stopPropagation();
    setBusy(true);
    try {
      const state = await createPurchaseOrder(it.key, it.order);
      onInventoryResult?.(it.key, state);
    } catch {
      /* leave as-is */
    }
    setBusy(false);
  };

  return (
    <div
      onClick={() => onOpenSku?.(it.key)}
      role={onOpenSku ? "button" : undefined}
      tabIndex={onOpenSku ? 0 : undefined}
      onKeyDown={(e) => onOpenSku && (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpenSku(it.key))}
      className={`flex items-center gap-3.5 border-b border-[var(--line)] px-4 py-3.5 transition-colors last:border-b-0 hover:bg-[var(--surface-2)] ${onOpenSku ? "cursor-pointer" : ""}`}>
      <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl ring-1 ${sev.chip} ${sev.ring}`} title={sev.label}>
        <TypeIcon type={it.type} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-semibold">{it.name}</span>
          {it.sku && <span className="tnum text-[11px] text-[var(--ink-3)]">{it.sku}</span>}
        </div>
        <div className="mt-0.5 text-sm leading-snug">
          <span className={`font-semibold ${sev.text}`}>{it.title}</span>
          <span className="text-[var(--ink-3)]"> — {it.detail}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="hidden text-xs text-[var(--ink-2)] sm:inline">{it.action}</span>
        {it.type === "stockout" && it.order > 0 && (
          <button
            onClick={order}
            disabled={busy}
            className="rounded-lg bg-accent-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-accent-700 disabled:opacity-45"
          >
            {busy ? "Ordering…" : `Order ${formatNumber(it.order)}`}
          </button>
        )}
        {onOpenSku && (
          <svg className="size-4 text-[var(--ink-3)]" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="M8 5l5 5-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </div>
    </div>
  );
}
