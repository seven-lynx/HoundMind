// Modules: every component, what it costs per tick, and why it is not running.
//
// `disabled` is normal and expected (vision ships off); `failed` is a bug. The table keeps them
// visually distinct because a screen where both are grey is a screen where the one that matters is
// invisible. `tick_ms` comes from `GET /modules`; `/state` carries only the counts.

import { api, errorText, esc, fmt } from "../lib.js";

export const modules = {
  id: "modules",
  label: "Modules",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Components</h3>
          <div class="row">
            <span class="chip" id="md-counts">—</span>
            <button id="md-refresh" class="tiny">Refresh</button>
          </div>
        </div>
        <div id="md-list" style="margin-top:.7rem"><div class="empty">loading…</div></div>
        <p class="hint"><span class="mono">tick_ms</span> is the per-tick cost of that module. Rising values are a performance question, not a hardware fault.</p>
      </div>`;

    const list = root.querySelector("#md-list");
    const counts = root.querySelector("#md-counts");

    function render(payload) {
      const items = payload.modules || [];
      const summary = payload.counts || {};
      counts.textContent = `${summary.loaded ?? "—"} loaded · ${summary.disabled ?? "—"} disabled · ${
        summary.failed ?? "—"
      } failed`;
      if (!items.length) {
        list.innerHTML = `<div class="empty">no modules reported — is the runtime ticking?</div>`;
        return;
      }
      const rows = items
        .map(
          (module) => `<tr>
            <td class="mono">${esc(module.name)}</td>
            <td><span class="chip" style="border-color:${
              module.state === "failed" ? "var(--rose)" : module.state === "ok" ? "var(--teal)" : "var(--line-2)"
            }">${esc(module.state || "—")}</span></td>
            <td class="num">${fmt(module.tick_ms, "ms")}</td>
            <td>${esc(module.detail || "—")}</td>
          </tr>`
        )
        .join("");
      list.innerHTML = `<table><thead><tr>
        <th>module</th><th>state</th><th class="num">tick</th><th>reason</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
    }

    async function load() {
      try {
        render(await api("/modules"));
      } catch (err) {
        list.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }
    }

    root.querySelector("#md-refresh").addEventListener("click", load);
    load();
    const timer = setInterval(() => {
      if (!document.hidden && !root.closest(".panel").hidden) load();
    }, 4000);

    return {
      update(source) {
        const counts_ = (source.state && source.state.modules) || {};
        if (counts_.loaded !== undefined) {
          counts.textContent = `${counts_.loaded} loaded · ${counts_.disabled} disabled · ${counts_.failed} failed`;
        }
      },
      destroy() { clearInterval(timer); },
    };
  },
};
