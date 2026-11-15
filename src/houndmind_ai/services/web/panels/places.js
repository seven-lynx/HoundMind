// Places: a taught position is a heading plus a distance from an anchor.
//
// `at_anchor` is a checkbox and not a hidden default: it decides whether a walk across the room is
// allowed to start, and the server refuses it as a string precisely because "false" is truthy. The
// panel sends a real boolean and shows the refusal when the navigator disagrees.

import { api, errorText, esc, fmt } from "../lib.js";

function problems(list) {
  if (!Array.isArray(list) || !list.length) return "";
  return list
    .map((problem) => `<li>${esc(problem.message || problem.path || String(problem))}</li>`)
    .join("");
}

export const places = {
  id: "places",
  label: "Places",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Catalogue</h3>
          <button id="pl-refresh" class="tiny">Refresh</button>
        </div>
        <div id="pl-list" style="margin-top:.7rem"><div class="empty">loading…</div></div>
        <p class="hint" id="pl-path"></p>
        <p class="error" id="pl-error" role="alert"></p>
      </div>

      <div class="card">
        <h3>Teach a place</h3>
        <form id="pl-form" class="row grow">
          <label>name<input id="pl-name" required maxlength="32" placeholder="kitchen"></label>
          <label>heading °<input id="pl-heading" type="number" step="1" value="0"></label>
          <label>distance cm<input id="pl-distance" type="number" step="1" value="100"></label>
          <label>anchor<input id="pl-anchor" placeholder="optional" maxlength="32"></label>
          <label>confidence<input id="pl-confidence" type="number" step="0.05" min="0" max="1" placeholder="optional"></label>
          <button type="submit" class="primary">Add</button>
        </form>
        <div id="pl-problems"></div>
      </div>

      <div class="card"><h3>Walk in progress</h3><div id="pl-goal"><div class="empty">nothing in flight</div></div></div>`;

    const list = root.querySelector("#pl-list");
    const path = root.querySelector("#pl-path");
    const error = root.querySelector("#pl-error");
    const form = root.querySelector("#pl-form");
    const problemsBox = root.querySelector("#pl-problems");
    const goalBox = root.querySelector("#pl-goal");

    function render(payload) {
      path.textContent = payload.path ? `from ${payload.path}` : "";
      const items = payload.places || [];
      if (!items.length) {
        list.innerHTML = `<div class="empty">no places taught yet</div>`;
      } else {
        const rows = items
          .map((place) => {
            const id = String(place.id || place.name || "");
            return `<tr>
              <td><strong>${esc(place.name || id)}</strong><br><span class="mono">${esc(id)}</span></td>
              <td class="num">${fmt(place.heading_deg, "°")}</td>
              <td class="num">${fmt(place.distance_cm, "cm")}</td>
              <td>${esc(place.anchor || "—")}</td>
              <td class="num">${fmt(place.confidence)}</td>
              <td class="num">
                <button class="tiny primary" data-go="${esc(id)}">Go</button>
                <button class="tiny" data-rename="${esc(id)}" data-name="${esc(place.name || id)}">Rename</button>
                <button class="tiny danger" data-del="${esc(id)}">Forget</button>
              </td>
            </tr>`;
          })
          .join("");
        list.innerHTML = `<table><thead><tr>
          <th>place</th><th class="num">heading</th><th class="num">distance</th>
          <th>anchor</th><th class="num">conf</th><th></th>
        </tr></thead><tbody>${rows}</tbody></table>
        <p class="hint"><label style="display:inline-flex;gap:.4rem;align-items:center">
          <input id="pl-at-anchor" type="checkbox" style="width:auto;margin:0"> the dog is at the anchor
        </label></p>`;

        list.querySelectorAll("button[data-go]").forEach((button) => {
          button.addEventListener("click", () => go(button.dataset.go));
        });
        list.querySelectorAll("button[data-del]").forEach((button) => {
          button.addEventListener("click", () => forget(button.dataset.del));
        });
        list.querySelectorAll("button[data-rename]").forEach((button) => {
          button.addEventListener("click", () =>
            rename(button.dataset.rename, button.dataset.name)
          );
        });
      }
      problemsBox.innerHTML =
        Array.isArray(payload.refusals) && payload.refusals.length
          ? `<ul class="hint">${problems(payload.refusals)}</ul>`
          : "";
    }

    async function load() {
      try {
        render(await api("/places"));
      } catch (err) {
        list.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      }
    }

    async function go(id) {
      error.textContent = "";
      const atAnchor = root.querySelector("#pl-at-anchor");
      try {
        await api(`/places/${encodeURIComponent(id)}/go`, {
          method: "POST",
          body: JSON.stringify({ at_anchor: Boolean(atAnchor && atAnchor.checked) }),
        });
      } catch (err) {
        error.textContent = errorText(err);
      }
    }

    async function forget(id) {
      error.textContent = "";
      try {
        await api(`/places/${encodeURIComponent(id)}`, { method: "DELETE" });
        await load();
      } catch (err) {
        error.textContent = errorText(err);
      }
    }

    async function rename(id, current) {
      error.textContent = "";
      // One field, one edit: the browser's own dialog is a smaller surface than a second form that
      // would duplicate the create form and still only send a name. Cancelling it edits nothing.
      const name = window.prompt(`Rename ${id}`, current || "");
      if (name === null) return;
      const trimmed = name.trim();
      if (!trimmed || trimmed === current) return;
      try {
        await api(`/places/${encodeURIComponent(id)}`, {
          method: "PATCH",
          body: JSON.stringify({ name: trimmed }),
        });
        await load();
      } catch (err) {
        error.textContent = errorText(err);
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      problemsBox.innerHTML = "";
      const body = {
        name: root.querySelector("#pl-name").value.trim(),
        heading_deg: Number(root.querySelector("#pl-heading").value),
        distance_cm: Number(root.querySelector("#pl-distance").value),
      };
      const anchor = root.querySelector("#pl-anchor").value.trim();
      if (anchor) body.anchor = anchor;
      const confidence = root.querySelector("#pl-confidence").value.trim();
      if (confidence !== "") body.confidence = Number(confidence);
      try {
        await api("/places", { method: "POST", body: JSON.stringify(body) });
        form.reset();
        root.querySelector("#pl-heading").value = "0";
        root.querySelector("#pl-distance").value = "100";
        await load();
      } catch (err) {
        error.textContent = errorText(err);
        const found = err.payload && err.payload.problems;
        if (Array.isArray(found)) problemsBox.innerHTML = `<ul class="hint">${problems(found)}</ul>`;
      }
    });

    root.querySelector("#pl-refresh").addEventListener("click", load);

    load();
    const timer = setInterval(() => {
      if (!document.hidden && !root.closest(".panel").hidden) load();
    }, 8000);

    return {
      update(source) {
        const nav = (source.state && source.state.nav) || {};
        const goal = nav.goal;
        if (!goal) {
          goalBox.innerHTML = `<div class="empty">nothing in flight</div>`;
          return;
        }
        goalBox.innerHTML = `<table><tbody>
          <tr><td>state</td><td>${esc(goal.state || "—")}</td></tr>
          <tr><td>place</td><td class="mono">${esc(goal.name || goal.id || "—")}</td></tr>
          <tr><td>detail</td><td>${esc(goal.detail || "—")}</td></tr>
        </tbody></table>`;
      },
      destroy() { clearInterval(timer); },
    };
  },
};

