// History: the command audit and the clients currently attached.
//
// The audit is the record of what was asked and what answered; the session list is who is holding a
// command right now. Both are counts of people, not telemetry, so this panel refreshes on demand
// rather than at the state rate.

import { api, clockTime, errorText, esc, fmt } from "../lib.js";

export const history = {
  id: "history",
  label: "History",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Commands</h3>
          <div class="row">
            <label style="margin:0">limit<input id="hi-limit" type="number" min="1" max="200" value="40" style="width:5rem"></label>
            <button id="hi-refresh" class="tiny">Refresh</button>
          </div>
        </div>
        <div id="hi-commands" style="margin-top:.7rem"><div class="empty">loading…</div></div>
      </div>

      <div class="card">
        <h3>Attached clients</h3>
        <div id="hi-sessions"><div class="empty">loading…</div></div>
      </div>

      <div class="card">
        <h3>Pair another device</h3>
        <p class="hint">One code, valid five minutes, works once. Needs <span class="mono">admin</span>, which the device token has and a paired phone does not.</p>
        <button id="hi-pair">Open a pairing window</button>
        <p class="hint mono" id="hi-pair-code"></p>
      </div>`;

    const commands = root.querySelector("#hi-commands");
    const sessions = root.querySelector("#hi-sessions");
    const limit = root.querySelector("#hi-limit");

    function render(payload) {
      const records = payload.commands || [];
      if (!records.length) {
        commands.innerHTML = `<div class="empty">no commands recorded yet</div>`;
      } else {
        const rows = records
          .map((record) => {
            const refused = record.veto || record.refused || (!record.accepted && record.accepted !== undefined);
            return `<tr>
              <td class="mono">${esc(record.at ? clockTime(record.at) : "—")}</td>
              <td>${esc(record.action || record.name || "—")}</td>
              <td>${esc(record.source || "—")}</td>
              <td>${esc(record.principal || record.client || record.by || "—")}</td>
              <td>${refused ? `<span style="color:var(--rose)">${esc(record.veto || "refused")}</span>` : "accepted"}</td>
            </tr>`;
          })
          .join("");
        commands.innerHTML = `<table><thead><tr>
          <th>time</th><th>action</th><th>source</th><th>client</th><th>verdict</th>
        </tr></thead><tbody>${rows}</tbody></table>`;
      }

      const clients = payload.sessions || [];
      if (!clients.length) {
        sessions.innerHTML = `<div class="empty">no client attached</div>`;
        return;
      }
      const rows = clients
        .map(
          (session) => `<tr>
            <td class="mono">${esc(session.name || session.key || "—")}</td>
            <td>${esc((session.scopes || []).join(", ") || "—")}</td>
            <td class="num">${fmt(session.quiet_s, "s")}</td>
            <td>${esc(session.command || "—")}</td>
          </tr>`
        )
        .join("");
      sessions.innerHTML = `<table><thead><tr>
        <th>client</th><th>scopes</th><th class="num">quiet</th><th>command</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
    }

    async function load() {
      const count = Math.max(1, Math.min(200, Number(limit.value) || 40));
      try {
        render(await api(`/history?limit=${count}`));
      } catch (err) {
        commands.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
        sessions.innerHTML = "";
      }
    }

    root.querySelector("#hi-refresh").addEventListener("click", load);

    root.querySelector("#hi-pair").addEventListener("click", async () => {
      const box = root.querySelector("#hi-pair-code");
      box.textContent = "";
      try {
        const payload = await api("/pair/open", { method: "POST", body: JSON.stringify({}) });
        const minutes = Math.round((payload.expires_in_s || 300) / 60);
        box.textContent = `Code ${payload.code} - valid ${minutes} min, single use.`;
      } catch (err) {
        box.textContent = errorText(err);
      }
    });

    load();

    return { update() { /* on demand */ } };
  },
};
