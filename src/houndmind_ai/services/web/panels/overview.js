// Overview: one living subject, the instruments around it, and the sentence that explains the last
// decision. This is the panel a person leaves open.

import { api, errorText, esc, facts, fmt, gauge, spark, toneFor } from "../lib.js";

const DOG = `
<svg viewBox="0 0 220 140" role="img" aria-label="The dog, in its current posture">
  <g class="subject-body">
    <path class="dog-tail" d="M40 60 q-18 -8 -24 -26"></path>
    <rect class="dog-leg rear" x="50" y="86" width="12" height="30" rx="5"></rect>
    <rect class="dog-leg rear" x="68" y="88" width="11" height="26" rx="5"></rect>
    <rect class="dog-leg front" x="150" y="86" width="12" height="30" rx="5"></rect>
    <rect class="dog-leg front" x="132" y="88" width="11" height="26" rx="5"></rect>
    <ellipse class="dog-body" cx="106" cy="72" rx="62" ry="26"></ellipse>
    <circle class="dog-collar" cx="158" cy="64" r="11"></circle>
    <path class="dog-head" d="M158 60 q22 -8 36 -3 q11 4 9 13 q-2 10 -15 11 q-17 1 -30 -7 z"></path>
    <path class="dog-head" d="M166 42 l7 -15 q2 -5 6 -2 l2 17 z"></path>
    <circle class="dog-eye" cx="188" cy="60" r="2.6"></circle>
  </g>
</svg>`;

/**
 * What the dog is doing, derived from what the server already publishes.
 *
 * This is a reading, not an authority: `since_s` is how long the current command has been live and
 * `last_command` is the action that won the tick. A posture the runtime has no word for stays
 * "standing by" rather than being guessed at.
 */
function stance(snapshot) {
  const actuators = snapshot.actuators || {};
  const action = actuators.last_command;
  const since = actuators.since_s;
  const mode = snapshot.mode;
  if (since !== null && since !== undefined && since < 2.5) {
    if (["forward", "backward", "turn_left", "turn_right", "trot"].includes(action)) {
      return { label: `moving · ${action}`, cls: "walking" };
    }
    if (["sit", "half_sit"].includes(action)) return { label: "sitting", cls: "sitting" };
    if (action === "lie" || action === "doze off") return { label: "lying", cls: "lying" };
  }
  if (mode === "rest") return { label: "resting", cls: "resting" };
  if (mode === "patrol") return { label: "patrolling", cls: "" };
  return { label: "standing by", cls: "" };
}

function whyLine(snapshot) {
  const actuators = snapshot.actuators || {};
  const decision = snapshot.decision || null;
  if (actuators.vetoed) {
    return { tone: "veto", text: `${actuators.veto || "refused"} — the dog did not do it, see Decisions` };
  }
  if (decision && decision.intent) {
    const confidence =
      typeof decision.confidence === "number" ? ` (${Math.round(decision.confidence * 100)}%)` : "";
    return { tone: "", text: `${decision.intent}${confidence} from ${decision.source || "unknown"}` };
  }
  if (actuators.last_command) return { tone: "", text: `holding ${actuators.last_command}` };
  return { tone: "", text: "nothing has asked the dog to move yet" };
}

export const overview = {
  id: "overview",
  label: "Overview",

  mount(root) {
    root.innerHTML = `
      <div class="grid two">
        <div class="card">
          <h3>Subject</h3>
          <div class="subject" id="ov-subject">${DOG}<span class="stance-label" id="ov-stance">no telemetry</span></div>
        </div>
        <div class="card">
          <h3>Instruments</h3>
          <div class="grid instruments" id="ov-gauges"></div>
          <div id="ov-sparks" style="margin-top:.9rem"></div>
        </div>
      </div>
      <div class="why" id="ov-why" data-tone="">
        <span class="kicker">why</span><span id="ov-why-text">waiting for the first frame…</span>
      </div>
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">Head sweep</h3>
          <span class="chip" id="ov-scan-mode">no scan</span>
        </div>
        <svg id="ov-radar" viewBox="-110 -108 220 118" role="img"
          aria-label="The last head sweep, drawn as a polar plot with the nose at the top"></svg>
        <p class="hint" id="ov-scan-note"></p>
      </div>
      <div class="grid two">
        <div class="card"><h3>Body</h3><div id="ov-body"></div></div>
        <div class="card"><h3>Runtime</h3><div id="ov-runtime"></div></div>
      </div>`;

    const subject = root.querySelector("#ov-subject");
    const stanceLabel = root.querySelector("#ov-stance");
    const gauges = root.querySelector("#ov-gauges");
    const sparks = root.querySelector("#ov-sparks");
    const why = root.querySelector("#ov-why");
    const whyText = root.querySelector("#ov-why-text");
    const body = root.querySelector("#ov-body");
    const runtime = root.querySelector("#ov-runtime");
    const radar = root.querySelector("#ov-radar");
    const scanMode = root.querySelector("#ov-scan-mode");
    const scanNote = root.querySelector("#ov-scan-note");

    // The snapshot carries `scan` as a summary (#169): mode, timestamp and a sample count. The
    // bearings are a separate read, fetched only when that timestamp moves - a sweep is up to 181
    // numbers, and the snapshot arrives at the state rate.
    let scanStamp = null;

    function polar(scan) {
      const range = 200;
      const rings = [50, 100, 150, 200]
        .map(
          (cm) =>
            `<circle r="${((cm / range) * 100).toFixed(0)}" fill="none" stroke="var(--line-2)" stroke-width="1"/>`
        )
        .join("");
      const dots = Object.entries(scan.angles || {})
        .filter(([, cm]) => Number.isFinite(Number(cm)))
        .map(([yaw, cm]) => {
          // A compass bearing, with the nose up: yaw 0 is straight ahead, yaw 90 is to the right.
          const angle = (Number(yaw) * Math.PI) / 180;
          const radius = (Math.min(Math.max(Number(cm), 0), range) / range) * 100;
          const x = Math.sin(angle) * radius;
          const y = -Math.cos(angle) * radius;
          return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.4" fill="var(--amber)"/>`;
        })
        .join("");
      return `${rings}<line x1="0" y1="0" x2="0" y2="-100" stroke="var(--line-2)"/>${dots}`;
    }

    async function refreshScan(stamp) {
      if (stamp === scanStamp) return;
      scanStamp = stamp;
      try {
        const payload = await api("/scan");
        const scan = payload.scan;
        if (!scan) {
          scanMode.textContent = "no scan";
          radar.innerHTML = "";
          scanNote.textContent = "";
          return;
        }
        if (scan.mode === "sweep" && scan.angles) {
          const count = Object.keys(scan.angles).length;
          scanMode.textContent = `${count} bearing${count === 1 ? "" : "s"}`;
          radar.innerHTML = polar(scan);
          scanNote.textContent = "rings at 50, 100, 150 and 200 cm; the nose points up";
        } else {
          // A three-way scan has no angles to plot, so the numbers are shown as measured rather
          // than placed at an angle the server never reported.
          scanMode.textContent = scan.mode;
          radar.innerHTML = "";
          scanNote.textContent = `forward ${fmt(scan.forward, "cm")} · right ${fmt(
            scan.right,
            "cm"
          )} · left ${fmt(scan.left, "cm")}`;
        }
      } catch (err) {
        radar.innerHTML = "";
        scanNote.textContent = errorText(err);
      }
    }

    return {
      update(source) {
        const snapshot = source.state;
        if (!snapshot) {
          stanceLabel.textContent = "no telemetry";
          return;
        }

        const sensors = snapshot.sensors || {};
        const health = snapshot.health || {};
        const perf = snapshot.perf || {};
        const safety = snapshot.safety || {};
        const supervisor = snapshot.supervisor || {};
        const counts = snapshot.modules || {};
        const nav = snapshot.nav || {};

        // Re-fetch the bearings only when the scan changed; the summary in the snapshot exists so a
        // 10 Hz telemetry stream does not carry a 181-number sweep (#169).
        const scan = snapshot.scan;
        if (scan && typeof scan.timestamp === "number") {
          refreshScan(scan.timestamp);
        } else if (scanStamp !== null) {
          scanStamp = null;
          scanMode.textContent = "no scan";
          radar.innerHTML = "";
          scanNote.textContent = "";
        }

        const look = stance(snapshot);
        subject.className = `subject ${look.cls}`;
        stanceLabel.textContent = look.label;

        gauges.innerHTML = [
          gauge({
            label: "sonar",
            value: sensors.distance_valid ? sensors.distance_cm : null,
            unit: "cm",
            min: 0,
            max: 200,
            tone: toneFor(sensors.distance_valid ? sensors.distance_cm : null, 30, 12, {
              inverted: true,
            }),
          }),
          gauge({
            label: "battery",
            value: sensors.battery_valid ? sensors.battery_v : null,
            unit: "V",
            min: 6.0,
            max: 8.4,
            tone: toneFor(sensors.battery_valid ? sensors.battery_v : null, 7.0, 6.6, {
              inverted: true,
            }),
          }),
          gauge({
            label: "temperature",
            value: health.temp_c,
            unit: "°C",
            min: 30,
            max: 85,
            tone: toneFor(health.temp_c, 65, 78),
          }),
          gauge({
            label: "loop",
            value: perf.tick_hz_actual,
            unit: "Hz",
            min: 0,
            max: perf.tick_hz_target || 10,
            tone: toneFor(perf.tick_overrun_ms, 1, 10),
          }),
        ].join("");

        sparks.innerHTML = `
          <div class="gauge"><div class="caption">sonar, 12 s</div>${spark(source.rings.distance_cm)}</div>
          <div class="gauge" style="margin-top:.5rem"><div class="caption">tick, ms</div>${spark(source.rings.tick_ms)}</div>`;

        const reason = whyLine(snapshot);
        why.dataset.tone = reason.tone;
        whyText.textContent = reason.text;

        body.innerHTML = facts([
          ["mode", esc(snapshot.mode || "—")],
          ["touch", esc(sensors.touch_valid ? sensors.touch : "—")],
          [
            "sound",
            sensors.sound_valid
              ? sensors.sound_detected
                ? `heard (${esc(sensors.sound_direction || "?")})`
                : "quiet"
              : "—",
          ],
          [
            "pitch / roll",
            `${fmt(sensors.pitch_deg, "°", sensors.imu_valid)} / ${fmt(
              sensors.roll_deg,
              "°",
              sensors.imu_valid
            )}`,
          ],
          ["heading", nav.heading_calibrated ? "gyro-corrected" : "not calibrated"],
          ["safety", safety.active ? "active" : "off"],
          ["e-stop", safety.emergency_stop ? "SET" : "clear"],
          [
            "supervisor",
            supervisor.holding
              ? `holding (${esc(supervisor.reason || "no reason given")})`
              : "not holding",
          ],
        ]);

        runtime.innerHTML = facts([
          [
            "modules",
            `${counts.loaded ?? "—"} loaded · ${counts.disabled ?? "—"} disabled · ${
              counts.failed ?? "—"
            } failed`,
          ],
          ["tick", `${fmt(perf.tick_ms, "ms")} (target ${fmt(perf.tick_hz_target, "Hz")})`],
          ["cpu", fmt(health.cpu_pct, "%")],
          ["memory", fmt(health.mem_used_pct, "%")],
          [
            "health",
            health.status === "degraded"
              ? `degraded: ${esc((health.reasons || []).join(", ") || "no reason given")}`
              : esc(health.status || "—"),
          ],
          ["trace", `<span class="mono">${esc(snapshot.trace_id || "—")}</span>`],
        ]);
      },
    };
  },
};

