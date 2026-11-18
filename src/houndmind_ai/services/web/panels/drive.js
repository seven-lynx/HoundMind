// Drive: hold to move, release to stop. The panel issues commands and renders the server's answer;
// it never decides whether the dog should move.
//
// Two paths, and the difference matters:
//   - the pad renews a bare command every RENEW_MS, well inside the server's 300 ms deadman. This
//     is the vendor's fire-and-forget queue, the shape the app already shipped with.
//   - "one step" issues a single supervised step with an explicit speed, which the HAL runs
//     synchronously. That is the path the distance bench needs: one step, one measurement, no
//     queue behind it.

import { RENEW_MS, TTL_MS, api, errorText, esc } from "../lib.js";

const MODES = {
  idle: "autonomy on: the behaviour and navigator may drive",
  manual: "a hand on the wheel: clients may drive, autonomy may not",
  patrol: "the navigator roams on its own",
  rest: "parked: only stop and the watchdog get through",
};

// The select shows the intent, not the vocabulary (#334). "idle" is a word an operator has to
// learn; "autonomy on" is the decision they are making - and `rest` -> `idle` is a single change
// that hands a parked dog back to self-driving, so it has to read as one.
const MODE_LABELS = {
  idle: "idle - autonomy on",
  manual: "manual - you drive",
  patrol: "patrol - roams",
  rest: "rest - parked",
};

let renewTimer = null;
let held = null;

function rid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID().slice(0, 12);
  return String(Date.now()).slice(-12);
}

async function issue(action, params = {}) {
  return api("/command", {
    method: "POST",
    body: JSON.stringify({ id: rid(), action, params, ttl_ms: TTL_MS }),
  });
}

/** Stop from anywhere - the palette, the keyboard, a hidden tab. Parks the dog, and never fails
 *  loudly: `POST /stop` sets the runtime to `rest`, which is the only mode autonomy cannot drive
 *  in, so a panic press is not overwritten on the next tick (#333). */
export async function stopAllMotion() {
  try {
    await api("/stop", { method: "POST", body: JSON.stringify({}) });
  } catch (err) {
    /* a stop that cannot reach the device is the connection badge's job to report */
  }
}

/** Stop the motion in flight without parking: a pad release, not a panic press.
 *
 * A `stop` command is the escape hatch the gateway accepts in any mode (act/gateway.py::_vet), so
 * this is the same deadman stop the pad's own buttons get - and it leaves the mode alone, which is
 * what makes hold-and-release driving possible while `POST /stop` means parked. */
export async function stopMotion() {
  try {
    await issue("stop");
  } catch (err) {
    /* the deadman expires the last command if even this never arrives */
  }
}

/** Hand the runtime a mode. Labels are intent, the mode name is the wire value (#334). */
export async function setMode(mode) {
  return api("/mode", { method: "POST", body: JSON.stringify({ mode }) });
}

function stopHold() {
  if (renewTimer) clearInterval(renewTimer);
  renewTimer = null;
  held = null;
  document.querySelectorAll(".pad.active").forEach((button) => button.classList.remove("active"));
}

export const drive = {
  id: "drive",
  label: "Drive",

  mount(root) {
    root.innerHTML = `
      <div class="grid two">
        <div class="card">
          <h3>Pad</h3>
          <div class="dpad">
            <button class="pad up" data-action="forward" aria-label="forward">▲</button>
            <button class="pad left" data-action="turn_left" aria-label="turn left">◀</button>
            <button class="pad stop" data-action="stop" aria-label="stop">STOP</button>
            <button class="pad right" data-action="turn_right" aria-label="turn right">▶</button>
            <button class="pad down" data-action="backward" aria-label="backward">▼</button>
          </div>
          <p class="hint">Hold to walk; release, hide the tab, or lose the link and it stops. Keyboard: WASD or arrows, space to stop.</p>
          <p class="error" id="drive-error" role="alert"></p>
        </div>

        <div class="card">
          <h3>Mode</h3>
          <label for="drive-mode">What may drive</label>
          <select id="drive-mode">
            ${Object.keys(MODES).map((mode) => `<option value="${mode}">${esc(MODE_LABELS[mode] || mode)}</option>`).join("")}
          </select>
          <p class="hint" id="drive-mode-hint">${esc(MODES.idle)}</p>
          <p class="hint">STOP parks the dog: it sets <span class="mono">rest</span>, the one mode
          autonomy cannot drive in. Pick a mode here to let it drive again.</p>

          <h3 style="margin-top:1.1rem">One step</h3>
          <div class="row grow">
            <label>speed
              <input id="drive-speed" type="range" min="60" max="200" step="10" value="120">
            </label>
            <label>steps
              <input id="drive-steps" type="number" min="1" max="5" step="1" value="1">
            </label>
          </div>
          <p class="hint">Speed <span id="drive-speed-value">120</span>. One supervised step at a time - the control the bench measures with.</p>
          <div class="row" style="margin-top:.5rem">
            <button id="drive-step-forward">Step forward</button>
            <button id="drive-step-backward">Step back</button>
          </div>
          <p class="error" id="drive-step-error" role="alert"></p>
        </div>
      </div>`;

    const error = root.querySelector("#drive-error");
    const stepError = root.querySelector("#drive-step-error");
    const modeSelect = root.querySelector("#drive-mode");
    const modeHint = root.querySelector("#drive-mode-hint");
    const speedInput = root.querySelector("#drive-speed");
    const speedValue = root.querySelector("#drive-speed-value");
    const stepsInput = root.querySelector("#drive-steps");

    function startHold(action, button) {
      stopHold();
      if (action === "stop") {
        stopMotion();
        return;
      }
      held = action;
      button.classList.add("active");
      issue(action).catch((err) => { error.textContent = errorText(err); });
      renewTimer = setInterval(() => {
        issue(action).catch((err) => {
          error.textContent = errorText(err);
          stopHold();
        });
      }, RENEW_MS);
    }

    function release() {
      if (!held) return;
      stopHold();
      // A stop on release, so the deadman is the backstop and not the mechanism. It is a stop
      // *command*, not `POST /stop`: releasing a key must not park the dog, or driving by hold
      // would be one press and a mode change to resume.
      stopMotion();
    }

    root.querySelectorAll(".pad").forEach((button) => {
      const action = button.dataset.action;
      button.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        startHold(action, button);
      });
      ["pointerup", "pointerleave", "pointercancel"].forEach((name) => {
        button.addEventListener(name, release);
      });
    });

    document.addEventListener("hm-drive", (event) => {
      const button = root.querySelector(`.pad[data-action="${event.detail}"]`);
      if (button) startHold(event.detail, button);
    });
    document.addEventListener("hm-drive-release", release);

    modeSelect.addEventListener("change", async () => {
      modeHint.textContent = MODES[modeSelect.value] || "";
      try {
        await setMode(modeSelect.value);
      } catch (err) {
        error.textContent = errorText(err);
      }
    });

    speedInput.addEventListener("input", () => { speedValue.textContent = speedInput.value; });

    async function nudge(action) {
      stepError.textContent = "";
      const speed = Number(speedInput.value) || 120;
      const steps = Math.max(1, Math.min(5, Number(stepsInput.value) || 1));
      try {
        await issue(action, { speed, steps, wait: true });
      } catch (err) {
        stepError.textContent = errorText(err);
      }
    }
    root.querySelector("#drive-step-forward").addEventListener("click", () => nudge("forward"));
    root.querySelector("#drive-step-backward").addEventListener("click", () => nudge("backward"));

    let seenMode = null;

    return {
      update(source) {
        const snapshot = source.state;
        if (!snapshot) return;
        if (snapshot.mode && snapshot.mode !== seenMode) {
          seenMode = snapshot.mode;
          modeSelect.value = snapshot.mode;
          modeHint.textContent = MODES[snapshot.mode] || "";
        }
        const actuators = snapshot.actuators || {};
        if (actuators.tilt_latched) {
          error.textContent = "Tilt latched: put the dog upright, then clear it from the device.";
        } else if (actuators.vetoed) {
          error.textContent = `Refused: ${actuators.veto || "vetoed"}`;
        }
      },
    };
  },
};

