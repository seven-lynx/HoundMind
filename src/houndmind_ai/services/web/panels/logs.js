// Logs: the runtime's own JSON lines, filterable, plus the support bundle.
//
// The level and the search box are query parameters, not client-side filters: the server scans back
// through the file for a match, so a filter that matches nothing recent still finds the older line
// (#171). The panel renders record lines only; a traceback's continuation lines have no fields.
//
// `admin` scope, which pairing deliberately does not grant - so a paired phone sees a sentence
// explaining the gap rather than an empty box. The bundle is fetched as a blob because an `<a href>`
// cannot carry the bearer header, and the URL would otherwise carry a credential into history.
//
// The bundle contains `config/settings.jsonc` verbatim, WiFi credentials included. The button says
// so before you press it.

import { api, apiBlob, clockTime, download, errorText, esc, fmt } from "../lib.js";

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
          <h3 style="margin:0">Tail <span id="lg-mode" class="chip">tail</span></h3>
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
    const mode = root.querySelector("#lg-mode");

    let lines = [];
    let truncated = false;
    let live = false;
    let signature = "";
    let searchTimer = null;

    // A filter is a server-side query over the file (#171), so it and the live batch cannot be mixed:
    // the panel shows one or the other, and the chip says which.
    const filtering = () => level.value !== "all" || search.value.trim() !== "";

    function render() {
      mode.textContent = live ? "live" : filtering() ? "filtered" : "tail";
      // No filtering here any more: `?level=` and `?contains=` are answered by the server across its
      // whole scan window, so an empty table means "nothing matched", not "nothing matched in the
      // last 80 lines it happened to fetch" (#171). Records only - a traceback's continuation line
      // has no fields to put in a row.
      const shown = lines
        .map(parse)
        .filter((record) => record)
        .reverse();

      if (!shown.length) {
        list.innerHTML = `<div class="empty">${
          truncated
            ? "no match in the last 4 MiB of the log"
            : live
            ? "waiting for the next line"
            : "no lines match"
        }</div>`;
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
      // A poll is history, not the live channel: the chip has to say so, and the next live batch is
      // free to take the panel back.
      live = false;
      signature = "";
      const count = Math.max(10, Math.min(500, Number(tail.value) || 80));
      const params = new URLSearchParams({ tail: String(count) });
      if (level.value && level.value !== "all") params.set("level", level.value);
      const needle = search.value.trim();
      if (needle) params.set("contains", needle);
      try {
        const payload = await api(`/logs?${params.toString()}`);
        lines = payload.lines || [];
        truncated = Boolean(payload.truncated);
        render();
      } catch (err) {
        lines = [];
        truncated = false;
        list.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }
    }

    level.addEventListener("change", load);
    search.addEventListener("input", () => {
      // A keystroke is not a request: the server does the scanning, so wait for the typing to stop.
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(load, 300);
    });
    tail.addEventListener("change", load);
    root.querySelector("#lg-refresh").addEventListener("click", load);

    root.querySelector("#lg-bundle").addEventListener("click", async () => {
      error.textContent = "";
      try {
        const blob = await apiBlob("/support-bundle");
        download(blob, "houndmind-support.zip");
      } catch (err) {
        error.textContent =
          err.status === 403 ? errorText(err) : `No bundle: ${err.message}`;
      }
    });

    load();

    return {
      update(state) {
        // The live channel (#170), used only while no filter is set: a filtered view is a
        // server-side query, and mixing the two would show unmatched lines under a filter.
        // `signature` keeps a 10 Hz state frame from re-rendering an unchanged table.
        if (filtering()) {
          live = false;
          return;
        }
        const ring = (state && state.logLines) || [];
        const next = ring.length ? `${ring.length}:${ring[ring.length - 1]}` : "";
        if (!next || next === signature) return;
        signature = next;
        lines = ring;
        truncated = false;
        live = true;
        render();
      },
    };
  },
};
