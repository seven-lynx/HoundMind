// Routines: the scripts the runner loaded at boot, with dry-run, refusals and the live step.
//
// The list comes from `GET /routines`, which reads the runner's report rather than the directory -
// two readers of one directory are two answers to "which routines exist", and the dog can only
// play the ones it actually loaded. A refused file is shown, not hidden: a routine that silently
// does not exist is the failure mode this panel is meant to end.

import { api, errorText, esc, fmt } from "../lib.js";

function steps(routine) {
  if (Array.isArray(routine.steps)) return routine.steps.length;
  return null;
}

function refusals(block) {
  const entries = Object.entries(block || {});
  if (!entries.length) return "";
  const rows = entries
    .map(([file, problems]) => {
      const text = (problems || [])
        .map((problem) => (problem && problem.message) || String(problem))
        .join("; ");
      return `<tr><td class="mono">${esc(file)}</td><td>${esc(text)}</td></tr>`;
    })
    .join("");
  return `<div class="card"><h3>Refused files</h3>
    <table><tbody>${rows}</tbody></table>
    <p class="hint">These files are on the device and were not loaded. Fix them and restart the runtime.</p>
  </div>`;
}

export const routines = {
  id: "routines",
  label: "Routines",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Loaded</h3>
          <div class="row">
            <button id="rt-refresh" class="tiny">Refresh</button>
            <button id="rt-stop" class="tiny danger">Stop the run</button>
          </div>
        </div>
        <div id="rt-list" style="margin-top:.7rem"><div class="empty">loading…</div></div>
        <p class="hint" id="rt-dir"></p>
        <p class="error" id="rt-error" role="alert"></p>
      </div>
      <div id="rt-refusals"></div>
      <div class="card"><h3>In progress</h3><div id="rt-current"><div class="empty">nothing is running</div></div></div>`;

    const list = root.querySelector("#rt-list");
    const dir = root.querySelector("#rt-dir");
    const error = root.querySelector("#rt-error");
    const refusalsBox = root.querySelector("#rt-refusals");
    const current = root.querySelector("#rt-current");
    const stopButton = root.querySelector("#rt-stop");

    async function start(id, dry) {
      error.textContent = "";
      try {
        await api(`/routines/${encodeURIComponent(id)}/run`, {
          method: "POST",
          body: JSON.stringify({ dry_run: Boolean(dry) }),
        });
        await load();
      } catch (err) {
        error.textContent = errorText(err);
      }
    }

    function render(payload) {
      const items = payload.routines || [];
      dir.textContent = payload.directory ? `from ${payload.directory}` : "";
      if (!items.length) {
        list.innerHTML = `<div class="empty">no routines loaded — add a JSON file to the routines directory</div>`;
      } else {
        const rows = items
          .map((routine) => {
            const id = String(routine.id || routine.name || "");
            const count = steps(routine);
            return `<tr>
              <td><strong>${esc(routine.name || id)}</strong><br><span class="mono">${esc(id)}</span></td>
              <td class="num">${count === null ? "—" : count}</td>
              <td class="num">
                <button class="tiny primary" data-run="${esc(id)}">Run</button>
                <button class="tiny" data-dry="${esc(id)}">Dry run</button>
              </td>
            </tr>`;
          })
          .join("");
        list.innerHTML = `<table><thead><tr><th>routine</th><th class="num">steps</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
        list.querySelectorAll("button[data-run]").forEach((button) => {
          button.addEventListener("click", () => start(button.dataset.run, false));
        });
        list.querySelectorAll("button[data-dry]").forEach((button) => {
          button.addEventListener("click", () => start(button.dataset.dry, true));
        });
      }
      refusalsBox.innerHTML = refusals(payload.refusals);
    }

    async function load() {
      try {
        render(await api("/routines"));
      } catch (err) {
        list.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }
    }

    stopButton.addEventListener("click", async () => {
      try {
        await api("/stop", { method: "POST", body: JSON.stringify({}) });
      } catch (err) {
        error.textContent = errorText(err);
      }
    });
    root.querySelector("#rt-refresh").addEventListener("click", load);

    load();
    const timer = setInterval(() => {
      if (!document.hidden && !root.closest(".panel").hidden) load();
    }, 6000);

    return {
      update(source) {
        const run = source.state && source.state.routines;
        if (!run) {
          current.innerHTML = `<div class="empty">nothing is running</div>`;
          stopButton.disabled = true;
          return;
        }
        stopButton.disabled = false;
        current.innerHTML = `<table><tbody>
          <tr><td>routine</td><td class="mono">${esc(run.id || "—")}</td></tr>
          <tr><td>state</td><td>${esc(run.state || "—")}</td></tr>
          <tr><td>step</td><td class="num">${fmt(run.index)}</td></tr>
          <tr><td>action</td><td>${esc(run.action || "—")}</td></tr>
          <tr><td>detail</td><td>${esc(run.detail || run.veto || "—")}</td></tr>
          <tr><td>dry run</td><td>${run.dry_run ? "yes" : "no"}</td></tr>
        </tbody></table>`;
      },
      destroy() { clearInterval(timer); },
    };
  },
};
