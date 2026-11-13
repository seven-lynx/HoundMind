# HoundMind Architecture

Status: **design** — why the runtime is layered the way it is. Where this file and the tree
disagree, the tree is right and this file is a bug.
Pairs with: `docs/CONTROL_API.md` (the wire contract), `src/houndmind_ai/` (the tree it describes)

The refactor replaced a 5–10 Hz loop in which every module wrote strings into one dictionary. The
sections below are the rules that replaced it: who may touch hardware, who owns a thread, and what
happens when something stops answering.

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
  │  behavior FSMs · navigation · mapping  (pure, testable)    │
  └─────────────────────────┬──────────────────────────────────┘
                            │ IntentBoard entry (desired motion)
  ┌─────────────────────────▼──────────────────────────────────┐
  │  act/   actuator gateway  +  MANDATORY INTERLOCK           │
  └─────────────────────────┬──────────────────────────────────┘
                            │ Dog HAL (Protocol)
  ┌──────────────────────────┴─────────────────────────────────┐
  │  hal/   PidogHAL (device)          FakeDogHAL (CI + tests) │
  └────────────────────────────────────────────────────────────┘
```

**Dependency rule (enforced by review; an import-linter would make it mechanical):**

`services` → `kernel` → `act` → `hal`. Never the reverse. Vendor imports (`pidog`, `robot_hat`,
`vilib`, `picamera2`, `rtabmap`) appear **only** in `hal/` and `optional/`. A vendor import anywhere
else is a defect: it breaks `pip install` on a workstation and in CI.

---

## 2. Package layout

The real tree, not the planned one:

```
src/houndmind_ai/
  board/      detect.py
  core/       config.py  runtime.py  module.py  logging_setup.py
  kernel/     state.py  commands.py  intents.py  registry.py  scheduler.py  supervisor.py
              config_schema.py  routine.py  routine_store.py
  hal/        iface.py  fake.py  vendor.py  module.py  sensors.py  motors.py
  act/        gateway.py  interlock.py
  safety/     supervisor.py  watchdog.py  balance.py  health_monitor.py  sensor_health.py
  navigation/ scanning.py  obstacle_avoidance.py  orientation.py  local_planner.py
  mapping/    mapper.py  path_planner.py
  behavior/   fsm.py  library.py  registry.py  attention.py  habituation.py  routine_runner.py
  perception/ fusion.py
  calibration/ servo_calibration.py  workflow.py
  logging/    event_logger.py  led_manager.py
  optional/   vision.py  vision_pi4.py  vision_preprocessing.py  vision_inference_scheduler.py
              face_recognition.py  semantic_labeler.py  slam_pi4.py  voice.py  energy_emotion.py
  services/   api.py  auth.py  camera.py  module.py  sessions.py  settings.py  state.py
              stream.py  web/  (index.html, app.js, style.css)
src/tools/    hardware_checkup.py  smoke_test.py  camera_check.py  collect_support_bundle.py
              download_opencv_models.py  installer_verify.py  list_audio_devices.py
              validate_rtabmap_adapter.py
```

`board/` answers one question — which Raspberry Pi this is — and holds no policy of its own. There is
no `android/` project yet, and the only client that ships is the web app inside `services/web/`.
`src/tools/` holds device CLIs run as `python -m tools.<name>`; it is not a second implementation of
anything.

---

## 3. Concurrency model

The old design ran everything inside the loop, so any blocking call — a head move, a sweep scan, an
audio read — consumed the whole budget, and daemon threads wrote into the same dict the loop was
iterating.

| Layer | Thread | Rule |
|---|---|---|
| Decision (kernel, nav, behavior) | one loop thread | **Never blocks.** No `sleep`, no `wait_*`, no file I/O, no socket I/O. |
| Actuator gateway | one worker | Serialises commands, and the HAL holds one lock on the servo bus for every caller. Owns the only `pidog` call path for motion. |
| Sensor service | one worker per sensor family | Publishes an immutable `SensorSnapshot`; readers take the latest. |
| Camera | one producer | Encodes once, fans out frames to N clients; drops on backpressure. |
| Control plane | asyncio event loop, own thread | Never touches hardware directly; posts commands to the bus. |
| Scan worker | one owned worker | Latest-value: a request during a sweep is dropped, not queued (`kernel/scheduler.py`). |

**Rules.**

1. State crossing a thread boundary is **immutable** (frozen dataclass or tuple) or copied under a
   lock. No shared mutable dict.
2. Buffers are **latest-value**, not queues, except where every sample matters (event log).
3. Every blocking call is behind an interface the fake can implement instantly, so tests never sleep.
4. Nothing is `daemon=True` without an owning supervisor entry that can stop and restart it.

---

## 4. Commands and events

One motion path. It replaces the legacy `safety_action` / `watchdog_action` / `navigation_action` /
`behavior_action` string merge, which had no way to express "this producer is gone".

```
producer ──intent──▶ IntentBoard ──┐
                                   ├──▶ gateway ──▶ interlock ──▶ hal.action()
client   ──Command─▶ CommandBus ───┘        │            │
                                            └── Event ───┘ (accepted / vetoed / cancelled)
```

Two entry points, one execution path:

- **`IntentBoard`** (`kernel/intents.py`) — one slot per `Source`, refreshed each tick and
  **expiring** if not. A producer that crashed, blocked or changed its mind stops being heard, with
  nothing to un-set. This is what the internal modules use.
- **`CommandBus`** (`kernel/commands.py`) — typed `Command` objects from the control plane, with a
  bounded queue. A full queue is a `429`, never added latency on the servo bus.

`Command` (frozen):

| Field | Meaning |
|---|---|
| `id` | unique per issue; the dedupe key is the id, never the bare action string |
| `source` | `behaviour`, `navigation`, `client`, `watchdog`, `system` |
| `action` | a known action name: `KNOWN_ACTIONS`, or anything classified in `config/actions.jsonc` (`kernel/actions.py`) |
| `params` | action-specific; rewritten by the interlock when it clamps a speed |
| `ttl_ms` | deadman. A motion stops when it expires unless renewed |
| `priority` | the `Source` value — declared, not implied by dict order |

**Precedence is declared, not discovered:** `Source` is an `IntEnum`, so
`system > watchdog > client > navigation > behaviour` is one number per producer at
`kernel/commands.py:36`. A higher-priority command **cancels** lower ones explicitly and the
cancellation is logged (`motion_cancel` on the context, `displaced` in the state snapshot).

**Command identity matters.** Two `"forward"` commands from different sources are two commands; the
gateway can tell "same intent renewed" from "new intent" — which the legacy string comparison could
not.

---

## 5. The interlock (non-negotiable)

The interlock is not a module and cannot be turned off from configuration. It sits between the
gateway and the HAL and answers every command, in this order (`act/interlock.py:1-24`). The **class**
of the action decides how much of the envelope applies; the class is data in `config/actions.jsonc`,
loaded by `kernel/actions.py`, and it selects which limits apply without ever editing one.

| # | Check | Behaviour |
|---|---|---|
| 1 | `stop` | **Always accepted.** The escape hatch is never vetoed, at any layer. |
| 2 | Unknown action | Refused — `veto: "unknown_action"`. Nothing classifies it. |
| 3 | TTL / deadman | Refused past `ttl_ms` (default 300 ms). Every class spends it, an LED included. |
| 4 | `non_motion` | Accepted here — `rgb`, `sound`, `speak`, `head`, `rpy`. A flat battery must not stop the dog saying the battery is flat. |
| 5 | Tilt latch | Posture, expression and locomotion refused until a human clears it. Latched from a **valid** IMU only. |
| 6 | Low voltage | The same three classes refused below `min_battery_v`, and only when the reading is valid. |
| 7 | Obstacle veto | `locomotion`, **forward family** only: the last **valid** distance ≤ `emergency_stop_cm`. |
| 8 | Speed clamp | `speed` clamped to `max_speed`; the clamp is logged once per session. |

`forward`, `backward`, `turn_left`, `turn_right` and `trot` are `locomotion` in every repertoire.
A config that tries to classify one as anything weaker is refused at load with the action named,
because the obstacle stop is not user config — the envelope belongs to the board, not to
`settings.jsonc`.
`backward` and the turns stay outside the obstacle rule on purpose: they are how the dog leaves a
corner.

Every veto returns `accepted: false` **with a reason string**, and emits an event. A silent refusal is
a bug — the operator would have no way to learn why the dog did not move. The obstacle and tilt checks
read the validity flags, so a broken sensor can neither veto motion forever nor authorise it.

The mode policy (`MODE_ALLOWED_SOURCES`, `kernel/commands.py:81`) is a separate, earlier gate: it
decides *which producer may ask* in the current mode, and the interlock decides whether the winner's
command is safe. `stop` passes both.

---

## 6. Board profiles

Board differences are **configuration**, not code paths. `board/detect.py` reads the device-tree model
and classifies it as `pi4`, `pi5`, `unsupported` (Pi 3 and older) or `unknown` (no device tree: CI, a
workstation, a container). `profile` in `config/settings.jsonc` ships as `auto`, which means "use that
answer"; `HOUNDMIND_PROFILE=pi4` overrides it at launch.

Resolution rules, in order:

1. `HOUNDMIND_PROFILE` if set, then `profile` in the file, then `auto`.
2. A name asked for explicitly must exist in `profiles` — a typo is a load-time error with a
   did-you-mean, not a warning that runs the shipped cadence.
3. `auto` on a supported board picks that board's profile. A profile with no overrides is fine (a
   config may define none); the base settings are the answer.
4. `auto` on an unsupported board is a load-time error naming the model and the last release that
   supported it. On an unknown host it logs a warning and uses `pi4`.

A profile sets cadence and enablement and nothing else: `loop.tick_hz`, `sensors.poll_hz`, the
`navigation.scan_*` cadence, the `enabled` flag on Pi4/5-only modules, camera backend, and the thermal
warning thresholds where the board's own behaviour differs. The safety envelope
(`act/interlock.py::InterlockLimits`: `max_speed`, `emergency_stop_cm`, `tilt_latch_deg`,
`min_battery_v`) is deliberately **not** user config, so a config edit cannot widen it.

---

## 7. Configuration

- JSON5 with comments, validated by a typed model at load (`kernel/config_schema.py`).
- **Unknown key = load-time error** with a did-you-mean suggestion, and the process exits before any
  hardware is touched (`main.py:123-129`). This is what stops `settings.voice` (instead of
  `voice_assistant`) from silently doing nothing.
- Under `modules.<name>` only `enabled` and `required` are read; tuning lives under
  `settings.<name>`, and a tuning key placed under `modules` is reported rather than ignored.
- Secrets are **never** in this file: the API token lives at `~/.houndmind/api_token` (0600) and the
  config references the path.

---

## 8. Failure and degradation

- A component that cannot start calls `disable(reason)` and stops. It does not raise, unless it is
  declared `required` (HAL pieces only).
- Disabled is not the same as absent: `GET /api/v1/modules` distinguishes `ok`, `degraded`,
  `disabled` and `failed`, and carries the reason. `GET /api/v1/health` is liveness only — it returns
  `{"status": "ok"}` and leaks nothing, because it is unauthenticated.
- `kernel/supervisor.py` restarts resources with exponential backoff and a cap. A watchdog must never
  emit a *motion* recovery that puts the dog in a pose nobody asked for; the safe recovery from any
  fault is **stop the actuators and report**, not "lie down".

---

## 9. Testing strategy

| Layer | Tested with | On CI |
|---|---|---|
| interlock, commands, intents, gateway | `FakeDogHAL` + fake clock | yes |
| navigation / behavior / mapping | `FakeDogHAL` with scripted traces | yes |
| config schema | golden files + negative cases | yes |
| API / auth / WebSocket | `aiohttp.test_utils.TestClient`, no socket bound to the LAN | yes |
| HAL adapters | import-time contract tests, `monkeypatch` vendor modules | yes |
| real servos, camera, audio, thermals | on the device, by hand | **never** |

Rule: a test that needs a Pi is a tool, not a test. It lives in `src/tools/` and is run by a human
with the dog on blocks. `tests/` runs with no dog attached, and `pyproject.toml` pins
`testpaths = ["tests"]` so a device CLI named `*_test.py` cannot be collected as a test module.