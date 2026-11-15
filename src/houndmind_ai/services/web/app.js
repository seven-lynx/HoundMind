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
import { PANEL_KEY, api, clockTime, esc, getToken, setToken, store } from "./lib.js";
import { stopAllMotion } from "./panels/drive.js";

const $ = (id) => document.getElementById(id);

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

$("token-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = $("token-input").value.trim();
  if (!value) return;
  setToken(value);
  $("connect-error").textContent = "";
  boot();
});

$("pair-form").addEventListener("submit", async (event) => {
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

$("sign-out").addEventListener("click", () => signOut(""));

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
    socket.send(JSON.stringify({ type: "hello", token }));
    startPing();
  });

  socket.addEventListener("message", (message) => {
    let frame = null;
    try { frame = JSON.parse(message.data); } catch (err) { return; }
    if (!frame || typeof frame !== "object") return;

    if (frame.type === "state") {
      lastFrameAt = Date.now();
      if (store.health !== "live") store.set({ health: "live" }, "socket");
      store.frame(frame.data || {});
    } else if (frame.type === "event") {
      const payload = frame.data || {};
      store.event(payload.name || "event", payload.data || {});
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

$("palette-input").addEventListener("input", (event) => {
  paletteIndex = 0;
  renderPalette(event.target.value);
});

$("palette-input").addEventListener("keydown", (event) => {
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
  $("connect").hidden = true;
  $("shell").hidden = false;
  renderNav();
  renderChrome();
  renderTicker();
  route();
  connect();

  try {
    // `/meta` is the only unauthenticated route with device facts in it; without it the console
    // still works, so a failure here costs a label and nothing else.
    store.meta = await api("/meta");
    renderChrome();
  } catch (err) {
    /* the connection badge already reports whether the plane answers */
  }
}

boot();


