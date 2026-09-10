import { useMemo, useState } from "react";
import { createPurchaseOrder } from "../api";
import { deriveExceptions } from "../exceptions";
import { Card, formatNumber, SectionLabel, Stat } from "./ui";

const SEV = {
  critical: { dot: "bg-neg-500", ring: "border-neg-500/40", text: "text-neg-500 dark:text-neg-400", label: "Critical" },
  high: { dot: "bg-amber-500", ring: "border-amber-500/40", text: "text-amber-600 dark:text-amber-400", label: "High" },
  medium: { dot: "bg-amber-400", ring: "border-amber-400/40", text: "text-amber-600 dark:text-amber-400", label: "Medium" },
  low: { dot: "bg-[var(--ink-3)]", ring: "border-[var(--line)]", text: "text-[var(--ink-3)]", label: "Low" },
};

// Phase 3 - the app leads with "here's what needs you" rather than making the
// seller go hunting. Derived live from the current forecast + inventory, so
// ordering a stockout item drops it off the list.
export default function Exceptions({ rows, settings, service, onInventoryResult, onOpenForecast }) {
  const { items, byType, missingStock, total, totalImpact } = useMemo(
    () => deriveExceptions(rows, settings, service.z),
    [rows, settings, service]
  );

  const summary = [
    { label: "Stockout risk", n: (byType.stockout || 0), tone: "text-neg-500 dark:text-neg-400" },
    { label: "Overdue", n: (byType.overdue || 0), tone: "text-amber-600 dark:text-amber-400" },
    { label: "Demand shift", n: (byType.surge || 0) + (byType.collapse || 0), tone: "text-[var(--ink-2)]" },
    { label: "Overstock", n: (byType.overstock || 0), tone: "text-[var(--ink-2)]" },
  ];

  return (
    <div className="flex flex-col gap-5">
      <div>
        <SectionLabel className="mb-1">What needs you</SectionLabel>
        <p className="max-w-2xl text-sm leading-relaxed text-[var(--ink-2)]">
          {total > 0
            ? `${formatNumber(total)} of your ${formatNumber(rows.length)} products need attention right now — ${
                totalImpact != null
                  ? `about $${formatNumber(totalImpact)} of margin and capital at stake, ranked by dollars at risk`
                  : "ranked by urgency"}.`
            : "Everything's in good shape — nothing needs action right now."}
        </p>
      </div>

      {total > 0 && (
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
          {summary.map((s) => (
            <Stat
              key={s.label}
              label={s.label}
              value={formatNumber(s.n)}
              tone={s.n ? s.tone : "text-[var(--ink-3)]"}
            />
          ))}
        </div>
      )}

      {total === 0 ? (
        <Card className="flex flex-col items-center gap-2 p-10 text-center">
          <div className="flex size-11 items-center justify-center rounded-xl border border-pos-500/40 bg-pos-500/10">
            <svg className="size-5 text-pos-500 dark:text-pos-400" viewBox="0 0 20 20" fill="none">
              <path d="M4 10.5 8.5 15 16 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="text-sm font-semibold">All clear</div>
          <p className="max-w-sm text-sm text-[var(--ink-2)]">
            No stockout risks, overdue deliveries, or sharp demand shifts across your catalog.
          </p>
        </Card>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--line)]">
          {items.map((it) => (
            <ExceptionRow key={it.key} it={it} onInventoryResult={onInventoryResult} />
          ))}
        </div>
      )}

      {missingStock > 0 && (
        <p className="text-xs text-[var(--ink-3)]">
          {formatNumber(missingStock)} product{missingStock === 1 ? "" : "s"} have no on-hand set, so their
          stockout risk can’t be assessed.{" "}
          <button onClick={onOpenForecast} className="text-accent-600 underline-offset-2 hover:underline dark:text-accent-400">
            Set stock on the Forecast tab
          </button>
          .
        </p>
      )}
    </div>
  );
}

function ExceptionRow({ it, onInventoryResult }) {
  const sev = SEV[it.severity] || SEV.low;
  const [busy, setBusy] = useState(false);

  const order = async () => {
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
    <div className="flex items-center gap-3 border-b border-[var(--line)] px-4 py-3 last:border-b-0">
      <span className={`mt-0.5 size-2.5 shrink-0 rounded-full ${sev.dot}`} title={sev.label} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium">{it.name}</span>
          {it.sku && <span className="tnum text-[11px] text-[var(--ink-3)]">{it.sku}</span>}
        </div>
        <div className="mt-0.5 text-sm">
          <span className={`font-medium ${sev.text}`}>{it.title}</span>
          <span className="text-[var(--ink-3)]"> — {it.detail}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="hidden text-xs text-[var(--ink-2)] sm:inline">{it.action}</span>
        {it.type === "stockout" && it.order > 0 && (
          <button
            onClick={order}
            disabled={busy}
            className="rounded-md bg-accent-500 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-accent-600 disabled:opacity-45"
          >
            {busy ? "Ordering…" : `Order ${formatNumber(it.order)}`}
          </button>
        )}
      </div>
    </div>
  );
}
