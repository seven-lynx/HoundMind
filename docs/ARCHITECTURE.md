# HoundMind Architecture

Status: **target design** — being implemented on `refactor/resurrection`.
Companion: `docs/CONTROL_API.md` (the wire contract), `.houndmind-local/docs/plans/houndmind-resurrection.md` (phases).

This document describes where the code is going and why. Where it contradicts the legacy
tree, the legacy tree is wrong.

---

## 1. Layers

```
  ┌──────────────┐   ┌───────────────┐
  │  Web app     │   │ Android app   │        clients: no logic, no safety decisions
  │ (served by   │   │ (Kotlin/      │
  │  the dog)    │   │  Compose)     │
  └──────┬───────┘   └───────┬───────┘
         └─────── v1 REST + WS ───────┘
                            │
         ┌──────────────────▼─────────────────────┐
         │  services/   control plane             │
         │  api · auth · stream · camera · sessions│
         └──────────────────┬─────────────────────┘
                            │ typed Command / Event
  ┌─────────────────────────▼──────────────────────────────────┐
  │  kernel/   state · registry · scheduler · supervisor       │
  │  behaviour FSMs · navigation · mapping  (pure, testable)   │
  └─────────────────────────┬──────────────────────────────────┘
                            │ Command (desired motion)
  ┌─────────────────────────▼──────────────────────────────────┐
  │  act/   actuator gateway  +  MANDATORY INTERLOCK           │
  └─────────────────────────┬──────────────────────────────────┘
                            │ hal iface (Protocol)
  ┌──────────────┬──────────┴──────────┬──────────────────────┐
  │ PidogAdapter │     PidogAdapter    │   FakeAdapter        │
  │  (Pi 4)      │      (Pi 5)         │  (CI + tests)        │
  └──────────────┴─────────────────────┴──────────────────────┘
```

**Dependency rule (enforced by review, later by import-linter):**

`services` → `kernel` → `act` → `hal`. Never the reverse. Vendor imports (`pidog`,
`robot_hat`, `picamera2`, `vilib`) appear **only** in `hal/` and `optional/`. A vendor
import anywhere else is a defect: it breaks `pip install` on a workstation and in CI.

---

## 2. Package layout

```
src/houndmind_ai/
  kernel/     state.py  commands.py  intents.py  registry.py  scheduler.py  supervisor.py
  hal/        iface.py  fake.py  vendor.py  module.py  sensors.py  motors.py
  act/        gateway.py  interlock.py  calibration.py
  nav/        mapping.py  scanning.py  avoidance.py  planner.py
  behaviour/  fsm.py  library.py  attention.py
  services/   api.py  auth.py  stream.py  camera.py  sessions.py
  board/      detect.py  profiles/pi4.toml  profiles/pi5.toml
  tools/      doctor.py  config_cli.py  calibrate.py  smoke.py
web/          pre-built static bundle (served by services/api.py)
android/      Gradle project, same v1 API
```

Legacy modules (`navigation/`, `behavior/`, `mapping/`, `safety/`, `optional/`) are ported
into the new packages phase by phase, then deleted. No file lives in two places at once.

---

## 3. Concurrency model

The legacy design ran everything inside a 5–10 Hz loop, so any blocking call (a head move,
a sweep scan, an audio read) consumed the whole budget, and daemon threads wrote into the
same dict the loop was iterating.

**New model.**

| Layer | Thread | Rule |
|---|---|---|
| Decision (kernel, nav, behaviour) | one loop thread | **Never blocks.** No `sleep`, no `wait_*`, no file I/O, no socket I/O. |
| Actuator gateway | one worker | Serialises commands, and the HAL holds one lock on the servo bus for every caller. Owns the only `pidog` call path for motion. |
| Sensor service | one worker per sensor family | Publishes an immutable `SensorReading` snapshot; readers take the latest. |
| Camera | one producer | Encodes once, fans out frames to N clients; drops on backpressure. |
| Control plane | asyncio event loop | Never touches hardware directly; posts commands to the gateway. |
| Scan worker | one owned worker | Latest-value: a request during a sweep is dropped, not queued (`kernel/scheduler.py`). |

**Rules.**

1. State crossing a thread boundary is **immutable** (frozen dataclass or tuple) or copied
   under a lock. No shared mutable dict.
2. Buffers are **latest-value**, not queues, except where every sample matters (event log).
3. Every blocking call is behind an interface that the fake can implement instantly, so
   tests never sleep.
4. Nothing is `daemon=True` without an owning supervisor entry that can stop and restart it.

---

## 4. Commands and events

One motion path. Replaces the legacy `safety_action` / `watchdog_action` /
`navigation_action` / `behavior_action` string merge.

```
producer ──Command──▶ actuator gateway ──▶ interlock ──▶ hal.action()
                            │                  │
                            └──── Event ───────┘ (accepted / vetoed / completed)
```

`Command` (frozen):

| Field | Meaning |
|---|---|
| `id` | unique per issue; dedupe key is `(action, params, id)`, never the bare string |
| `source` | `client`, `behaviour`, `navigation`, `watchdog`, `system` |
| `action` | catalog name from `config/actions.jsonc` |
| `params` | action-specific, validated against the catalog |
| `ttl_ms` | deadman. A motion stops when it expires unless renewed |
| `priority` | declared, not implied by dict order |

**Precedence is declared, not discovered:** `system > watchdog > client > navigation > behaviour`.
A higher-priority command **cancels** lower ones explicitly and the cancellation is logged.

**Command identity matters.** Two `"forward"` commands from different sources with
different ids are two commands; the gateway can tell "same intent renewed" from
"new intent" — which the legacy string comparison could not.

---

## 5. The interlock (non-negotiable)

Safety is **not** a module and cannot be disabled by configuration in production. It sits
between the gateway and the HAL and answers every command:

| Check | Behaviour on failure |
|---|---|
| **Clamp** | speed/angle clamped to the board profile's safe range; the clamp is logged once per session |
| **TTL / deadman** | command expires (`ttl_ms`, default 300 ms for motion); expiry emits `command_expired` and sends `stop` |
| **Obstacle veto** | last **valid** distance ≤ `emergency_stop_cm` vetoes any forward-family action |
| **Tilt latch** | tilt beyond threshold latches `rest` until an operator explicitly clears it |
| **Link loss** | no heartbeat from a client with an active command → stop within TTL |
| **Low voltage** | if the battery feed reports under threshold, motion is refused |

Every veto returns `accepted: false` **with a reason string**, and emits an event. Silent
refusal is a bug. The audit log records every motion command with source, action, and
verdict — this is what makes "why did the dog do that" answerable.

`--unsafe` exists only on a dev board profile and logs a loud banner for its entire lifetime.

---

## 6. Board profiles

`board/detect.py` reads `/proc/device-tree/model` (Linux) and returns a profile name.
Unknown or missing model on a device build is a **fatal startup error**, not a silent
downgrade — the legacy `detect_pi_class` mapping Pi 5 → `pi4` is exactly the failure this
prevents.

A profile declares:

```toml
# board/profiles/pi5.toml
name = "pi5"
tick_hz = 20
sensor_poll_hz = 20
camera_backend = "picamera2"
max_speed = 200
thermal_soft_c = 75
thermal_hard_c = 85
requires = ["pidog", "robot_hat"]
optional_manifests = ["vision"]
```

Editions differ only by which profile and manifest ship. A fix lands once.

---

## 7. Configuration

- JSON5 (comments) validated by a typed model at load.
- **Unknown key = error** with a did-you-mean suggestion. Range/type errors are errors, not
  warnings. `modules.<name>` sub-keys reach the component — never discarded.
- `houndmind config validate | diff | migrate | explain`.
- The published JSON Schema is a build artifact so editors and the web app can validate.
- Secrets are **never** in this file: the API token lives at `~/.houndmind/api_token` (0600)
  and the config references the path.

---

## 8. Failure and degradation

- A component that cannot start calls `disable(reason)` and stops. It does not raise, unless
  it is declared `required` (HAL pieces only).
- Disabled is not the same as absent: `/health` distinguishes `ok`, `degraded`, `disabled`,
  `failed`, and shows the reason. The dashboard and the apps read this.
- A supervisor restarts resources with exponential backoff and a cap. A watchdog must never
  emit a *motion* recovery that puts the dog in a pose nobody asked for; the safe recovery
  from any fault is **stop the actuators and report**, not "lie down".

---

## 9. Testing strategy

| Layer | Tested with | On CI |
|---|---|---|
| interlock, commands, gateway | `FakeAdapter` + fake clock | yes |
| nav / behaviour / mapping | `FakeAdapter` with scripted traces | yes |
| config schema | golden files + negative cases | yes |
| API / auth / WS | in-process test client, no sockets bound to the LAN | yes |
| HAL adapters | import-time contract tests, `monkeypatch` vendor modules | yes |
| real servos, camera, audio, thermals | on the device, via `houndmind doctor` | **never** |

Rule: a test that needs a Pi is a tool, not a test. It lives in `tools/` and is run by a
human with the dog on blocks.