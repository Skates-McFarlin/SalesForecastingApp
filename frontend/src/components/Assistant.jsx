import { useEffect, useRef, useState } from "react";
import { askAssistant, fetchLearning, fetchLedger, fetchBriefing } from "../api";
import { deriveExceptions } from "../exceptions";
import { optimizeBudget } from "../optimize";
import { reorder, SectionLabel, Spinner } from "./ui";

const SUGGESTIONS = [
  "What needs my attention?",
  "How accurate have you been?",
  "What should I reorder now?",
  "If I only had $20,000, what would you buy?",
];

const money = (n) => `$${Math.round(n).toLocaleString()}`;
const pct = (x) => `${Math.round(x * 100)}%`;

function resolveProducts(question, rows) {
  const q = question.toLowerCase();
  const out = [];
  for (const r of rows) {
    const sku = (r.Sku || "").toLowerCase();
    const words = (r.ProductName || "").toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length >= 4);
    if ((sku && q.includes(sku)) || words.some((w) => q.includes(w))) out.push(r);
    if (out.length >= 4) break;
  }
  return out;
}

// Assemble a snapshot of REAL, client-computed figures for the question. The
// backend LLM only phrases an answer from these — it never computes numbers.
function assembleSnapshot(question, { rows, settings, service, catalog, learning, ledger }) {
  const z = service.z;
  const exc = deriveExceptions(rows, settings, z);
  const full = optimizeBudget(rows, settings, z, Infinity);

  let demand = 0, order = 0, reorderNow = 0;
  for (const r of rows) {
    const d = reorder(r, settings, z);
    demand += Number(r.Forecast || 0);
    order += d.order;
    if (d.hasInventory && d.reorderNow) reorderNow += 1;
  }

  let miss = null;
  const scored = (ledger || []).filter((x) => x.status === "complete" && x.stats);
  if (scored.length) {
    let ae = 0, ta = 0;
    for (const s of scored) {
      ae += (s.stats.portfolio_error / 100) * s.stats.total_actual;
      ta += s.stats.total_actual;
    }
    if (ta > 0) miss = `±${Math.round((ae / ta) * 100)}%`;
  }

  // If the question is about a specific cash amount, actually run the budget
  // optimizer at that figure so the assistant can answer it concretely.
  let budgetScenario = null;
  if (/\$|\bbudget\b|\bspend\b|\bafford\b|\bthousand\b|\d\s*k\b/i.test(question)) {
    const m = question.replace(/,/g, "").match(/\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(k|thousand)/i);
    if (m) {
      let amt = parseFloat(m[1] || m[2]);
      if (m[3]) amt *= 1000;
      if (amt >= 100 && amt < full.idealCost * 5) {
        const p = optimizeBudget(rows, settings, z, amt);
        budgetScenario = {
          budget: Math.round(amt),
          allocated: Math.round(p.allocatedSpend),
          coverage: pct(p.coverage),
          expected_service: pct(p.expectedService),
          funded: p.counts.funded,
          partial: p.counts.partial,
          skipped: p.counts.unfunded,
        };
      }
    }
  }

  const products = resolveProducts(question, rows).map((r) => {
    const d = reorder(r, settings, z);
    return {
      name: r.ProductName,
      sku: r.Sku,
      category: r.Category && r.Category !== "unknown" ? r.Category : null,
      forecast: Math.round(Number(r.Forecast || 0)),
      yoy: r["% Change from Previous Year"] !== "N/A" ? `${r["% Change from Previous Year"]}%` : null,
      on_hand: r.OnHand != null ? r.OnHand : null,
      cover_days: d.coverDays != null ? Math.round(d.coverDays) : null,
      suggested_order: d.order,
      reorder_now: d.hasInventory && d.reorderNow,
      lead_time: d.leadTimeDays,
      // Stockout de-censoring: the forecast reconstructed likely-out-of-stock
      // periods to demand, so the assistant can explain a lifted forecast.
      stockout_periods: Array.isArray(r.StockoutPeriods) ? r.StockoutPeriods : [],
    };
  });

  return {
    business:
      catalog && !catalog.empty
        ? { products: catalog.products, span: `${catalog.date_from} to ${catalog.date_to}`, grain: catalog.grain }
        : null,
    attention: {
      total: exc.total,
      stockout: exc.byType.stockout || 0,
      overdue: exc.byType.overdue || 0,
      demand_shift: (exc.byType.surge || 0) + (exc.byType.collapse || 0),
      overstock: exc.byType.overstock || 0,
      top: exc.items.slice(0, 5).map((it) => `${it.name}: ${it.title} — ${it.detail}`),
    },
    plan: {
      forecast_demand: Math.round(demand),
      suggested_order: Math.round(order),
      reorder_now: reorderNow,
      full_restock_cost: Math.round(full.idealCost),
      service_level: service.label,
      expected_service_full: pct(full.serviceIfFull),
    },
    track_record: learning
      ? {
          graded_skus: learning.graded_skus,
          reconciled: learning.reconciled_items,
          realized_coverage: learning.coverage != null ? pct(learning.coverage) : null,
          biased_skus: learning.biased_skus,
          typical_miss: miss,
        }
      : miss
        ? { typical_miss: miss }
        : null,
    budget_scenario: budgetScenario,
    products,
  };
}

export default function Assistant({ rows, settings, service, catalog }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [learning, setLearning] = useState(null);
  const [ledger, setLedger] = useState(null);
  const [brief, setBrief] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    fetchLearning().then(setLearning).catch(() => {});
    fetchLedger().then(setLedger).catch(() => {});
  }, [rows]);

  // Proactive "here's what matters today" - fetched once on open. Sends live
  // attention counts so an urgent stockout leads; trends/trust come server-side.
  useEffect(() => {
    setBrief(null);
    const snap = assembleSnapshot("", { rows, settings, service, catalog, learning, ledger });
    fetchBriefing({ attention: snap.attention })
      .then((r) => setBrief(r.briefing || null))
      .catch(() => {});
  }, [rows, settings, service]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const send = async (text) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput("");
    const history = messages.slice(-4).map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: "user", content: q }]);
    setBusy(true);
    try {
      const snapshot = assembleSnapshot(q, { rows, settings, service, catalog, learning, ledger });
      const res = await askAssistant(q, snapshot, history);
      setMessages((m) => [...m, { role: "assistant", content: res.answer, unverified: res.unverified }]);
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", content: `Sorry — ${err.message}`, error: true }]);
    }
    setBusy(false);
  };

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col">
      <div>
        <SectionLabel className="mb-1">Ask Insighta</SectionLabel>
        <p className="max-w-2xl text-sm leading-relaxed text-[var(--ink-2)]">
          Ask about your business in plain language. Every figure comes from your live forecast,
          inventory, and track record — the assistant explains, it doesn’t make numbers up.
        </p>
      </div>

      <div ref={scrollRef} className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto pb-2">
        {messages.length === 0 && brief && (
          <div className="flex items-start gap-2.5 rounded-xl border border-accent-500/30 bg-accent-500/5 px-4 py-3">
            <svg className="mt-0.5 size-4 shrink-0 text-accent-600 dark:text-accent-400" viewBox="0 0 16 16" fill="none">
              <path d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8 3.4 3.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.3" />
            </svg>
            <div>
              <SectionLabel className="mb-1">What matters today</SectionLabel>
              <p className="text-sm leading-relaxed text-[var(--ink-2)]">{brief}</p>
            </div>
          </div>
        )}
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-2 pt-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="rounded-full border border-[var(--line-strong)] px-3 py-1.5 text-sm text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <Bubble key={i} m={m} />
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-sm text-[var(--ink-3)]">
            <Spinner className="size-3.5 text-accent-500" /> Thinking…
          </div>
        )}
      </div>

      <div className="mt-3 flex items-end gap-2 border-t border-[var(--line)] pt-3">
        <textarea
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask about a product, what to reorder, your budget…"
          className="max-h-32 flex-1 resize-none rounded-lg border border-[var(--line-strong)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-accent-500"
        />
        <button
          onClick={() => send()}
          disabled={busy || !input.trim()}
          className="rounded-lg bg-accent-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-600 disabled:opacity-45"
        >
          Send
        </button>
      </div>
    </div>
  );
}

function Bubble({ m }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-accent-500 px-3.5 py-2 text-sm text-white">
          {m.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[85%] rounded-2xl rounded-bl-sm border px-3.5 py-2 text-sm leading-relaxed ${
          m.error
            ? "border-neg-500/35 bg-neg-500/8 text-neg-500 dark:text-neg-400"
            : "border-[var(--line)] bg-[var(--surface)] text-[var(--ink-2)]"
        }`}
      >
        {m.content}
        {m.unverified && (
          <div className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-400">
            ⚠ Some figures here couldn’t be verified against your data — double-check before acting.
          </div>
        )}
      </div>
    </div>
  );
}
