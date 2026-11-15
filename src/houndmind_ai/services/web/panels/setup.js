// Config and Calibration: the two panels that read settings rather than telemetry.
//
// Config shows the redacted document and edits only what the server says is live. A redacted leaf
// is never offered as an input: sending "***" back would overwrite a real secret with three stars.
// The answer to a PATCH carries `persisted: false`, and the panel says so out loud - the change dies
// with the process.
//
// Calibration is read-only by contract (`api.py::_calibration`). The request names are discovered
// from the route's own 400 body instead of being hardcoded here, because a second copy of that
// allow-list is a copy that drifts.

import { api, errorText, esc, fmt } from "../lib.js";

function leafValue(config, dotted) {
  let node = config;
  for (const part of dotted.split(".")) {
    if (!node || typeof node !== "object") return undefined;
    node = node[part];
  }
  return node;
}

function control(dotted, value) {
  if (typeof value === "boolean") {
    return `<label style="display:inline-flex;gap:.4rem;align-items:center">
      <input type="checkbox" data-key="${esc(dotted)}" ${value ? "checked" : ""} style="width:auto;margin:0">
      ${value ? "true" : "false"}
    </label>`;
  }
  if (typeof value === "number") {
    return `<input type="number" step="any" data-key="${esc(dotted)}" value="${value}" style="max-width:9rem">`;
  }
  return `<input data-key="${esc(dotted)}" value="${esc(value ?? "")}" style="max-width:16rem">`;
}

export const config = {
  id: "config",
  label: "Config",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Live keys</h3>
          <button id="cf-refresh" class="tiny">Refresh</button>
        </div>
        <div id="cf-live" style="margin-top:.7rem"><div class="empty">loading…</div></div>
        <div class="row" style="margin-top:.7rem"><button id="cf-apply" class="primary">Apply changes</button></div>
        <p class="hint" id="cf-note"></p>
        <p class="error" id="cf-error" role="alert"></p>
      </div>

      <div class="card">
        <h3>Redacted document</h3>
        <p class="hint">Secrets are masked by the server. This is a view, not an editor.</p>
        <pre class="mono" id="cf-raw" style="max-height:22rem;overflow:auto;background:#0c1218;border:1px solid var(--line);border-radius:8px;padding:.7rem"></pre>
      </div>`;

    const live = root.querySelector("#cf-live");
    const raw = root.querySelector("#cf-raw");
    const note = root.querySelector("#cf-note");
    const error = root.querySelector("#cf-error");

    function render(payload) {
      const document_ = payload.config || {};
      const keys = payload.live_keys || [];
      raw.textContent = JSON.stringify(document_, null, 2);
      if (!keys.length) {
        live.innerHTML = `<div class="empty">this build lists no live keys</div>`;
        return;
      }
      const rows = keys
        .map((key) => {
          const value = leafValue(document_, key);
          return `<tr><td class="mono">${esc(key)}</td><td>${control(key, value)}</td></tr>`;
        })
        .join("");
      live.innerHTML = `<table><thead><tr><th>key</th><th>value</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    async function load() {
      error.textContent = "";
      try {
        render(await api("/config"));
      } catch (err) {
        live.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }
    }

    root.querySelector("#cf-refresh").addEventListener("click", load);

    root.querySelector("#cf-apply").addEventListener("click", async () => {
      error.textContent = "";
      note.textContent = "";
      const patch = {};
      live.querySelectorAll("[data-key]").forEach((input) => {
        const key = input.dataset.key;
        if (input.type === "checkbox") patch[key] = input.checked;
        else if (input.type === "number") {
          const value = Number(input.value);
          if (Number.isFinite(value)) patch[key] = value;
        } else patch[key] = input.value;
      });
      if (!Object.keys(patch).length) {
        error.textContent = "Nothing to apply.";
        return;
      }
      try {
        const result = await api("/config", { method: "PATCH", body: JSON.stringify(patch) });
        const applied = Object.keys(result.applied || {}).length;
        note.textContent = `Applied ${applied} key(s). ${
          result.persisted ? "" : "This lives in this process only - a restart reloads settings.jsonc."
        }`;
        await load();
      } catch (err) {
        error.textContent = errorText(err);
        const invalid = (err.payload && err.payload.invalid) || [];
        const rejected = (err.payload && err.payload.rejected) || [];
        const parts = invalid.map((entry) => {
          const text = (entry.problems || [])
            .map((problem) => `${problem.path}: ${problem.message}`)
            .join("; ");
          return `${entry.key} - ${text}`;
        });
        if (rejected.length) parts.push(`cannot change live: ${rejected.join(", ")}`);
        if (parts.length) note.textContent = parts.join(" | ");
      }
    });

    load();
    return { update() { /* settings change on request, not per tick */ } };
  },
};

export const calibration = {
  id: "calibration",
  label: "Calibration",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <h3>Servo trim</h3>
        <div id="cb-offsets"><div class="empty">loading…</div></div>
        <p class="hint" id="cb-note"></p>
      </div>

      <div class="card">
        <h3>Read-only probes</h3>
        <p class="hint">These requests read. Nothing here writes an offset or asks the dog to move.</p>
        <div id="cb-requests" class="badge-row"><div class="empty">asking which probes exist…</div></div>
        <pre class="mono" id="cb-result" style="margin-top:.8rem;background:#0c1218;border:1px solid var(--line);border-radius:8px;padding:.7rem;max-height:16rem;overflow:auto"></pre>
        <p class="error" id="cb-error" role="alert"></p>
      </div>`;

    const offsets = root.querySelector("#cb-offsets");
    const note = root.querySelector("#cb-note");
    const requests = root.querySelector("#cb-requests");
    const result = root.querySelector("#cb-result");
    const error = root.querySelector("#cb-error");

    async function run(name) {
      error.textContent = "";
      result.textContent = "running…";
      try {
        const payload = await api("/calibration/run", {
          method: "POST",
          body: JSON.stringify({ request: name }),
        });
        result.textContent = JSON.stringify(payload.result || payload, null, 2);
      } catch (err) {
        error.textContent = errorText(err);
        result.textContent = "";
      }
    }

    function renderRequests(names) {
      if (!Array.isArray(names) || !names.length) {
        requests.innerHTML = `<div class="empty">this build exposes no calibration requests</div>`;
        return;
      }
      requests.innerHTML = names
        .map((name) => `<button class="tiny" data-request="${esc(name)}">${esc(name)}</button>`)
        .join(" ");
      requests.querySelectorAll("button[data-request]").forEach((button) => {
        button.addEventListener("click", () => run(button.dataset.request));
      });
    }

    async function load() {
      try {
        const payload = await api("/calibration");
        const entries = Object.entries(payload.servo_zero_offsets || {});
        offsets.innerHTML = entries.length
          ? `<table><thead><tr><th>servo</th><th class="num">offset</th></tr></thead><tbody>${entries
              .map(
                ([name, value]) =>
                  `<tr><td class="mono">${esc(name)}</td><td class="num">${fmt(value)}</td></tr>`
              )
              .join("")}</tbody></table>`
          : `<div class="empty">no offsets stored on this device</div>`;
        note.textContent = `${payload.detail || ""}${
          payload.auto_apply ? " · applied automatically at start" : " · not applied automatically"
        }`;
      } catch (err) {
        offsets.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }

      try {
        // A deliberately unknown name. The route refuses it before anything is written and answers
        // with the list it does accept, so the UI never keeps a second copy of the allow-list.
        await api("/calibration/run", {
          method: "POST",
          body: JSON.stringify({ request: "__discover__" }),
        });
        requests.innerHTML = `<div class="empty">the probe list did not answer as expected</div>`;
      } catch (err) {
        renderRequests(err.payload && err.payload.requests);
      }
    }

    load();
    return { update() { /* nothing per tick */ } };
  },
};


