# HoundMind Architecture

Status: **design** — why the runtime is layered the way it is. Where this file and the tree
disagree, the tree is right and this file is a bug.
Pairs with: `docs/CONTROL_API.md` (the wire contract), `src/houndmind_ai/` (the tree it describes)

The refactor replaced a 5–10 Hz loop in which every module wrote strings into one dictionary. The
sections below are the rules that replaced it: who may touch hardware, who owns a thread, and what
happens when something stops answering.

---

## Contents

1. [Layers](#1-layers) — who may touch hardware, and the dependency rule
2. [Package layout](#2-package-layout) — the real tree
3. [Concurrency model](#3-concurrency-model) — one loop thread, and who may block
4. [Commands and events](#4-commands-and-events) — the typed vocabulary
5. [The interlock (non-negotiable)](#5-the-interlock-non-negotiable)
6. [Board profiles](#6-board-profiles)
7. [Configuration](#7-configuration)
8. [Failure and degradation](#8-failure-and-degradation)
9. [Testing strategy](#9-testing-strategy)

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
  main.py  __main__.py
  board/      detect.py  rules.py
  core/       config.py  instance.py  runtime.py  module.py  logging_setup.py
  kernel/     state.py  commands.py  intents.py  registry.py  scheduler.py  supervisor.py
              config_schema.py  actions.py  decisions.py  place.py  place_store.py
              routine.py  routine_store.py
  hal/        iface.py  fake.py  vendor.py  module.py  sensors.py  motors.py
  act/        gateway.py  interlock.py
  safety/     supervisor.py  watchdog.py  balance.py  health_monitor.py  sensor_health.py
  navigation/ scanning.py  obstacle_avoidance.py  orientation.py  place_navigator.py
              localization.py  odometry.py  place_recognition.py  room_context.py
              route_follower.py
  mapping/    mapper.py  path_planner.py  home_map.py  planner.py  rooms.py  room_scale.py
  behavior/   fsm.py  library.py  registry.py  attention.py  habituation.py  routine_runner.py
  perception/ fusion.py  place_views.py
  calibration/ workflow.py
  logging/    event_logger.py  decision_log.py  led_manager.py
  optional/   vision.py  vision_pi4.py  vision_preprocessing.py  vision_inference_scheduler.py
              face_recognition.py  semantic_labeler.py  slam_pi4.py  slam_clip.py  voice.py
              assistant.py  energy_emotion.py
  services/   api.py  auth.py  camera.py  config_writer.py  discovery.py  module.py
              sessions.py  settings.py  state.py  stream.py  tls.py  web/  (index.html,
              app.js, lib.js, style.css, sw.js, manifest.webmanifest, icon.svg, panels/)
src/tools/    audio_check.py  bench_tick.py  calibrate_servos.py  camera_check.py
              camera_record.py  collect_support_bundle.py  download_opencv_models.py
              hardware_checkup.py  imu_calibrate.py  installer_verify.py
              list_audio_devices.py  map_inspect.py  place_match.py  replay_decisions.py
              schema_export.py  servo_level.py  slam_replay.py  smoke_test.py
              soak_run.py  step_calibrate.py  validate_routines.py  validate_rtabmap_adapter.py
```

`board/` answers one question — which Raspberry Pi this is — and holds no policy of its own. There is
no `android/` project here: the Android client is **HoundMind Remote**, developed in its own repository
against `docs/CONTROL_API.md` and the conformance corpus in `docs/fixtures/clients/` (#274). The client
that ships in this tree is the web app inside `services/web/`.
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
| Actuator gateway | one worker | Serialises commands, and the HAL holds one lock on the servo bus for every caller. Owns the only `pidog` call path — motion and servo trim alike. |
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

### 3.1 What the control plane costs (measured, #19)

The HTTP stack runs in the same process as the loop, so its footprint is the loop's problem. Measured
on the small edition — Pi 4B (8 GB), Bookworm 64-bit, Python 3.11.2, 15 modules loaded with the
motion, vision and voice set disabled — each run settled 60 s, two 30 s CPU windows:

| `modules.api.enabled` | RSS | CPU | Loop |
|---|---|---|---|
| `false` | 60.0 MB | 33.5 %, 32.2 % | — |
| `true`  | 72.5 MB | 31.1 %, 40.5 % | `tick_hz_actual 9.99`, `tick_ms 3.93` |

So the control plane is worth **~12.5 MB of RSS**, and its CPU cost sits inside the noise of a
workload already spending a third of a core on sensor polling. Three WebSocket clients on one token
add ~3.4 points of CPU — but only one of them streams, because the contract allows one socket per
token and evicts the rest with `error: superseded` ([§4](#4-commands-and-events), and
`services/stream.py`).

One number this table does **not** have: concurrent WS clients, which needs one paired token each.
Re-measure before changing the shape — lazy import, a separate process or an opt-in server were all
considered and none of them is justified by these figures.

### 3.1.1 What MJPEG costs (measured, #283)

`services/camera.py` encodes each frame once and fans it out, so a second viewer costs the HTTP stack
and not the camera. Measured on the same board and interpreter as
[§3.1](#31-what-the-control-plane-costs-measured-19) — Pi 4B (8 GB), Bookworm
64-bit, Python 3.11.2 — with `vision_pi4` producing 1944×2592 frames at
`vision_pi4.frame_interval_s: 0.1` and `CameraService.max_fps` at its default of 15:

| Measurement | Value |
|---|---|
| `GET /camera/snapshot`, ticket minted per request and inside the timing | 5, 15, 15, 6, 14 ms for a 50.1 KiB JPEG |
| `GET /camera/stream`, one viewer for 10 s | 68 frames — **6.8 fps, 330 KiB/s** |
| `GET /camera/stream`, two viewers for 10 s | 62 frames — 6.1 fps, 307 KiB/s |
| Runtime CPU over the ~30 s run | 13.4 s, ~45 % of one core |
| RSS | 206.0 → 206.6 MiB, flat |
| `vcgencmd` during the run | `temp=50.6'C`, `throttled=0x50000`, `arm=1.80 GHz` |

So the producer delivers 6.8 fps against a 10 fps request, each frame costs ~4.6 ms of CPU to encode
at full resolution, and a snapshot answers in a few milliseconds on the device. The frame cap is per
client (`services/camera.py:44`), and the second viewer did not double the CPU.

Two caveats, because the numbers are scene- and load-dependent:

- The run was a **dark scene** (`mean=3.4`), which is why the JPEG is 50.1 KiB. A lit scene produces
  larger frames and a lower fps — read 6.8 fps as the optimistic end, not the expected value.
- `throttled=0x50000` is soft-temp plus has-throttled, latched during the session and cleared by the
  next reboot. Read `get_throttled` **before** a reboot or it is no evidence (#316).

Still unmeasured: **end-to-end latency**, the clock-or-hand-in-front-of-the-lens figure. The snapshot
request time and the per-frame encode cost above bound it from below; they are not the number a viewer
experiences, and nothing here should be read as measuring it (#413).

### 3.2 Tick budget (measured, #267)

`core/runtime.py:158-190` stamps `module_tick_duration:<name>` and `module_tick_durations` on every
tick; `python -m tools.bench_tick` drives the same registry `main.build_registry` builds, on a
`FakeDogHAL`, and reports p50/p95/max per module plus how often each overran `1 / loop.tick_hz`.

These are **module code on a workstation**, fake HAL, control plane off. They rank modules and catch
a Python-level regression; they are **not** device numbers, because no I2C read, camera frame or
audio buffer happens here, and the per-module figures sample `time.time()`.

| Board / interpreter | Ticks | tick p50 | tick p95 | Largest module p95 | Command |
|---|---|---|---|---|---|
| Workstation, Python 3.14.5, Windows 11 | 300 (+30) @ 10 Hz | 0.17 ms | 0.32 ms | `watchdog` 0.060 ms, `motion_gateway` 0.052 ms, `behavior` 0.032 ms | `python -m tools.bench_tick --ticks 300` |
| Pi 4B, Bookworm 64-bit, Python 3.11 | — | **not measured** | **not measured** | — | the same command, on the dog |

The budget to compare against is the loop's own: 100 ms per tick at 10 Hz. With every module under
0.4 ms of code, a device tick that overruns is explained either by the vendor reads this harness does
not have or by something it does not measure - both are reasons to run it on the Pi and fill the
second row, not to assume this one.

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
`min_battery_v`) is deliberately **not** user config, so a config edit cannot widen it — with one
deliberate exception: `settings.movement.min_battery_v` may be **raised** above the compiled
`MIN_BATTERY_FLOOR_V` (6.4 V), because raising it only narrows the envelope. The schema's
`minimum` is that floor, so a lower value is a load error rather than a clamp (#208). The shipped
file already sits above it at 7.6 V, because a gait took the bench dog's rail down at 7.78 V with the
pack idle (#292): the constant is the widest the envelope may ever be, not the value this build
recommends.

---

## 7. Configuration

- JSON5 with comments, validated by a typed model at load (`kernel/config_schema.py`).
- **Unknown key = load-time error** with a did-you-mean suggestion, and the process exits before any
  hardware is touched (`core/config.py:183-185`). This is what stops `settings.voice` (instead of
  `voice_assistant`) from silently doing nothing.
- Under `modules.<name>` only `enabled` and `required` are read; tuning lives under
  `settings.<name>`, and a tuning key placed under `modules` is reported rather than ignored.
- **The module name itself is checked too** (`kernel/config_schema.py::KNOWN_MODULES`): a typo such
  as `modules.watchdg` is refused with the near name, and a retired block
  (`modules.telemetry_dashboard`, `modules.wifi_localization`) is refused with what replaced it,
  instead of loading and quietly doing nothing (#392).
- Secrets are **never** in this file: the API token is written on first start to
  `~/.houndmind/api_token` (0600) by `services/auth.py::TokenStore`, and the config references the
  path.

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

### 8.1 A process restart resumes the runtime, never the motion

`systemd` owns the process (`packaging/systemd/houndmind.service`): SIGTERM ends the loop on a tick
boundary and closes the HAL (#212), `Restart=on-failure` brings a crashed run back, and three failed
starts in a minute stop the unit rather than loop it. What comes back after a reboot is the module
set, the control plane and the sensors.

What does **not** come back is anything that was moving. `motion_command` and the intent board are
context-only and every intent expires, so a gait cannot survive a restart by construction; a routine
that was mid-run is lost rather than replayed. That is the rule the restart policy is built on — a
robot that resumes a trajectory after an unexplained reboot is a robot that moves without being
asked. The next start reports how the previous one ended instead (`core/instance.py`, #214).

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