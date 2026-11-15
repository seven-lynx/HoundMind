// Tricks: every action the repertoire reports, grouped by class.
//
// The arm switch is not decoration. `locomotion` changes where the dog is, and a stray click on a
// list of forty buttons is exactly how that happens; `posture` and `expression` do not cross the
// floor, so they run unarmed. The class comes from the server, which reads it from
// `config/actions.jsonc` - the client never decides what kind of thing an action is.

import { api, errorText, esc } from "../lib.js";

const ORDER = ["locomotion", "posture", "expression", "non_motion"];
const NOTE = {
  locomotion: "changes where the dog is — needs the arm switch",
  posture: "changes its shape, not its place",
  expression: "a look or a sound",
  non_motion: "does not move the dog at all",
};

export const tricks = {
  id: "tricks",
  label: "Tricks",

  mount(root) {
    root.innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Actions</h3>
          <label style="display:flex;gap:.4rem;align-items:center;margin:0">
            <input id="tr-arm" type="checkbox" style="width:auto;margin:0">
            arm locomotion
          </label>
        </div>
        <div id="tr-body" style="margin-top:.8rem"><div class="empty">loading the repertoire…</div></div>
      </div>
      <p class="error" id="tr-error" role="alert"></p>`;

    const body = root.querySelector("#tr-body");
    const error = root.querySelector("#tr-error");
    const arm = root.querySelector("#tr-arm");

    async function run(name, actionClass) {
      error.textContent = "";
      if (actionClass === "locomotion" && !arm.checked) {
        error.textContent = "Arm locomotion first - that class moves the dog across the floor.";
        return;
      }
      try {
        await api("/command", {
          method: "POST",
          body: JSON.stringify({
            id: `web-${Date.now()}`,
            action: name,
            // `wait` for the posing classes so the next click cannot stack behind a slow stand-up.
            params: actionClass === "locomotion" ? {} : { wait: true },
            ttl_ms: 300,
          }),
        });
      } catch (err) {
        error.textContent = errorText(err);
      }
    }

    function render(actions) {
      const groups = new Map();
      for (const action of actions) {
        const key = action.class || "unclassified";
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(action);
      }
      const order = [...ORDER, "unclassified"].filter((key) => groups.has(key));

      body.innerHTML = order
        .map((key) => {
          const items = groups.get(key);
          const buttons = items
            .map(
              (action) => `<button class="tiny" data-action="${esc(action.name)}" data-class="${esc(
                action.class || ""
              )}" title="${esc((action.params || []).join(", ") || "no parameters")}">${esc(
                action.name
              )}</button>`
            )
            .join(" ");
          return `<div style="margin-bottom:.8rem">
            <div class="caption" style="font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)">${esc(
              key
            )} · ${items.length}</div>
            <p class="hint" style="margin:.15rem 0 .4rem">${esc(NOTE[key] || "the server has no class for these")}</p>
            <div class="badge-row">${buttons}</div>
          </div>`;
        })
        .join("");

      body.querySelectorAll("button[data-action]").forEach((button) => {
        button.addEventListener("click", () =>
          run(button.dataset.action, button.dataset.class)
        );
      });
    }

    api("/repertoire")
      .then((payload) => {
        const actions = (payload && payload.actions) || [];
        if (!actions.length) {
          body.innerHTML = `<div class="empty">the repertoire is empty: no action is classified and the HAL reports none</div>`;
          return;
        }
        render(actions);
      })
      .catch((err) => {
        body.innerHTML = `<div class="empty">${esc(errorText(err))}</div>`;
      });

    return { update() { /* the repertoire does not change per tick */ } };
  },
};
