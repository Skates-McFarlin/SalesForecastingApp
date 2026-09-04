// The Electron window is loaded over file://, so requests must be absolute.
// The backend enables CORS for /api/*, and in `vite dev` the proxy in
// vite.config.js points the same paths at this host anyway.
const BASE = "http://127.0.0.1:5000";

async function asJson(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    // fall through to a status-based message below
  }
  if (!res.ok) {
    throw new Error(body?.error || `Request failed (${res.status})`);
  }
  return body;
}

export async function fetchHealth() {
  return asJson(await fetch(`${BASE}/api/health`));
}

function forecastForm(file, startDate, duration) {
  const form = new FormData();
  form.append("file", file);
  form.append("start_date", startDate);
  form.append("duration", String(duration));
  return form;
}

export async function generateForecast(file, startDate, duration, { signal } = {}) {
  return asJson(
    await fetch(`${BASE}/api/predictions/generate`, {
      method: "POST",
      body: forecastForm(file, startDate, duration),
      signal,
    })
  );
}

export async function fetchErrorMetrics(file, startDate, duration, { signal } = {}) {
  return asJson(
    await fetch(`${BASE}/api/predictions/error_metrics`, {
      method: "POST",
      body: forecastForm(file, startDate, duration),
      signal,
    })
  );
}

// Peek at a file's month coverage so the date pickers can reflect real data.
// Best-effort: on any failure we return null and the UI keeps its defaults.
export async function inspectFile(file, { signal } = {}) {
  try {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/api/predictions/inspect`, {
      method: "POST",
      body: form,
      signal,
    });
    const body = await res.json();
    return body?.range ?? null;
  } catch {
    return null;
  }
}

// --- Stateful catalog (Phase 0) -------------------------------------------

export async function fetchCatalog() {
  return asJson(await fetch(`${BASE}/api/catalog`));
}

export async function importSales(file) {
  const form = new FormData();
  form.append("file", file);
  return asJson(
    await fetch(`${BASE}/api/catalog/import`, { method: "POST", body: form })
  );
}

async function catalogRun(path, startDate, duration, signal) {
  return asJson(
    await fetch(`${BASE}/api/catalog/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_date: startDate, duration }),
      signal,
    })
  );
}

export async function forecastCatalog(startDate, duration, { signal } = {}) {
  return catalogRun("forecast", startDate, duration, signal);
}

export async function scoreCatalogAccuracy(startDate, duration, { signal } = {}) {
  return catalogRun("accuracy", startDate, duration, signal);
}

export async function fetchSummary(predictionId) {
  const body = await asJson(await fetch(`${BASE}/api/predictions/${predictionId}/summary`));
  return body.Summary;
}
