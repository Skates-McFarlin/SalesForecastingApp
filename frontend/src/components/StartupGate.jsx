import { useEffect, useRef, useState } from "react";
import { fetchHealth } from "../api";
import { Spinner } from "./ui";

const COPY = {
  connecting: {
    title: "Starting the engine",
    detail: "Waiting for the local forecasting service…",
  },
  starting: { title: "Starting the engine", detail: "Bringing up the local service…" },
  downloading_model: {
    title: "Downloading the AI model",
    detail: "One-time setup, about 1.1 GB. Future launches skip this entirely.",
  },
  loading_model: { title: "Loading the AI model", detail: "Almost ready…" },
};

// Windows Defender scans the freshly installed binaries on the very first
// launch, which can hold the backend off for a couple of minutes. Say so
// rather than letting it look hung.
const SLOW_START_AFTER_MS = 25000;

export default function StartupGate({ children }) {
  const [health, setHealth] = useState({ status: "connecting", ready: false, error: null });
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef(Date.now());

  useEffect(() => {
    let cancelled = false;
    let timer;

    const poll = async () => {
      try {
        const next = await fetchHealth();
        if (!cancelled) setHealth(next);
        if (next.ready || next.error) return;
      } catch {
        if (!cancelled) setHealth({ status: "connecting", ready: false, error: null });
      }
      if (!cancelled) timer = setTimeout(poll, 1000);
    };
    poll();

    const tick = setInterval(() => setElapsed(Date.now() - startedAt.current), 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearInterval(tick);
    };
  }, []);

  if (health.ready) return children;

  const copy = COPY[health.status] ?? COPY.connecting;
  const slow = !health.error && health.status === "connecting" && elapsed > SLOW_START_AFTER_MS;
  const seconds = Math.floor(elapsed / 1000);

  return (
    <div className="flex h-full items-center justify-center bg-[var(--page)] p-6">
      <div className="w-full max-w-md rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-8 shadow-sm">
        <div className="flex items-center gap-3">
          <Mark />
          <span className="text-lg font-semibold tracking-tight">Insighta</span>
        </div>

        {health.error ? (
          <>
            <h1 className="mt-7 text-base font-semibold text-neg-500 dark:text-neg-400">
              The service failed to start
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-[var(--ink-2)]">
              Restarting the app usually clears this. If it keeps happening, reinstalling will
              repair the local files.
            </p>
            <pre className="mt-4 max-h-40 overflow-auto rounded-lg border border-[var(--line)] bg-[var(--surface-2)] p-3 text-xs whitespace-pre-wrap text-[var(--ink-2)]">
              {health.error}
            </pre>
          </>
        ) : (
          <>
            <div className="mt-7 flex items-center gap-2.5">
              <Spinner className="size-4 text-accent-500" />
              <h1 className="text-base font-semibold">{copy.title}</h1>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-[var(--ink-2)]">{copy.detail}</p>

            <div className="mt-5 h-1 overflow-hidden rounded-full bg-[var(--surface-3)]">
              <div className="h-full w-1/3 animate-[shimmer_1.6s_infinite] rounded-full bg-accent-500/70" />
            </div>

            <div className="mt-3 flex items-center justify-between text-xs text-[var(--ink-3)]">
              <span className="tnum">{seconds}s elapsed</span>
              {slow && <span>First launch after install is slower</span>}
            </div>

            {slow && (
              <p className="mt-4 rounded-lg border border-[var(--line)] bg-[var(--surface-2)] p-3 text-xs leading-relaxed text-[var(--ink-2)]">
                Windows scans newly installed programs the first time they run, which can add a
                couple of minutes. This only happens once — later launches take a few seconds.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Mark() {
  return (
    <svg className="size-7" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <rect width="28" height="28" rx="7" className="fill-accent-500" />
      <path
        d="M7.5 18.5 12 13l3.5 3.5L20.5 9"
        stroke="white"
        strokeWidth="2.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
