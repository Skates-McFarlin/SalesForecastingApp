import { useEffect, useState } from "react";
import { fetchLedger, fetchRun, fetchLearning } from "../api";
import { Badge, Card, DeltaBadge, formatNumber, SectionLabel, Spinner, Stat } from "./ui";

// The decision & outcome ledger (Phase 1): every forecast the app made, and -
// once real sales cover its window - how that forecast actually held up. This is
// an honest track record on the user's own business, not a synthetic backtest.
export default function Ledger({ reloadToken }) {
  const [runs, setRuns] = useState(null);
  const [learning, setLearning] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [details, setDetails] = useState({});

  useEffect(() => {
    let live = true;
    setError(null);
    fetchLedger()
      .then((data) => live && setRuns(data))
      .catch((err) => live && setError(err.message));
    fetchLearning()
      .then((data) => live && setLearning(data))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [reloadToken]);

  const toggle = async (run) => {
    if (expanded === run.id) {
      setExpanded(null);
      return;
    }
    setExpanded(run.id);
    if (details[run.id]?.items || details[run.id]?.loading) return;
    setDetails((d) => ({ ...d, [run.id]: { loading: true } }));
    try {
      const detail = await fetchRun(run.id);
      setDetails((d) => ({ ...d, [run.id]: detail }));
    } catch (err) {
      setDetails((d) => ({ ...d, [run.id]: { error: err.message } }));
    }
  };

  if (error) {
    return (
      <Card className="p-6 text-sm text-neg-500 dark:text-neg-400">
        Couldn’t load the track record: {error}
      </Card>
    );
  }
  if (runs === null) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[var(--ink-2)]">
        <Spinner className="size-4 text-accent-500" /> Loading your track record…
      </div>
    );
  }
  if (runs.length === 0) return <EmptyLedger />;

  const scored = runs.filter((r) => r.status === "complete");

  return (
    <div className="flex flex-col gap-5">
      <div>
        <SectionLabel className="mb-1">Track record</SectionLabel>
        <p className="max-w-2xl text-sm leading-relaxed text-[var(--ink-2)]">
          Every forecast the app makes is recorded here. Once your synced sales
          catch up to a forecast’s window, it’s graded automatically against what
          actually sold — so you can see how accurate the app has been on your own
          business.
        </p>
      </div>

      {scored.length > 0 && <Headline runs={scored} />}

      {learning && learning.corrected_skus > 0 && (
        <div className="flex items-start gap-2.5 rounded-xl border border-accent-500/30 bg-accent-500/5 px-4 py-3">
          <svg className="mt-0.5 size-4 shrink-0 text-accent-600 dark:text-accent-400" viewBox="0 0 16 16" fill="none">
            <path d="M2 8a6 6 0 0 1 10-4.5M14 8a6 6 0 0 1-10 4.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            <path d="M12 2v2.2H9.8M4 14v-2.2h2.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <p className="text-sm leading-relaxed text-[var(--ink-2)]">
            <span className="font-medium text-[var(--ink)]">The app is learning your business.</span>{" "}
            From {formatNumber(learning.reconciled_items)} graded forecasts it now auto-corrects{" "}
            <span className="font-medium text-accent-600 dark:text-accent-400">{formatNumber(learning.corrected_skus)}</span>{" "}
            {learning.corrected_skus === 1 ? "product" : "products"} — adjusting the forecast where your sales
            consistently run above or below it, so future orders get more accurate.
          </p>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-[var(--line)]">
        {runs.map((run) => (
          <RunRow
            key={run.id}
            run={run}
            isOpen={expanded === run.id}
            detail={details[run.id]}
            onToggle={() => toggle(run)}
          />
        ))}
      </div>
    </div>
  );
}

// A single portfolio-wide accuracy figure across every scored run, so the user
// gets one honest headline: how far off, on average, weighted by volume.
function Headline({ runs }) {
  let totalF = 0;
  let totalA = 0;
  let absErr = 0;
  let within = 0;
  let scored = 0;
  for (const r of runs) {
    const s = r.stats;
    if (!s) continue;
    totalF += s.total_forecast;
    totalA += s.total_actual;
    // Recover each run's total absolute (per-SKU) error from its portfolio
    // error. Summing |totalF - totalA| instead would let a run's over- and
    // under-forecasts cancel, flattering the number down to net bias.
    if (s.portfolio_error != null) absErr += (s.portfolio_error / 100) * s.total_actual;
    within += s.within_interval;
    scored += s.scored_items;
  }
  const err = totalA > 0 ? (absErr / totalA) * 100 : null;
  const bias = totalA > 0 ? ((totalF - totalA) / totalA) * 100 : null;
  const coverage = scored > 0 ? (within / scored) * 100 : null;

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--line)] sm:grid-cols-4">
      <Stat label="Scored forecasts" value={`${runs.length}`} sub={`${scored} SKU outcomes`} />
      <Stat
        label="Typical miss"
        value={err == null ? "—" : `±${err.toFixed(0)}%`}
        sub="of units sold"
      />
      <Stat label="Bias" value={<DeltaBadge value={bias == null ? "N/A" : bias.toFixed(1)} />} sub="over/under-forecast" />
      <Stat
        label="Within range"
        value={coverage == null ? "—" : `${coverage.toFixed(0)}%`}
        sub="landed in the band"
      />
    </div>
  );
}

function RunRow({ run, isOpen, detail, onToggle }) {
  const unit = run.grain === "weekly" ? "week" : "month";
  const recorded = run.created_at
    ? new Date(run.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : "";
  const s = run.stats;

  return (
    <div className="border-b border-[var(--line)] last:border-b-0">
      <button
        onClick={onToggle}
        className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors ${
          isOpen ? "bg-accent-500/6" : "hover:bg-[var(--surface-2)]"
        }`}
      >
        <svg
          className={`size-3.5 shrink-0 text-[var(--ink-3)] transition-transform ${isOpen ? "rotate-90" : ""}`}
          viewBox="0 0 14 14"
          fill="none"
        >
          <path d="m5 3 4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div className="min-w-0 flex-1">
          <div className="font-medium">{run.period}</div>
          <div className="mt-0.5 text-[11px] text-[var(--ink-3)]">
            {run.horizon} {unit}
            {run.horizon === 1 ? "" : "s"} · {run.product_count} products · recorded {recorded}
          </div>
        </div>
        {run.status === "complete" && s ? (
          <div className="flex items-center gap-4 text-right">
            <div>
              <div className="tnum text-sm font-semibold">
                {s.portfolio_error == null ? "—" : `±${s.portfolio_error.toFixed(0)}%`}
              </div>
              <div className="text-[10px] tracking-wide text-[var(--ink-3)] uppercase">miss</div>
            </div>
            <DeltaBadge value={s.bias == null ? "N/A" : s.bias.toFixed(1)} />
          </div>
        ) : (
          <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400">
            Awaiting sales
          </Badge>
        )}
      </button>

      {isOpen && (
        <div className="border-t border-[var(--line)] bg-accent-500/4 px-4 py-3">
          {detail?.loading && (
            <div className="flex items-center gap-2 text-sm text-[var(--ink-2)]">
              <Spinner className="size-3.5 text-accent-500" /> Loading run detail…
            </div>
          )}
          {detail?.error && <div className="text-sm text-neg-500 dark:text-neg-400">{detail.error}</div>}
          {detail?.items && <DetailTable detail={detail} />}
        </div>
      )}
    </div>
  );
}

function DetailTable({ detail }) {
  const scored = detail.status === "complete";
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--line)] bg-[var(--surface)]">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-[var(--surface-2)]">
          <tr className="border-b border-[var(--line)] text-[10px] font-semibold tracking-[0.09em] text-[var(--ink-3)] uppercase">
            <th className="px-3 py-2 text-left">Product</th>
            <th className="px-3 py-2 text-right">Forecast</th>
            <th className="px-3 py-2 text-right">Order</th>
            <th className="px-3 py-2 text-right">Actual</th>
            <th className="px-3 py-2 text-right">Error</th>
          </tr>
        </thead>
        <tbody>
          {detail.items.map((it, i) => (
            <tr key={i} className="border-b border-[var(--line)] last:border-b-0">
              <td className="px-3 py-2">
                <div className="font-medium">{it.product_name}</div>
                {it.sku && <div className="tnum text-[11px] text-[var(--ink-3)]">{it.sku}</div>}
              </td>
              <td className="tnum px-3 py-2 text-right">{formatNumber(it.forecast)}</td>
              <td className="tnum px-3 py-2 text-right text-accent-600 dark:text-accent-400">
                {formatNumber(it.recommended_order)}
              </td>
              <td className="tnum px-3 py-2 text-right">
                {scored && it.actual != null ? (
                  <span className="inline-flex items-center justify-end gap-1.5">
                    {formatNumber(it.actual)}
                    {it.within_interval != null && <Dot ok={it.within_interval} />}
                  </span>
                ) : (
                  <span className="text-[var(--ink-3)]">—</span>
                )}
              </td>
              <td className="px-3 py-2 text-right">
                <DeltaBadge value={it.error_pct == null ? "N/A" : it.error_pct} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {scored && (
        <p className="px-3 py-2 text-[11px] leading-relaxed text-[var(--ink-3)]">
          The dot shows whether actual sales landed inside the forecast’s confidence range.
          “Order” is what the app recommended buying at the {(detail.service_level * 100).toFixed(0)}% service level.
        </p>
      )}
    </div>
  );
}

function Dot({ ok }) {
  return (
    <span
      title={ok ? "Actual landed inside the forecast range" : "Actual fell outside the forecast range"}
      className={`inline-block size-2 rounded-full ${
        ok ? "bg-pos-500 dark:bg-pos-400" : "bg-neg-500 dark:bg-neg-400"
      }`}
    />
  );
}

function EmptyLedger() {
  return (
    <div className="flex h-full min-h-80 items-center justify-center">
      <div className="max-w-sm text-center">
        <div className="mx-auto flex size-11 items-center justify-center rounded-xl border border-[var(--line)] bg-[var(--surface)]">
          <svg className="size-5 text-[var(--ink-3)]" viewBox="0 0 20 20" fill="none">
            <path d="M3 10.5 8 15l9-10" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <h2 className="mt-4 text-sm font-semibold">No forecasts recorded yet</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-2)]">
          Generate a forecast and it’s logged here. As you sync new sales, the app grades its
          past forecasts against what actually sold — building an honest track record over time.
        </p>
      </div>
    </div>
  );
}
