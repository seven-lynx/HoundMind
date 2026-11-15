// Logs: the runtime's own JSON lines, filterable, plus the support bundle.
//
// `admin` scope, which pairing deliberately does not grant - so a paired phone sees a sentence
// explaining the gap rather than an empty box. The bundle is fetched as a blob because an `<a href>`
// cannot carry the bearer header, and the URL would otherwise carry a credential into history.
//
// The bundle contains `config/settings.jsonc` verbatim, WiFi credentials included. The button says
// so before you press it.

import { api, apiBlob, clockTime, errorText, esc, fmt } from "../lib.js";

const LEVELS = ["all", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

function parse(line) {
  try {
    return JSON.parse(line);
  } catch (err) {
    return null;
  }
}

export const logs = {
  id: "logs",
  label: "Logs",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Tail</h3>
          <div class="row">
            <label style="margin:0">lines<input id="lg-tail" type="number" min="10" max="500" value="80" style="width:5.5rem"></label>
            <label style="margin:0">level<select id="lg-level">${LEVELS.map(
              (level) => `<option value="${level}">${level.toLowerCase()}</option>`
            ).join("")}</select></label>
            <label style="margin:0">search<input id="lg-search" placeholder="substring" style="width:9rem"></label>
            <button id="lg-refresh" class="tiny">Refresh</button>
          </div>
        </div>
        <div id="lg-list" style="margin-top:.7rem"><div class="empty">loading…</div></div>
      </div>
      <div class="card">
        <h3>Support bundle</h3>
        <p class="hint">Logs, <span class="mono">config/settings.jsonc</span> and run metadata, zipped. The config is included verbatim - it can contain your WiFi password. Check it before sharing.</p>
        <button id="lg-bundle">Download bundle</button>
        <p class="error" id="lg-error" role="alert"></p>
      </div>`;

    const list = root.querySelector("#lg-list");
    const error = root.querySelector("#lg-error");
    const tail = root.querySelector("#lg-tail");
    const level = root.querySelector("#lg-level");
    const search = root.querySelector("#lg-search");

    let lines = [];

    function render() {
      const wanted = level.value;
      const needle = search.value.trim().toLowerCase();
      const shown = lines
        .map(parse)
        .filter((record) => record)
        .filter((record) => (wanted === "all" ? true : String(record.level || "").toUpperCase() === wanted))
        .filter((record) => {
          if (!needle) return true;
          return JSON.stringify(record).toLowerCase().includes(needle);
        })
        .slice()
        .reverse();

      if (!shown.length) {
        list.innerHTML = `<div class="empty">no lines match</div>`;
        return;
      }
      const rows = shown
        .map(
          (record) => `<tr>
            <td class="mono">${esc(record.timestamp ? clockTime(record.timestamp) : "—")}</td>
            <td><span class="chip" style="border-color:${
              String(record.level).startsWith("ERROR") || String(record.level) === "CRITICAL"
                ? "var(--rose)"
                : String(record.level) === "WARNING"
                ? "var(--amber)"
                : "var(--line-2)"
            }">${esc(record.level || "—")}</span></td>
            <td class="mono">${esc((record.logger || "").split(".").pop() || "—")}</td>
            <td>${esc(record.message || "")}${record.trace_id ? `<br><span class="mono">trace ${esc(record.trace_id)}</span>` : ""}</td>
          </tr>`
        )
        .join("");
      list.innerHTML = `<table><thead><tr>
        <th>time</th><th>level</th><th>logger</th><th>message</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
    }

    async function load() {
      error.textContent = "";
      const count = Math.max(10, Math.min(500, Number(tail.value) || 80));
      try {
        const payload = await api(`/logs?tail=${count}`);
        lines = payload.lines || [];
        render();
      } catch (err) {
        lines = [];
        list.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }
    }

    level.addEventListener("change", render);
    search.addEventListener("input", render);
    tail.addEventListener("change", load);
    root.querySelector("#lg-refresh").addEventListener("click", load);

    root.querySelector("#lg-bundle").addEventListener("click", async () => {
      error.textContent = "";
      try {
        const blob = await apiBlob("/support-bundle");
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "houndmind-support.zip";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      } catch (err) {
        error.textContent =
          err.status === 403 ? errorText(err) : `No bundle: ${err.message}`;
      }
    });

    load();

    return {
      update() { /* logs are pulled on demand; the state rate is not a log rate */ },
    };
  },
};
