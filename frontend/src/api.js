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

// Forecast always anchors at the catalog's data edge (the backend derives the
// origin), so this sends a horizon length - no start date to mis-align. An
// optional windowStart reports only a specific future window (e.g. just Q4); the
// full path from the edge is still forecast to reach it.
export async function forecastCatalog(duration, { windowStart = null, signal } = {}) {
  return asJson(
    await fetch(`${BASE}/api/catalog/forecast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration, window_start: windowStart }),
      signal,
    })
  );
}

// Accuracy backtests a chosen in-history window, so it keeps the start date.
export async function scoreCatalogAccuracy(startDate, duration, { signal } = {}) {
  return asJson(
    await fetch(`${BASE}/api/catalog/accuracy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_date: startDate, duration }),
      signal,
    })
  );
}

export async function fetchSummary(predictionId) {
  const body = await asJson(await fetch(`${BASE}/api/predictions/${predictionId}/summary`));
  return body.Summary;
}

// --- Inventory state & economics (Phase 2) --------------------------------

export async function fetchSettings() {
  return asJson(await fetch(`${BASE}/api/inventory/settings`));
}

export async function updateSettings(patch) {
  return asJson(
    await fetch(`${BASE}/api/inventory/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}

// Patch one product's inventory state (on-hand, on-order, lead time, cost, ...).
export async function updateProductInventory(key, patch) {
  return asJson(
    await fetch(`${BASE}/api/inventory/product/${encodeURIComponent(key)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}

// --- Purchase orders (Phase 2.5) ------------------------------------------
// Each returns the product's refreshed inventory state (on-order, learned lead,
// open POs) so the caller can update that row and recompute the order live.

export async function createPurchaseOrder(productKey, quantity) {
  return asJson(
    await fetch(`${BASE}/api/purchase-orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_key: productKey, quantity }),
    })
  );
}

export async function receivePurchaseOrder(poId, { receivedQty } = {}) {
  return asJson(
    await fetch(`${BASE}/api/purchase-orders/${poId}/receive`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(receivedQty == null ? {} : { received_qty: receivedQty }),
    })
  );
}

export async function cancelPurchaseOrder(poId) {
  return asJson(
    await fetch(`${BASE}/api/purchase-orders/${poId}`, { method: "DELETE" })
  );
}

// --- Decision & outcome ledger (Phase 1) ----------------------------------

// Every recorded forecast run, newest first (with accuracy where reconciled).
export async function fetchLedger() {
  return asJson(await fetch(`${BASE}/api/ledger`));
}

// Per-SKU forecast-vs-outcome detail for one run.
export async function fetchRun(runId) {
  return asJson(await fetch(`${BASE}/api/ledger/${runId}`));
}
