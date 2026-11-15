// People: who the dog has been taught. `admin` scope only, because an enrolled face is biometric.
//
// The route answers 200 with `identity.enabled: false` when the feature is off, which is a fact
// worth drawing: `people: []` alone would read as "nobody is enrolled". A paired phone gets a 403
// here and the panel says why instead of looking broken.

import { api, errorText, esc, fmt } from "../lib.js";

export const people = {
  id: "people",
  label: "People",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Roster</h3>
          <button id="pp-refresh" class="tiny">Refresh</button>
        </div>
        <div id="pp-identity" class="hint"></div>
        <div id="pp-list" style="margin-top:.6rem"><div class="empty">loading…</div></div>
        <p class="error" id="pp-error" role="alert"></p>
      </div>

      <div class="card">
        <h3>Teach a face</h3>
        <form id="pp-form" class="row grow">
          <label>name<input id="pp-name" required maxlength="32" placeholder="name"></label>
          <button type="submit" class="primary">Enrol</button>
        </form>
        <p class="hint">One face in frame. The request is accepted (202) and the roster reports the outcome.</p>
      </div>`;

    const list = root.querySelector("#pp-list");
    const identity = root.querySelector("#pp-identity");
    const error = root.querySelector("#pp-error");
    const form = root.querySelector("#pp-form");

    function render(payload) {
      const block = payload.identity || {};
      identity.textContent = block.enabled
        ? `identity running · backend ${block.backend || "unknown"}`
        : `identity off · ${block.reason || "not enabled on this device"}`;
      const roster = payload.people || [];
      if (!roster.length) {
        list.innerHTML = `<div class="empty">${
          block.enabled ? "nobody enrolled yet" : "enrolling needs the identity module enabled"
        }</div>`;
        return;
      }
      const rows = roster
        .map((person) => {
          const id = String(person.id || person.name || "");
          return `<tr>
            <td><strong>${esc(person.name || id)}</strong><br><span class="mono">${esc(id)}</span></td>
            <td>${esc(person.added || person.created || "—")}</td>
            <td class="num"><button class="tiny danger" data-del="${esc(id)}">Forget</button></td>
          </tr>`;
        })
        .join("");
      list.innerHTML = `<table><thead><tr><th>person</th><th>added</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table>`;
      list.querySelectorAll("button[data-del]").forEach((button) => {
        button.addEventListener("click", () => forget(button.dataset.del));
      });
    }

    async function load() {
      error.textContent = "";
      try {
        render(await api("/people"));
      } catch (err) {
        identity.textContent = "";
        list.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }
    }

    async function forget(id) {
      error.textContent = "";
      try {
        await api(`/people/${encodeURIComponent(id)}`, { method: "DELETE" });
        await load();
      } catch (err) {
        error.textContent = errorText(err);
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      const name = root.querySelector("#pp-name").value.trim();
      if (!name) return;
      try {
        const accepted = await api("/people", {
          method: "POST",
          body: JSON.stringify({ name }),
        });
        root.querySelector("#pp-name").value = "";
        identity.textContent = `enrolling ${accepted.name || name} · ${accepted.status || "pending"}`;
        setTimeout(load, 1500);
      } catch (err) {
        error.textContent = errorText(err);
      }
    });

    root.querySelector("#pp-refresh").addEventListener("click", load);
    load();

    return { update() { /* enrolment is async; the panel polls after a write */ } };
  },
};
