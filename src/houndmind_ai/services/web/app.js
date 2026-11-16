// HoundMind web app - entry point.
//
// Responsibilities, in the order they run: decide whether we have a token, open the socket, render
// the chrome (link badge, mode, ticker), build the rail from the panel registry, and route to a
// panel. Everything else lives in `lib.js` (shared core) or `panels/` (one module per panel).
//
// The panel contract is deliberately small: `mount(root)` draws once and returns an object with an
// optional `update(store)`. The app calls `update` on every state frame, but only for the panel on
// screen - thirteen panels re-rendering at 10 Hz is how a browser tab becomes the bottleneck on a
// Pi's WiFi.

import { panels } from "./panels/index.js";
import {
  PANEL_KEY,
  api,
  clockTime,
  currentOrigin,
  esc,
  getDevices,
  getToken,
  normalizeOrigin,
  registerServiceWorker,
  rememberDevice,
  setTheme,
  setToken,
  store,
} from "./lib.js";
import { stopAllMotion } from "./panels/drive.js";

const $ = (id) => document.getElementById(id);

/**
 * Attach a handler, or say why not.
 *
 * The markup and these modules ship together, but a browser can hold an older `index.html` - and the
 * failure then is a `TypeError` at module scope, so *no* handler is attached and every button on the
 * page silently does nothing. From the outside that is indistinguishable from a dead device. A
 * missing id is reported once here, and the boot guard at the bottom of this file says what to do.
 */
const missing = new Set();

function bind(id, event, handler) {
  const node = $(id);
  if (!node) {
    missing.add(id);
    console.warn(`houndmind: #${id} is not in this document - is the page stale?`);
    return;
  }
  node.addEventListener(event, handler);
}

const byId = new Map(panels.map((panel) => [panel.id, panel]));
const mounted = new Map();
let current = null;
let socket = null;
let attempt = 0;
let pingTimer = null;
let reconnectTimer = null;
let lastFrameAt = 0;

// ------------------------------------------------------------------ connect screen

function showConnect(message) {
  $("connect").hidden = false;
  $("shell").hidden = true;
  if (message) $("connect-error").textContent = message;
}

function signOut(message) {
  setToken("");
  teardownSocket();
  showConnect(message || "");
}

bind("token-form", "submit", (event) => {
  event.preventDefault();
  const value = $("token-input").value.trim();
  if (!value) return;
  setToken(value);
  $("connect-error").textContent = "";
  boot();
});

bind("pair-form", "submit", async (event) => {
  event.preventDefault();
  const code = $("code-input").value.trim();
  const client_name = $("name-input").value.trim() || "web";
  $("connect-error").textContent = "";
  try {
    const response = await fetch("/api/v1/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, client_name }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      $("connect-error").textContent =
        (payload && (payload.detail || payload.error)) || `HTTP ${response.status}`;
      return;
    }
    setToken(payload.device_token);
    boot();
  } catch (err) {
    $("connect-error").textContent = `pairing failed: ${err.message}`;
  }
});

bind("sign-out", "click", () => signOut(""));

// ---- theme (#178). `lib.js` applies the stored-or-OS choice at import time; this only keeps the
// button's word in step with what is showing, and flips it.
function renderThemeButton() {
  const button = $("theme-toggle");
  if (!button) return;
  const theme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  button.textContent = theme;
  button.setAttribute("aria-label", `theme: ${theme}; press to switch`);
}

bind("theme-toggle", "click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  setTheme(next);
  renderThemeButton();
});

renderThemeButton();

// ---- safety notifications (#177). A second signal, never the only one: the ticker shows every event
// whether or not the browser allows a notification, and the dog's own stop path is on the device.
// `Notification` needs a secure context, so on plain http the button stays hidden and nothing asks for
// permission.
function notificationSupported() {
  return window.isSecureContext && "Notification" in window;
}

function renderNotifyButton() {
  const button = $("notify-toggle");
  if (!button) return;
  if (!notificationSupported()) {
    // Hiding it is the honest state: the browser would refuse the prompt, and a button that cannot
    // work is worse than no button.
    button.hidden = true;
    return;
  }
  const state = Notification.permission;
  button.hidden = false;
  button.disabled = state === "denied";
  button.textContent =
    state === "granted" ? "notify on" : state === "denied" ? "notify blocked" : "notify off";
  button.title =
    state === "denied"
      ? "this browser has blocked notifications for this site; enable them in its settings"
      : state === "granted"
      ? "desktop notifications are on for safety events"
      : "show a desktop notification for safety events (e-stop, tilt, a veto)";
}

bind("notify-toggle", "click", async () => {
  if (!notificationSupported() || Notification.permission === "granted") return;
  try {
    // Asked for on a click, never on load: a prompt nobody understood is a prompt nobody grants.
    await Notification.requestPermission();
  } catch (err) {
    /* an older browser wants a callback; the label reports whatever it decided */
  }
  renderNotifyButton();
});

function notifySafety(name, data) {
  if (!notificationSupported() || Notification.permission !== "granted") return;
  // Only the events the ticker tints as vetoes: a notification for every routine step would train the
  // user to dismiss the one that mattered.
  if (toneForEvent(name) !== "veto") return;
  const detail = summarize({ name, data });
  try {
    new Notification(`HoundMind: ${name.replace(/_/g, " ")}`, {
      body: detail || "see the event ticker",
      tag: "houndmind-safety",
    });
  } catch (err) {
    /* a refused notification must not take the event path with it */
  }
}

renderNotifyButton();

// ---- devices (#179). The console is served *by* the plane it controls, so a second dog is a second
// origin, and switching is a navigation rather than a cross-origin fetch. That keeps the token where
// it already lives - each origin's own `sessionStorage` - and needs no CORS on either side; in-place
// switching would need CORS and would break on mixed content when only one dog has TLS (#202).
function renderDevicePicker() {
  const picker = $("device-picker");
  if (!picker) return;
  const here = currentOrigin();
  const rows = [{ origin: here, label: "this device" }].concat(getDevices());
  picker.innerHTML =
    rows
      .map(
        (device) =>
          `<option value="${esc(device.origin)}">${esc(
            device.label || device.origin.replace(/^https?:\/\//, "")
          )}</option>`
      )
      .join("") + `<option value="__add">add a device…</option>`;
  picker.value = here;
}

function addDevice() {
  const typed = window.prompt("URL of the other dog's console", "http://");
  renderDevicePicker(); // whatever happens next, the picker must show the truth again
  if (typed === null) return;
  const origin = normalizeOrigin(typed);
  if (!origin) {
    // A rare path, and the message has to be unmissable: an invalid URL would otherwise look like a
    // picker that did nothing.
    window.alert("That is not an http:// or https:// address.");
    return;
  }
  rememberDevice(origin);
  // A full navigation, not a fetch: the other dog's own console and bundle load, and its token field
  // comes with them.
  location.assign(`${origin}/`);
}

bind("device-picker", "change", () => {
  const picker = $("device-picker");
  const value = picker.value;
  if (value === "__add") {
    addDevice();
    return;
  }
  if (!value || value === currentOrigin()) {
    renderDevicePicker();
    return;
  }
  // No `stopAllMotion()` here: leaving the page closes the socket and the server's deadman expires
  // the command. A goodbye fetch would be one more thing to fail on a link that is going away.
  location.assign(`${value}/`);
});

renderDevicePicker();

// ------------------------------------------------------------------ socket

function teardownSocket() {
  stopPing();
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
  if (socket) {
    try { socket.close(); } catch (err) { /* already gone */ }
  }
  socket = null;
  store.set({ health: "offline" }, "socket");
}

function startPing() {
  stopPing();
  // The server drops a command from a client that stopped pinging (its own deadman), so a quiet
  // tab is a stopped dog rather than a dog walking on a stale command.
  pingTimer = setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "ping" }));
    }
  }, 2000);
}

function stopPing() {
  if (pingTimer) clearInterval(pingTimer);
  pingTimer = null;
}

function scheduleReconnect() {
  if (!getToken()) return;
  // Ask the unauthenticated liveness route whether the plane is there at all. "The Pi fell off the
  // WiFi" and "the WebSocket is broken but HTTP answers" look identical from a dead socket, and the
  // operator needs to know which one to walk over and look at.
  api("/health")
    .then(() => store.set({ apiAlive: true }, "probe"))
    .catch(() => store.set({ apiAlive: false }, "probe"));
  attempt += 1;
  const delay = Math.min(15000, 1000 * 2 ** Math.min(attempt - 1, 4));
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, delay);
}

function connect() {
  const token = getToken();
  if (!token) return;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
  if (socket) {
    try { socket.close(); } catch (err) { /* already gone */ }
  }
  store.set({ health: "connecting" }, "socket");

  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/api/v1/events`);

  socket.addEventListener("open", () => {
    attempt = 0;
    // `logs: true` asks for the live log channel (#170). The server grants it only to a token with
    // `admin` - the same scope `GET /api/v1/logs` needs - and says so in `welcome.logs`, so a paired
    // phone keeps its socket and simply has no live log channel.
    socket.send(JSON.stringify({ type: "hello", token, logs: true }));
    startPing();
  });

  socket.addEventListener("message", (message) => {
    let frame = null;
    try { frame = JSON.parse(message.data); } catch (err) { return; }
    if (!frame || typeof frame !== "object") return;

    if (frame.type === "welcome") {
      // The server's first word: who this socket authenticated as, and with which scopes. The app
      // uses it to explain a `403` before making the request that would produce one.
      const data = frame.data || {};
      store.set({ scopes: data.scopes || [], welcome: data }, "socket");
    } else if (frame.type === "log") {
      // Droppable on purpose (#170): the server sends the newest batch and drops older ones rather
      // than closing the socket, so this ring is bounded here too. A client that cannot keep up
      // loses lines, never telemetry.
      const batch = ((frame.data || {}).lines || []).filter((line) => typeof line === "string");
      if (batch.length) {
        store.set({ logLines: (store.logLines || []).concat(batch).slice(-600) }, "log");
      }
    } else if (frame.type === "state") {
      lastFrameAt = Date.now();
      if (store.health !== "live") store.set({ health: "live" }, "socket");
      store.frame(frame.data || {});
    } else if (frame.type === "event") {
      const payload = frame.data || {};
      store.event(payload.name || "event", payload.data || {});
      // A safety event gets a desktop notification when the user asked for one. The ticker has
      // already recorded it either way (#177).
      notifySafety(payload.name || "event", payload.data || {});
    } else if (frame.type === "error") {
      // `unauthorized` means this token is not welcome: asking again will not help.
      if (frame.error === "unauthorized" || frame.error === "bad_token") {
        signOut("Token rejected - paste the device token again.");
      }
    }
  });

  socket.addEventListener("close", () => {
    stopPing();
    if (store.health !== "offline") store.set({ health: "offline" }, "socket");
    scheduleReconnect();
  });

  socket.addEventListener("error", () => { /* close fires next; nothing to add */ });
}

// A tab left open on a dead WiFi must not keep showing the last plausible number.
setInterval(() => {
  if (store.health === "live" && Date.now() - lastFrameAt > 4000) {
    store.set({ health: "stale" }, "socket");
  }
}, 1500);

// ------------------------------------------------------------------ chrome

const HEALTH_LABEL = {
  connecting: "connecting",
  live: "live",
  stale: "no frames",
  offline: "offline",
};

function renderChrome() {
  const badge = $("link-badge");
  if (badge) {
    badge.dataset.link = store.health;
    badge.textContent =
      store.health === "offline" && store.apiAlive ? "no stream" : HEALTH_LABEL[store.health] || store.health;
    badge.title = (store.identity || store.welcome)
      ? `as ${(store.identity || store.welcome).device || "?"} · scopes: ${
          (store.scopes || []).join(", ") || "none"
        }`
      : "";
  }

  const mode = (store.state && store.state.mode) || "—";
  const modeBadge = $("mode-badge");
  if (modeBadge) {
    modeBadge.dataset.mode = mode;
    modeBadge.textContent = `mode ${mode}`;
  }

  const meta = store.meta || {};
  const id = $("device-id");
  if (id && meta.device_id) {
    id.textContent = `${meta.device_id}${meta.profile ? ` · ${meta.profile}` : ""}`;
  }

  const banner = $("banner");
  if (banner) {
    if (store.health === "live") {
      banner.hidden = true;
    } else {
      banner.hidden = false;
      const offline = store.health === "offline";
      banner.dataset.tone = offline ? "bad" : "";
      banner.innerHTML = offline
        ? `<strong>No connection.</strong> The device is not answering${
            store.apiAlive ? " on the telemetry stream, though HTTP does" : ""
          } — every panel below shows its last known state, and nothing you press will reach the dog.`
        : store.health === "stale"
        ? `<strong>Telemetry stopped.</strong> No frames for over 4 seconds — the panels show their last known state while the socket retries.`
        : `<strong>Connecting…</strong> waiting for the device to answer.`;
    }
  }
}

// The ticker is the one place an event is allowed to scroll: it is a log, not a control.
function renderTicker() {
  const list = $("ticker");
  if (!list) return;
  const items = store.events.slice(0, 12).map((entry) => {
    const detail = summarize(entry);
    const tone = toneForEvent(entry.name);
    return `<li data-tone="${tone}" title="${esc(clockTime(entry.at))}">${esc(entry.name)}${
      detail ? ` · ${esc(detail)}` : ""
    }</li>`;
  });
  list.innerHTML = items.join("") || `<li>no events yet</li>`;
}

function summarize(entry) {
  const data = entry.data || {};
  if (entry.name === "command_vetoed") return data.veto || data.detail || "";
  if (entry.name === "command_accepted") return data.action || "";
  if (entry.name === "mode_changed") return data.mode || "";
  if (entry.name === "routine") return data.state || "";
  if (entry.name === "decision") return data.intent || data.state || "";
  if (entry.name === "command_expired") return data.reason || "";
  const keys = Object.keys(data);
  if (!keys.length) return "";
  const first = data[keys[0]];
  return typeof first === "object" ? keys[0] : String(first);
}

function toneForEvent(name) {
  if (["command_vetoed", "command_expired", "safety_action"].includes(name)) return "veto";
  if (["command_accepted", "pairing_window_open"].includes(name)) return "ok";
  return "";
}

// ------------------------------------------------------------------ routing

function renderNav() {
  const nav = $("nav");
  nav.innerHTML = panels
    .map(
      (panel) =>
        `<button class="nav-item" data-panel="${esc(panel.id)}" aria-current="false">
           <span class="dot" aria-hidden="true"></span>${esc(panel.label)}
         </button>`
    )
    .join("");
  nav.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      location.hash = `#${button.dataset.panel}`;
    });
  });
}

function activate(id) {
  const panel = byId.get(id) || panels[0];
  const target = document.querySelector(`.panel[data-panel="${panel.id}"]`);
  if (!target) return;

  document.querySelectorAll(".panel").forEach((section) => {
    section.hidden = section !== target;
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.setAttribute("aria-current", button.dataset.panel === panel.id ? "true" : "false");
  });

  if (!mounted.has(panel.id)) {
    const root = target.querySelector("[data-body]");
    try {
      mounted.set(panel.id, panel.mount(root) || {});
    } catch (err) {
      root.innerHTML = `<div class="empty">This panel failed to start: ${esc(err.message)}</div>`;
      mounted.set(panel.id, {});
    }
  }

  current = panel.id;
  localStorage.setItem(PANEL_KEY, panel.id);
  const entry = mounted.get(panel.id);
  if (entry && typeof entry.update === "function") entry.update(store);
}

function route() {
  const id = (location.hash || "").replace(/^#/, "");
  activate(byId.has(id) ? id : localStorage.getItem(PANEL_KEY) || panels[0].id);
}

window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ keyboard

// Driving by keyboard goes through the same custom event the on-screen pad dispatches, so a key
// press and a button hold cannot drift into two different code paths.
const DRIVE_KEYS = {
  w: "forward",
  s: "backward",
  a: "turn_left",
  d: "turn_right",
  arrowup: "forward",
  arrowdown: "backward",
  arrowleft: "turn_left",
  arrowright: "turn_right",
};

function typing(target) {
  const tag = (target && target.tagName) || "";
  return ["INPUT", "TEXTAREA", "SELECT"].includes(tag) || (target && target.isContentEditable);
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") { closePalette(); return; }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openPalette();
    return;
  }

  if (typing(event.target)) return;

  const key = event.key.toLowerCase();
  if (DRIVE_KEYS[key]) {
    event.preventDefault();
    document.dispatchEvent(new CustomEvent("hm-drive", { detail: DRIVE_KEYS[key] }));
    return;
  }
  if (event.key === " ") {
    event.preventDefault();
    document.dispatchEvent(new CustomEvent("hm-drive", { detail: "stop" }));
    return;
  }
  if (event.key === "?") {
    event.preventDefault();
    openPalette();
    return;
  }
  const index = Number(event.key);
  if (Number.isInteger(index) && index >= 1 && index <= 9 && panels[index - 1]) {
    location.hash = `#${panels[index - 1].id}`;
  }
});

document.addEventListener("keyup", (event) => {
  if (typing(event.target)) return;
  const key = event.key.toLowerCase();
  if (DRIVE_KEYS[key] || event.key === " ") {
    document.dispatchEvent(new CustomEvent("hm-drive-release"));
  }
});

// A hidden tab must not leave a dog walking on a renewed deadman.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopAllMotion();
});

// ------------------------------------------------------------------ palette

function paletteEntries(query) {
  const needle = query.trim().toLowerCase();
  const items = panels.map((panel) => ({
    label: panel.label,
    kind: "panel",
    run: () => { location.hash = `#${panel.id}`; },
  }));
  items.push({ label: "Stop the dog", kind: "action", run: () => stopAllMotion() });
  items.push({ label: "Camera snapshot", kind: "panel", run: () => { location.hash = "#camera"; } });
  if (!needle) return items;
  return items.filter((item) => item.label.toLowerCase().includes(needle));
}

let paletteIndex = 0;
let paletteItems = [];

function openPalette() {
  const box = $("palette");
  box.hidden = false;
  $("palette-input").value = "";
  renderPalette("");
  $("palette-input").focus();
}

function closePalette() {
  $("palette").hidden = true;
}

function renderPalette(query) {
  paletteItems = paletteEntries(query);
  paletteIndex = Math.min(paletteIndex, Math.max(0, paletteItems.length - 1));
  $("palette-list").innerHTML = paletteItems
    .map(
      (item, index) =>
        `<li data-index="${index}" aria-selected="${index === paletteIndex}">${esc(item.label)}
         <span class="kind">${esc(item.kind)}</span></li>`
    )
    .join("") || `<li aria-selected="false">nothing matches</li>`;

  $("palette-list").querySelectorAll("li[data-index]").forEach((row) => {
    row.addEventListener("click", () => runPalette(Number(row.dataset.index)));
  });
}

function runPalette(index) {
  const item = paletteItems[index];
  closePalette();
  if (item) item.run();
}

bind("palette-input", "input", (event) => {
  paletteIndex = 0;
  renderPalette(event.target.value);
});

bind("palette-input", "keydown", (event) => {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    paletteIndex = Math.min(paletteIndex + 1, paletteItems.length - 1);
    renderPalette($("palette-input").value);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    paletteIndex = Math.max(paletteIndex - 1, 0);
    renderPalette($("palette-input").value);
  } else if (event.key === "Enter") {
    event.preventDefault();
    runPalette(paletteIndex);
  }
});

// ------------------------------------------------------------------ boot

function updateActive(source) {
  const entry = mounted.get(current);
  if (entry && typeof entry.update === "function") entry.update(source);
}

store.subscribe((source, reason) => {
  renderChrome();
  if (reason === "event") renderTicker();
  updateActive(source);
});

async function boot() {
  if (!getToken()) {
    showConnect("");
    return;
  }

  // Prove the device answers before leaving the connect screen. A console that appears and then
  // does nothing is the hardest failure to read, and it is exactly what a stale server process
  // produces: the page is already in memory, so it keeps looking alive while every call fails.
  $("connect-error").textContent = "";
  $("connect-hint").textContent = "checking the device…";
  try {
    store.meta = await api("/meta");
  } catch (err) {
    showConnect(errorText(err));
    $("connect-hint").textContent =
      "Paste the device token from ~/.houndmind/api_token, or pair. Nothing is shown until the device answers.";
    return;
  }

  $("connect").hidden = true;
  $("shell").hidden = false;
  // The socket's `welcome` frame reports the scopes, but a tab that opens while the stream is down
  // renders every scoped control as unavailable with no explanation - and the reason is "your token
  // lacks the scope", which is exactly what `/whoami` answers over HTTP (#168). The socket still
  // overwrites it on connect; this only makes the gates honest in the gap.
  try {
    const identity = await api("/whoami");
    store.set({ scopes: identity.scopes || [], identity }, "whoami");
  } catch (err) {
    // A `401` here is "this token is not valid", which the socket reports in its own words.
  }
  renderNav();
  renderChrome();
  renderTicker();
  route();
  connect();
}

// A document without the console is a stale `index.html`, not a broken device - and the person
// looking at it usually has no console open, because the console is the page. Say it in the page.
if (!$("connect") || !$("shell") || !$("token-form")) {
  document.body.innerHTML = `
    <section class="connect">
      <div class="connect-card">
        <p class="eyebrow">HoundMind</p>
        <h1 class="connect-title">This page is out of date</h1>
        <p class="hint">The page the browser loaded does not match the script that came with it, so
        nothing on it can work. Reload with <strong>Ctrl+Shift+R</strong> (Cmd+Shift+R on a Mac).
        The server now sends <span class="mono">Cache-Control: no-cache</span> on this page, so a
        reload is enough from here on.</p>
        <p class="hint mono">missing: ${[...missing].join(", ") || "the connect screen"}</p>
      </div>
    </section>`;
  throw new Error("stale document: the console markup is missing");
}

boot();
// Registered after the boot guard, so a stale document reports itself instead of a worker caching it.
registerServiceWorker();


