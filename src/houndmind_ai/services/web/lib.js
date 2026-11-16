// Shared core for the HoundMind web app: token handling, the API call, the store the socket
// fills. Formatters and instrument builders live at the bottom of this file.
//
// Why a separate module rather than one big `app.js`: panels import from here, and this module
// must never import a panel - an import cycle between the router and a panel is the kind of bug
// that only shows up as "undefined is not a function". One direction only:
// app.js -> panels -> lib.js.

export const TOKEN_KEY = "houndmind.token";
export const PANEL_KEY = "houndmind.panel";
// Light or dark, remembered across tabs and restarts (#178). The token is per-tab
// (`sessionStorage`); a theme is a preference about the person, not about the session.
export const THEME_KEY = "houndmind.theme";

// The server's deadman. The client renews faster than this, and the gap is the safety margin.
export const TTL_MS = 300;
export const RENEW_MS = 150;

const RING = 120; // 10 Hz x 12 s of history, per series

// ------------------------------------------------------------------ token

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(value) {
  if (value) sessionStorage.setItem(TOKEN_KEY, value);
  else sessionStorage.removeItem(TOKEN_KEY);
}

// ------------------------------------------------------------------ theme

/**
 * The theme to show: the stored choice, or what the OS says (#178).
 *
 * `prefers-color-scheme` is the default rather than a third state - a console with no opinion is one
 * the user has already expressed to their operating system - and the stored value wins over it,
 * because a deliberate switch must survive a change of ambient light.
 */
export function resolveTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch (err) {
    // Storage refused (private mode, or a browser that blocks it): the OS preference still works.
  }
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

/** Set `data-theme` on `<html>`, which is the only thing the stylesheet keys off. */
export function applyTheme(theme) {
  const chosen = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = chosen;
  return chosen;
}

/** Apply and remember. A refused write still applies for this tab. */
export function setTheme(theme) {
  const chosen = applyTheme(theme);
  try {
    localStorage.setItem(THEME_KEY, chosen);
  } catch (err) {
    // Nothing to do: the theme is applied, it just will not outlive the tab.
  }
  return chosen;
}

// At import time, before `app.js` renders: applying a theme after the first paint flashes the wrong
// palette, and on a slow Pi that flash is long enough to read as a bug.
applyTheme(resolveTheme());

// ------------------------------------------------------------------ app shell (#176)

/**
 * Register the service worker, **only in a secure context**.
 *
 * A worker needs `https://` or `localhost`; the device serves plain http on the LAN by default
 * (`settings.api.tls_enabled: false`), so this is a no-op there and the console works exactly as
 * before. `docs/INSTALL.md` documents turning TLS on as the path to an installable console.
 *
 * Failure is swallowed on purpose: a browser that refuses the worker must still get a working console,
 * because the worker is an optimisation and the control plane is not.
 */
export function registerServiceWorker() {
  if (!window.isSecureContext || !("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
    /* no worker: the console still connects, it just cannot load offline */
  });
}

// ------------------------------------------------------------------ api

/**
 * One call shape for every route. Errors carry `status`, `detail` and the parsed body, so a panel
 * can render the server's own explanation instead of inventing one.
 */
export async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/v1${path}`, Object.assign({}, options, { headers }));
  let payload = null;
  const type = response.headers.get("Content-Type") || "";
  if (type.includes("application/json")) {
    try { payload = await response.json(); } catch (err) { payload = null; }
  }
  if (!response.ok) {
    const detail = (payload && (payload.detail || payload.error)) || `HTTP ${response.status}`;
    const error = new Error(detail);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

/** A binary route (the support bundle). Same auth, no JSON. */
export async function apiBlob(path) {
  const token = getToken();
  const response = await fetch(`/api/v1${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.blob();
}

/**
 * A failure as a sentence a person can act on.
 *
 * The mapping is fixed on purpose: `403` is always a scope gap, `503` is always a module that is
 * not running, and neither is ever "Error". A generic message teaches operators to ignore the
 * panel, which is how a real refusal gets missed.
 */
export function errorText(error) {
  const detail = (error && error.message) || "unknown error";
  switch (error && error.status) {
    case 401: return "Token rejected - paste the device token again.";
    case 403: return `This token lacks the scope for that. ${detail}`;
    case 409: return `Refused: ${detail}`;
    case 429: return `Slow down - ${detail}`;
    case 503: return `Not running on the device: ${detail}`;
    default: return detail;
  }
}

// ------------------------------------------------------------------ store

const emptyRings = () => ({
  distance_cm: [],
  tick_ms: [],
  temp_c: [],
  battery_v: [],
  tick_hz_actual: [],
});

export const store = {
  meta: null,
  state: null,
  health: "connecting", // connecting | live | stale | offline
  events: [],
  // Live log lines from the `log` frame class (#170), bounded by the app. Empty means "no live
  // channel" - the Logs panel then falls back to polling `GET /api/v1/logs`.
  logLines: [],
  rings: emptyRings(),
  subs: new Set(),

  subscribe(fn) {
    this.subs.add(fn);
    return () => this.subs.delete(fn);
  },

  emit(reason) {
    for (const fn of this.subs) {
      try { fn(this, reason); } catch (err) { console.error("panel update failed", err); }
    }
  },

  set(patch, reason = "patch") {
    Object.assign(this, patch);
    this.emit(reason);
  },

  /** A `state` frame: replaces the snapshot and appends one sample to each ring. */
  frame(snapshot) {
    this.state = snapshot;
    const sensors = snapshot.sensors || {};
    const health = snapshot.health || {};
    const perf = snapshot.perf || {};
    push(this.rings.distance_cm, sensors.distance_valid ? sensors.distance_cm : null);
    push(this.rings.battery_v, sensors.battery_valid ? sensors.battery_v : null);
    push(this.rings.temp_c, health.temp_c);
    push(this.rings.tick_ms, perf.tick_ms);
    push(this.rings.tick_hz_actual, perf.tick_hz_actual);
    this.emit("state");
  },

  event(name, data) {
    this.events.unshift({ name, data, at: new Date() });
    if (this.events.length > 40) this.events.length = 40;
    this.emit("event");
  },
};

function push(ring, value) {
  ring.push(typeof value === "number" && Number.isFinite(value) ? value : null);
  if (ring.length > RING) ring.shift();
}

// ------------------------------------------------------------------ formatting

/**
 * A measurement, or an em dash.
 *
 * `valid` is the whole point of this function existing: a sensor that did not answer must not
 * render as a plausible zero, and a template string will happily do exactly that.
 */
export function fmt(value, unit, valid = true) {
  if (valid === false || value === null || value === undefined || Number.isNaN(value)) return "—";
  const text = typeof value === "number" ? trim(value) : String(value);
  return unit ? `${text} ${unit}` : text;
}

function trim(value) {
  if (Number.isInteger(value)) return String(value);
  return String(Math.round(value * 100) / 100);
}

export function clockTime(date) {
  const d = date instanceof Date ? date : new Date(date);
  return d.toLocaleTimeString([], { hour12: false });
}

export function elapsed(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 90) return `${minutes} min`;
  return `${Math.round(minutes / 60)} h`;
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

export function el(html) {
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}

/** Error text for a block that failed to load, in the same vocabulary as `errorText`. */
export function failBlock(error) {
  return `<div class="empty">${esc(errorText(error))}</div>`;
}

/** `ok` / `warn` / `bad` from a value against two thresholds, for gauge fills. */
export function toneFor(value, warn, bad, { inverted = false } = {}) {
  if (typeof value !== "number") return "ok";
  if (inverted) {
    if (value <= bad) return "bad";
    if (value <= warn) return "warn";
    return "ok";
  }
  if (value >= bad) return "bad";
  if (value >= warn) return "warn";
  return "ok";
}

// ------------------------------------------------------------------ instruments

/** A sparkline over a ring buffer. Null samples are skipped, not drawn as zero. */
export function spark(values, { height = 34 } = {}) {
  const points = values
    .map((value, index) => ({ value, index }))
    .filter((point) => typeof point.value === "number" && Number.isFinite(point.value));
  if (points.length < 2) {
    return `<svg class="spark" viewBox="0 0 100 30" preserveAspectRatio="none" height="${height}">
      <line x1="0" y1="15" x2="100" y2="15"></line></svg>`;
  }
  const numbers = points.map((point) => point.value);
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);
  const span = max - min || 1;
  const step = values.length > 1 ? 100 / (values.length - 1) : 100;
  const pairs = points
    .map((point) => {
      const x = point.index * step;
      const y = 28 - ((point.value - min) / span) * 26;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return `<svg class="spark" viewBox="0 0 100 30" preserveAspectRatio="none" height="${height}">
    <polyline points="${pairs}"></polyline></svg>`;
}

/** A labelled bar. `tone` comes from `toneFor`, never from a colour guess at the call site. */
export function gauge({ label, value, unit = "", min = 0, max = 100, tone = "ok", text }) {
  const fraction =
    typeof value === "number" ? Math.max(0, Math.min(1, (value - min) / (max - min || 1))) : 0;
  const shown = text !== undefined ? text : fmt(value, unit);
  return `<div class="gauge">
    <div class="value">${esc(shown)}</div>
    <div class="track"><div class="fill ${tone === "ok" ? "" : tone}" style="width:${(
      fraction * 100
    ).toFixed(1)}%"></div></div>
    <div class="caption">${esc(label)}</div>
  </div>`;
}

/** `<dl>` facts block. A null value still renders as a dash rather than disappearing. */
export function facts(pairs) {
  const rows = pairs
    .map(([key, value]) => `<dt>${esc(key)}</dt><dd>${value}</dd>`)
    .join("");
  return `<dl class="kv">${rows}</dl>`;
}

/** True when the token this socket authenticated with holds `scope`. */
export function may(scope) {
  return Array.isArray(store.scopes) && store.scopes.includes(scope);
}

/**
 * Save a blob as a file.
 *
 * The anchor is attached, clicked and removed rather than clicked detached: Firefox treats a
 * detached anchor's href as a path in some configurations, which surfaces as
 * "Content at http://… may not load or link to file:///". It also means the click is a real user
 * gesture on a real element if the browser decides to ask questions.
 */
export function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

