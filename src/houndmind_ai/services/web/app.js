// HoundMind web app — vanilla JS, no build step (D12).
//
// Everything here is a view of `/api/v1`. The app makes no safety decisions: the server answers
// 409 with a reason and this shows it. The one rule it must not soften is the validity flags —
// a sensor with `*_valid: false` renders "—", never a number.

const TOKEN_KEY = "houndmind.token";
const TTL_MS = 300;          // the deadman the device enforces
const RENEW_MS = 200;        // how often a held button re-issues it
const PING_MS = 2000;

let token = sessionStorage.getItem(TOKEN_KEY) || "";
let socket = null;
let pingTimer = null;
let renewTimer = null;
let held = null;

const $ = (id) => document.getElementById(id);

function setLink(text, cls) {
  const el = $("link");
  el.textContent = text;
  el.className = "badge" + (cls ? " " + cls : "");
}

function showError(message) {
  $("veto").textContent = message || "";
}

function fmt(value, unit, valid) {
  // `valid` is mandatory: a missing measurement is "—", not a plausible zero.
  if (valid === false || value === null || value === undefined) return "—";
  return unit ? `${value} ${unit}` : String(value);
}

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/v1${path}`, Object.assign({}, options, { headers }));
  let payload = null;
  try { payload = await response.json(); } catch (err) { payload = null; }
  if (!response.ok) {
    const detail = (payload && (payload.detail || payload.error)) || `HTTP ${response.status}`;
    const error = new Error(detail);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

// ---------------------------------------------------------------- auth

function applyAuthState() {
  const authed = Boolean(token);
  $("auth").classList.toggle("hidden", authed);
  $("app").classList.toggle("hidden", !authed);
  if (authed) connect();
}

$("token-save").addEventListener("click", () => {
  const value = $("token-input").value.trim();
  if (!value) return;
  token = value;
  sessionStorage.setItem(TOKEN_KEY, token);
  $("auth-error").textContent = "";
  applyAuthState();
});

$("pair").addEventListener("click", async () => {
  const code = $("code-input").value.trim();
  const client_name = $("name-input").value.trim() || "web";
  $("auth-error").textContent = "";
  try {
    const response = await fetch("/api/v1/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, client_name }),
    });
    const payload = await response.json();
    if (!response.ok) {
      $("auth-error").textContent = payload.detail || payload.error || "pairing failed";
      return;
    }
    token = payload.device_token;
    sessionStorage.setItem(TOKEN_KEY, token);
    applyAuthState();
  } catch (err) {
    $("auth-error").textContent = "pairing failed: " + err.message;
  }
});

// ---------------------------------------------------------------- websocket

function connect() {
  if (socket) { try { socket.close(); } catch (err) { /* already gone */ } }
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/api/v1/events`);

  socket.addEventListener("open", () => {
    setLink("authenticating");
    socket.send(JSON.stringify({ type: "hello", token }));
  });

  socket.addEventListener("message", (event) => {
    let frame;
    try { frame = JSON.parse(event.data); } catch (err) { return; }
    if (frame.type === "welcome") {
      setLink("live", "ok");
      startPing();
      loadCamera();
    } else if (frame.type === "state") {
      render(frame.data);
    } else if (frame.type === "event") {
      pushEvent(frame.data);
      if (frame.data.name === "mode_changed") renderMode(frame.data.data.mode);
    } else if (frame.type === "error") {
      if (frame.error === "unauthorized" || frame.error === "forbidden") {
        token = "";
        sessionStorage.removeItem(TOKEN_KEY);
        setLink("signed out", "bad");
        stopAll();
        applyAuthState();
      } else {
        pushEvent({ name: frame.error, data: frame.detail || {}, ts: Date.now() / 1000 });
      }
    }
  });

  socket.addEventListener("close", () => {
    setLink("offline", "bad");
    stopPing();
    stopHold();
    // Fixed backoff: the server is on the same LAN, so a long wait would just be unresponsive.
    setTimeout(() => { if (token) connect(); }, 2000);
  });

  socket.addEventListener("error", () => setLink("error", "bad"));
}

function startPing() {
  stopPing();
  // The device stops a client's command after `link_loss_s` without a ping; this is the
  // app-side half of that deadman.
  pingTimer = setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "ping" }));
    }
  }, PING_MS);
}

function stopPing() {
  if (pingTimer) clearInterval(pingTimer);
  pingTimer = null;
}

// ---------------------------------------------------------------- rendering

function render(state) {
  const sensors = state.sensors || {};
  $("t-distance").textContent = fmt(
    sensors.distance_cm === null ? null : Number(sensors.distance_cm).toFixed(1),
    "cm",
    sensors.distance_valid,
  );
  $("t-touch").textContent = sensors.touch_valid ? sensors.touch : "—";
  $("t-tilt").textContent = sensors.imu_valid
    ? `pitch ${Number(sensors.pitch_deg).toFixed(1)}° / roll ${Number(sensors.roll_deg).toFixed(1)}°`
    : "—";
  $("t-battery").textContent = sensors.battery_valid
    ? `${Number(sensors.battery_v).toFixed(2)} V`
    : "—";
  const health = state.health || {};
  $("t-temp").textContent = health.temp_c === null || health.temp_c === undefined
    ? "—"
    : `${Number(health.temp_c).toFixed(1)} °C`;
  const perf = state.perf || {};
  $("t-loop").textContent =
    perf.tick_hz_actual === null || perf.tick_hz_actual === undefined
      ? "—"
      : `${Number(perf.tick_hz_actual).toFixed(1)} Hz / ${Number(perf.tick_ms).toFixed(0)} ms`;

  const actuators = state.actuators || {};
  $("t-command").textContent = actuators.last_command
    ? `${actuators.last_command}${actuators.vetoed ? " (vetoed)" : ""}`
    : "—";
  if (actuators.tilt_latched) showError("Tilt latched. Right the dog, then clear it on the device.");
  renderMode(state.mode);
}

function renderMode(mode) {
  $("mode-badge").textContent = `mode: ${mode || "—"}`;
  if (mode) $("mode").value = mode;
}

function pushEvent(event) {
  const list = $("events");
  const item = document.createElement("li");
  const when = new Date().toLocaleTimeString();
  const detail = event.data && Object.keys(event.data).length
    ? " " + JSON.stringify(event.data)
    : "";
  item.textContent = `${when}  ${event.name}${detail}`;
  list.prepend(item);
  while (list.children.length > 60) list.removeChild(list.lastChild);
}

// ---------------------------------------------------------------- driving

async function issue(action) {
  try {
    await api("/command", {
      method: "POST",
      body: JSON.stringify({
        id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())).slice(0, 12),
        action,
        params: {},
        ttl_ms: TTL_MS,
        source: "client",
      }),
    });
    showError("");
  } catch (err) {
    showError(err.message);
  }
}

async function stop() {
  try {
    await api("/stop", { method: "POST", body: JSON.stringify({}) });
    showError("");
  } catch (err) {
    showError(err.message);
  }
}

function startHold(action, button) {
  stopHold();
  if (action === "stop") { stop(); return; }
  held = action;
  button.classList.add("active");
  issue(action);
  renewTimer = setInterval(() => issue(action), RENEW_MS);
}

function stopHold() {
  if (renewTimer) clearInterval(renewTimer);
  renewTimer = null;
  held = null;
  document.querySelectorAll(".pad.active").forEach((el) => el.classList.remove("active"));
}

function stopAll() {
  stopHold();
  stopPing();
  if (socket) { try { socket.close(); } catch (err) { /* already gone */ } }
  socket = null;
}

document.querySelectorAll(".pad").forEach((button) => {
  const action = button.dataset.action;
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    startHold(action, button);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((name) => {
    button.addEventListener(name, () => {
      if (!held) return;
      stopHold();
      // One explicit stop on release, so the deadman is a backstop rather than the mechanism.
      stop();
    });
  });
});

// A hidden tab must not leave the dog walking.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { stopHold(); stop(); }
});

$("mode").addEventListener("change", async (event) => {
  try {
    await api("/mode", { method: "POST", body: JSON.stringify({ mode: event.target.value }) });
    showError("");
  } catch (err) {
    showError(err.message);
  }
});

// ---------------------------------------------------------------- pairing

$("pair-open").addEventListener("click", async () => {
  try {
    const payload = await api("/pair/open", { method: "POST", body: JSON.stringify({}) });
    const minutes = Math.round((payload.expires_in_s || 300) / 60);
    $("pair-code").textContent = `Code ${payload.code} — valid ${minutes} min, single use.`;
  } catch (err) {
    $("pair-code").textContent = err.message;
  }
});

// ---------------------------------------------------------------- camera

function loadCamera() {
  const img = $("camera");
  img.addEventListener("error", () => {
    img.classList.add("hidden");
    $("camera-note").textContent =
      "No camera stream. Enable a vision module on the device to see frames here.";
  });
  // A ticket, not the token: the stream URL lands in history and access logs, and the token is the
  // credential for everything else (see #18).
  api("/camera/ticket", { method: "POST", body: JSON.stringify({}) })
    .then((payload) => {
      img.src = `/api/v1/camera/stream?ticket=${encodeURIComponent(payload.ticket)}`;
      img.classList.remove("hidden");
    })
    .catch((err) => {
      $("camera-note").textContent = err.message;
    });
}

applyAuthState();