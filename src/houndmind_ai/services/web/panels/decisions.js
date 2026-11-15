// Decisions: one record per tick - what won, who asked, and what refused it.
//
// This is the panel that answers "why did it do that" without opening a log file. The ring buffer
// is filled by the decision logger; when that module is off the route answers 503, and "the feed is
// off" is a different fact from "the dog has not decided yet" - the panel keeps them apart.

import { api, errorText, esc, fmt } from "../lib.js";

function vetoText(record) {
  const vetoes = record.vetoes || record.refusals || [];
  if (!Array.isArray(vetoes) || !vetoes.length) return "";
  return vetoes
    .map((veto) => `${veto.action || veto.name || "?"} refused: ${veto.reason || "?"}`)
    .join("; ");
}

export const decisions = {
  id: "decisions",
  label: "Decisions",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Feed</h3>
          <div class="row">
            <label style="margin:0">limit<input id="dc-limit" type="number" min="1" max="200" value="40" style="width:5rem"></label>
            <button id="dc-refresh" class="tiny">Refresh</button>
          </div>
        </div>
        <div id="dc-list" style="margin-top:.7rem"><div class="empty">loading…</div></div>
      </div>`;

    const list = root.querySelector("#dc-list");
    const limit = root.querySelector("#dc-limit");

    function render(payload) {
      const records = payload.decisions || [];
      if (!records.length) {
        list.innerHTML = `<div class="empty">no decisions recorded yet</div>`;
        return;
      }
      const rows = records
        .slice()
        .reverse()
        .map((record) => {
          const vetoes = vetoText(record);
          return `<tr>
            <td class="mono">${esc(record.ts !== undefined ? fmt(record.ts) : "—")}</td>
            <td>${esc(record.intent || record.action || "—")}</td>
            <td>${esc(record.source || "—")}</td>
            <td class="num">${fmt(record.confidence)}</td>
            <td>${vetoes ? `<span style="color:var(--rose)">${esc(vetoes)}</span>` : "—"}</td>
          </tr>`;
        })
        .join("");
      list.innerHTML = `<table><thead><tr>
        <th>ts</th><th>intent</th><th>source</th><th class="num">conf</th><th>refused by</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
    }

    async function load() {
      const count = Math.max(1, Math.min(200, Number(limit.value) || 40));
      try {
        render(await api(`/decisions?limit=${count}`));
      } catch (err) {
        list.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }
    }

    root.querySelector("#dc-refresh").addEventListener("click", load);
    load();
    const timer = setInterval(() => {
      if (!document.hidden && !root.closest(".panel").hidden) load();
    }, 3000);

    return { update() { /* the feed polls itself */ }, destroy() { clearInterval(timer); } };
  },
};
