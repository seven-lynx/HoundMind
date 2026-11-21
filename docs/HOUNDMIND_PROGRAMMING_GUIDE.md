# HoundMind Programming Guide

Status: **guide** — how to run, tune and extend the runtime. The authoritative version of every
default is `config/settings.jsonc`; this file explains it.
Pairs with: `docs/ARCHITECTURE.md` (why), `docs/FEATURES_GUIDE.md` (what each module does),
`docs/PIDOG_PROGRAMMING_GUIDE.md` (the vendor library underneath)

HoundMind is an add-on to the SunFounder PiDog software: install the vendor library first, then
HoundMind into the **same** virtualenv. Simulation mode is not supported — there is no dry-run that
moves a virtual dog, so everything here either runs against hardware or against `FakeDogHAL` in a
test.

---

## Contents

1. [Quick start](#1-quick-start) — install, run, the six keys worth knowing first
2. [Runtime model](#2-runtime-model) — the loop, the module lifecycle, intents
3. [Modules overview](#3-modules-overview)
4. [Context keys](#4-context-keys) — the contract every module reads and writes
5. [Sensor data types](#5-sensor-data-types) — `SensorReading`, `ScanReading`, validity flags
6. [Configuration sections](#6-configuration-sections)
7. [Configuration examples](#7-configuration-examples)
8. [Safety defaults and onboarding](#8-safety-defaults-and-onboarding)
9. [Calibration workflow](#9-calibration-workflow) — moves servos, needs clearance
10. [Logging and diagnostics](#10-logging-and-diagnostics)
11. [Autonomy, attention and behaviour tuning](#11-autonomy-attention-and-behaviour-tuning)
12. [Mapping and path planning](#12-mapping-and-path-planning)
13. [On-device validation](#13-on-device-validation)
14. [Extending the system](#14-extending-the-system) — writing a module
15. [Pi4 profile and deferred work](#15-pi4-profile-and-deferred-work)
16. [Developer commands](#16-developer-commands)

---

## 1. Quick start

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-lite.txt
python -m pip install -e .
```

Vendor libraries (`pidog`, `robot-hat`, `vilib`) are **not on PyPI**; install them from the SunFounder
repositories first, or let `scripts/install_houndmind.sh` do both. Then:

```bash
source .venv/bin/activate
python -m houndmind_ai                # or: .venv/bin/python -m houndmind_ai
```

`python -m houndmind_ai` accepts one flag: `--config <path>` to point at a settings file other than
`config/settings.jsonc`. There is no `--dry-run`: a run either has hardware or fails at the HAL, and a
config error exits with status 2 before any hardware is touched.

To prove the package imports without a dog attached:

```bash
PYTHONPATH=src python -c "import houndmind_ai; print('import OK')"
```

### Tuning it

Edit `config/settings.jsonc`. The keys that change behaviour most per keystroke:

| Key | Default | Effect |
|---|---|---|
| `loop.tick_hz` | `5` base; `10` on the `pi4`/`pi5` profiles | Decision-loop rate. Higher reacts faster and costs more CPU; the budget is `1/tick_hz`. |
| `sensors.poll_hz` | `10` | Sensor sampling rate, capped by `performance.sensor_poll_hz_max`. |
| `navigation.scan_interval_s` | `0.3` | How often the sweep runs; bounded by `scan_interval_min_s` / `_max_s`. |
| `behavior.idle_action`, `behavior.action_sets` | see config | What the dog does with no reason to do anything else. |
| `motors.min_action_interval_s` | `0.6` | Floor between motor commands. |
| `loop.max_cycles` | `null` | `null` means run forever, which is the only sane default for a service. |

### Autonomy tuning

HoundMind can patrol, play and rest without input. **It ships off**, because a start must not walk the
dog: `explore` draws `explore_action` (`forward`), so `behavior.autonomy_enabled` is `false` and the FSM
treats an absent key the same way — a config written before the key existed does not opt in by
omission. The knobs all live under `settings.behavior`:

- `autonomy_enabled`, `autonomy_interval_s`, `autonomy_modes`, `autonomy_weights`
- `autonomy_rest_energy_max`, `autonomy_play_energy_min`

```jsonc
"behavior": {
  // The opt-in: nothing below happens while this is false.
  "autonomy_enabled": true,
  "autonomy_interval_s": 8.0,
  "autonomy_modes": ["idle", "patrol", "play", "rest"],
  "autonomy_weights": {"idle": 0.4, "patrol": 0.3, "play": 0.2, "rest": 0.1},
  "autonomy_rest_energy_max": 0.35,
  "autonomy_play_energy_min": 0.75
}
```

A mode in `autonomy_modes` is only reachable if its bucket has an action, and `patrol`/`explore` walk
the dog — list them only when the dog has room.

### Validating and stopping

Bench validation is the checklist in `docs/INSTALL.md`. Optional modules stay off until it passes.
Stop the runtime with `Ctrl-C` and let the process exit: the module `stop()` hooks run and the HAL
closes the servo bus. Do not kill -9 a moving dog.

---

## 2. Runtime model

HoundMind runs a fixed-tick loop. Each tick reads sensors, fuses them into perception, updates
scanning/navigation/behavior, and finally emits at most one motion command.

- **`RuntimeContext`** — the dict-like object every module reads and writes. Keys are contracts;
  [§4](#4-context-keys) is the list.
- **`Module` lifecycle** — `start(context)`, `tick(context)`, `stop(context)`. A module that cannot
  start calls `self.disable(reason)` and stops; it does not raise unless it was registered
  `required=True`.
- **Tick rate** — `loop.tick_hz`. Lowering it cuts CPU and costs reaction time; the shipped profiles use 10.
- **Motion never comes from a module writing an action string.** Producers publish an intent to the
  `IntentBoard`; `motion_gateway` ranks them, runs the winner through `act/interlock.py`, and publishes
  `motion_command`. `hal_motors` executes nothing else.

A minimal module:

```python
from __future__ import annotations

import logging

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class ExampleModule(Module):
    """Publishes one derived value and never blocks the tick."""

    def start(self, context) -> None:
        self._seen = 0

    def tick(self, context) -> None:
        reading = context.get("sensor_reading")
        if reading is None or not getattr(reading, "distance_valid", False):
            return  # branch on validity before value
        self._seen += 1
        context.set("example.distance_cm", reading.distance_cm)

    def stop(self, context) -> None:
        logger.info("ExampleModule saw %d valid readings", self._seen)
```

That skeleton is the whole contract: no `sleep`, no file I/O, no vendor import, and a validity check
before the value. Registration is manual — [§14](#14-extending-the-system).

---

## 3. Modules overview

What to expect from each package, and what to watch when it misbehaves.

**Core**
- `core/runtime.py` — loop management and module lifecycle. Watch for tick overruns; the runtime
  publishes `module_tick_duration:<name>` and a `tick_latency` warning when a module blows the budget.
- `core/config.py` — JSON5 parsing, profile merge, strict validation. A bad key stops the process
  before hardware is opened.
- `core/module.py` — the `Module` base class, `disable(reason)`, and the status the API reports.

**Kernel** (`kernel/`)
- `commands.py` — `Source`, `Command`, `Verdict`, `CommandBus`, `RUNTIME_MODES`, `MODE_ALLOWED_SOURCES`.
- `intents.py` — `IntentBoard`: one expiring slot per producer.
- `scheduler.py` — `LatestJobWorker`: the owned worker a scan runs on.
- `supervisor.py` — restart policy, backoff, and the give-up list.
- `registry.py` — `Capability` labels; a second claimant for an exclusive one is a startup error.
- `state.py`, `config_schema.py` — snapshot shape and the typed config model.

**HAL** (`hal/`)
- `iface.py` — `DogHAL` Protocol and the immutable `SensorSnapshot`.
- `vendor.py` — `PidogHAL`, the only place that imports `pidog` and the only holder of the servo lock.
- `fake.py` — `FakeDogHAL`, used by CI and every test.
- `sensors.py` / `motors.py` — polling and execution on top of the HAL.

**Navigation, mapping, behavior**
- `navigation/scanning.py` — three-way and sweep scans on the worker; publishes `scan_reading` and the
  measured `scan_duration_s`. Check `scan_quality` before trusting a long-range value.
- `navigation/obstacle_avoidance.py` — turn choice, no-go memory, stuck recovery. Tune
  `navigation.turn_cooldown_s` to stop oscillation.
- `navigation/orientation.py` — gyro-Z heading integration into `current_heading`.
- `navigation/place_navigator.py` — walks to a taught place (one `Source.PLACE` intent per cycle).
- `mapping/mapper.py` — openings, safe paths, optional home-map snapshots.
- `behavior/` — FSM, action library, registry, attention and habituation. Actions come from
  `config/actions.jsonc`.
- `behavior/routine_runner.py` — plays a user-authored routine (`docs/ROUTINES.md`) one step per tick,
  publishing each step as a `Source.ROUTINE` intent and retracting it on the tick the step settles, so
  two identical steps are two commands. The first refusal ends the run.

**Safety and diagnostics**
- `safety/watchdog.py` — holds motion when sensor or scan data is stale; asks the runtime to restart
  modules that stopped ticking. Stop-and-report, never a pose.
- `safety/supervisor.py` — the state the watchdog publishes as `watchdog_status`.
- `safety/balance.py`, `safety/health_monitor.py`, `safety/sensor_health.py` — all off by default.
- `logging/event_logger.py` — JSONL events with rotation; `logging/led_manager.py` — LED priority.

**Optional** (`optional/`) — vision, voice, face recognition, semantic labeling, SLAM, energy/emotion.
Every heavy import is inside the method that needs it, so `lite` imports cleanly on a workstation.

---

## 4. Context keys

The keys a module may rely on. Anything not here is private and may change.

**Set by the loop**

| Key | Type | Meaning |
|---|---|---|
| `config`, `settings` | objects | Parsed config and its `settings` section |
| `trace_id` | `str` | Correlates every log line and event of one run |
| `tick_ts`, `watchdog_heartbeat_ts` | `float` | Monotonic timestamps |
| `module_names` | `list[str]` | Tick order |
| `module_heartbeat:<name>` | `float` | Last tick time, per module |
| `module_tick_duration:<name>` | `float` | Seconds, per module |
| `module_error:<name>` | `str \| None` | Why a module stopped |
| `module_tick_durations` | `dict` | All durations at once |
| `restart_modules` | `list[str]` | Modules the watchdog wants restarted |
| `quiet_mode_active` | `bool` | Suppresses behaviour chatter |
| `runtime_tick` | `int` | Monotonic cycle counter, set before the modules run; also a log field (`docs/LOGGING.md`) |

**Identity and board** — set once at startup, by `main.py`

| Key | Type | Meaning |
|---|---|---|
| `device_id` | `str` | Stable id for this device; what `/meta` and the API serve |
| `board_model` | `str` | The device-tree model string the profile was chosen from (`board/detect.py`) |

**Sensors and perception**

| Key | Type |
|---|---|
| `hal` | `DogHAL \| None` — the only path to hardware |
| `sensor_reading` | `SensorReading` ([§5](#5-sensor-data-types)) |
| `sensors`, `sensor_history`, `sensor_health` | `dict` |
| `scan_reading` | `ScanReading` ([§5](#5-sensor-data-types)) |
| `scan_latest`, `scan_quality`, `scan_history` | `dict` |
| `scan_duration_s` | `float` — measured sweep length |
| `perception` | `dict` — the fused snapshot; every key is documented in the table below |
| `faces` | `dict \| None` — what the detector saw: `timestamp` (the frame's own capture time), `backend`, `detected` (read by `perception`, P4 PL3) |
| `scan_in_flight` | `bool` |
| `scan_worker`, `scan_service` | worker and service handles |
| `current_heading` | `float` — degrees |
| `sensor_service` | service handle — the sensor loop; `orientation`, `fusion` and `safety/supervisor.py` read it |
| `battery_voltage` | `float` — pack volts, published only while valid; `act/gateway.py`, `behavior/fsm.py` and `/state` prefer it over the reading |
| `pose_hint` | `dict` — what `perception/fusion.py` infers about the body; the calibration workflow reads it |

**`perception`, key by key** — assembled in one place (`perception/fusion.py::_update_from_reading`),
so two keys cannot disagree. Every value here is a *measurement*, so a consumer branches on the
companion flag before it reads the value; a missing reading is not a zero, and it is not a "no".

| Key | Type today | Meaning | Companion flag | What a falsy flag licenses |
|---|---|---|---|---|
| `obstacle` | `bool` | `True` when the reading carried a positive range under `settings.perception.obstacle_cm` (20 cm shipped), validated or not; `False` when it carried no range at all | `obstacle_valid` — **published**; `True` only when that range was also flagged valid | *Nothing yet.* `False` beside an invalid flag is a sonar that did not answer: unproven, not permission to keep driving (`navigation/obstacle_avoidance.py:78`) |
| `distance` | `float \| None` | whatever range the HAL put in the reading; `None` when it had nothing | `distance_valid` — **published** | render "—", never a number — the one client rule [CONTROL_API.md §4](CONTROL_API.md#4-state-snapshot) forbids softening |
| `touch` | `str` | `"N"` when no pad is pressed, else the pad's name | `touch_valid` — **published** | no interaction is spent on a pad that did not answer |
| `sound` | `bool` | the reading's `sound_detected` — a clap was heard | `sound_valid` — **published** | no attention cue (`behavior/attention.py:37`), and "quiet" is not claimed either |
| `sound_direction` | `int \| None` | bearing of the last clap; `None` when the vendor gave none | none — `None` is the flag | the head stays where it is; never default it to `0` (`behavior/attention.py:50`) |
| `occupancy` | `bool \| None` | somebody in front of the dog, with `min_frames` / `release_frames` hysteresis | `occupancy_valid` — **published** | `null` with `false` means unknown (no detector, no frame, stale frame), never "nobody there" ([FEATURES_GUIDE.md §3](FEATURES_GUIDE.md#3-perception)) |
| `occupancy_frames` | `int` | consecutive frames behind the current claim | rides with `occupancy_valid` | not a confidence — one frame is not "almost someone" |

Every one of those flags is published by `perception/fusion.py::_update_from_reading` beside its
value, `occupancy_valid` with them, so nothing in the snapshot is a bare value. What has *not*
moved is the consumers: `behavior/fsm.py:83-85` and `navigation/obstacle_avoidance.py:78-84` still
read the value with a default, which is how "the sensor did not answer" became "nothing is there",
and teaching them the flag is #270's next slice. The snapshot is rewritten every tick from whatever
`sensor_reading` holds, so a reading the sensor loop stopped refreshing stays in place with the
flags of its own last tick: its age is still the consumer's to check.

**Navigation, mapping and behaviour**

| Key | Type |
|---|---|
| `navigation_decision`, `navigation_turn`, `navigation_followup` | `dict` |
| `place_request` | `dict` in, consumed once — `{"id": "<slug or name>", "at_anchor": true}` |
| `place_goal` | `dict \| None` — the trip in progress, or why it was refused (`navigation/place_navigator.py`) |
| `place_store` | `PlaceStore \| None` — the one store for `settings.places.path`, published by the navigator at start and cleared at stop; the `/places` routes write through it, so a second store would be a second writer (`kernel/place_store.py`) |
| `identity_roster` | `dict \| None` — `{backend, path, people: [{id, name}]}`, published by `optional/face_recognition.py` at start and after every mutation; what `GET /api/v1/people` serves, and never an embedding |
| `identity_admin` | `IdentityForgetter \| None` — the module's `forget(id)` and nothing else, published at start and cleared at stop; `DELETE /api/v1/people/{id}` is its only caller, and it runs in an executor because an LBPH retrain reads every image |
| `mapping_openings`, `mapping_state` | `dict` — the sweep-derived openings, and the sample history plus the occupancy `grid` |
| `home_map` | `dict \| None` — the loaded map document (`mapping/home_map.py`), published by `mapping` at start; absent when `mapping.home_map_load_path` is empty |
| `home_map_status` | `dict` — `{loaded, cells, reason, problems, notes}`, always published, so "no map" is a stated fact rather than a missing key |
| `behavior_override` | `str \| None` |
| `behavior_state` | `str` — the FSM's published state (`idle`, `alert`, …), not a command |
| `runtime_mode` | `idle` \| `patrol` \| `manual` \| `rest` |
| `stuck_recovery` | `dict` — obstacle avoidance's stuck-recovery state; the event log records it |
| `gentle_recovery_active` | `bool` — a gentle retreat is in progress |
| `energy_level`, `energy_speed_hint` | `float`, `str \| None` — 0..1 energy (one producer: `behavior/fsm.py`, switched by `settings.energy.enabled`), and the speed hint the motors clamp to |
| `emotion_state` | `str` — the label `optional/energy_emotion.py` publishes for LEDs and behaviour |
| `behavior_habituation` | `dict` — `{stimulus, count}`, the per-stimulus counter `behavior/fsm.py` keeps |
| `orientation_calibration_ok` | `bool` — a calibration run produced the z-axis bias (`orientation_bias_z`); `False` when it had no samples. Served as `nav.heading_calibrated` |

`mapping/room_scale.py::RoomScale` is the H4 half of the mapping story: fed one sample per sonar tick
— the pose, the heading, the range and its validity — it returns `scale_progress`, with the
sufficiency table's seven criteria and how far the run has got against each, plus a verdict. It is a
**library**: nothing ticks it and it publishes no key, so a run's `scale_progress` is the room run's
to publish (H6) and the console's to draw (H8). The distinction it exists for is *discover* versus
*confirm*: a room that carries `size_cm` is drawn in centimetres, so its walls can confirm a stride,
while a room without one cannot and the measurement comes from the ranged **differences** along a
wall the dog walked beside — the method `tools/step_calibrate.py` uses, minus the walk-into-a-wall.
Neither mode writes anything: `step_cm_source` stays `assumed` until an `--apply` passes
`navigation/odometry.py::apply_step_value`'s gates (five samples, within 10 % of each other, clamped
to ±20 % per apply).

**Motion** — the only keys `hal_motors` reads

| Key | Type |
|---|---|
| `intent_board` | `IntentBoard` — what each source asks for right now |
| `motion_command` | `dict \| None` — the winning command |
| `motion_verdict` | `dict` — the tick's outcome: `status` is `accepted`, `refused`, `undecided` or `silent`, with `veto`/`detail` on a refusal and `sources` naming the refusals behind `undecided` |
| `motion_cancel` | `list` — lower-priority intents this tick displaced |
| `tilt_latched` | `bool` |

**Decisions** — the answer to "why did the dog do that"

| Key | Type |
|---|---|
| `decision_record` | `DecisionRecord` (`kernel/decisions.py`) — this tick's winner, refusals and inputs, published by `motion_gateway` |
| `decision_ring` | `DecisionRing` — the last `decision_log_max_entries` records, oldest first, published by `decision_log` |

**Routines** — the runner's request/answer pair

| Key | Type |
|---|---|
| `routine_request` | `dict` — `{"id", "dry_run"}`, written by `POST /api/v1/routines/{id}/run`; the runner consumes it on the next tick |
| `routine_report` | `StoreReport` (`kernel/routine_store.py`) — what `settings.routines.dir` held when the runner started, refusals included |
| `routine_run` | `RoutineRun` (`behavior/routine_runner.py`) — the run in progress or just finished, republished every tick; `to_dict()` is the one object behind `/routines`, `state.routines` and the `routine` event |
| `routine_stop` | `bool` — `POST /stop` sets it and the runner ends the run as `stopped`; only set when a runner is loaded, so the flag cannot outlive the stop |

A routine is admitted in `idle`, `patrol` and `manual`; `rest` refuses it, so a routine started while
the dog is resting reports `veto: "mode"` instead of moving (`kernel/commands.py::MODE_ALLOWED_SOURCES`).

**Safety, health, LEDs**

| Key | Type |
|---|---|
| `safety_active`, `emergency_stop_active` | `bool` |
| `tilt_warning` | `dict` (`pitch`, `roll`) |
| `watchdog_hold`, `watchdog_status` | `dict` |
| `health_status`, `health_degraded` | `dict`, `bool` |
| `health_high_water` | `dict[str, float \| None]` — the worst value each health metric reached since start; served as `health.high_water` |
| `scan_interval_override_s` | `float \| None` |
| `led_request:safety` \| `:navigation` \| `:attention` \| `:emotion` \| `:health` | `dict` |

**Calibration and optional sources**

| Key | Type |
|---|---|
| `calibration_request`, `calibration_result` | `str`, `dict` ([§9](#9-calibration-workflow)) |
| `localization_confidence` | `float` |
| `vision_frame`, `vision_frame_jpeg` | array, `bytes` — the Pi 4/5 feed (`optional/vision_pi4.py`) or the Pi 3 one (`optional/vision.py`), stamped by `vision_frame_ts` |
| `face_recognition_command` | `dict` |
| `voice_text`, `voice_command` | `str` |
| `slam_map_data`, `slam_trajectory` | `dict` |
| `vision_status`, `vision_inference_status`, `vision_inference_result` | `dict` — camera readiness from `optional/vision_pi4.py` or `optional/vision.py` (`{status, backend, frames}`; `frames: false` with a `reason` when the build cannot produce one), the scheduler's state (`{state}`) and its latest answer |
| `vision_frame_interval_override_s` | `float \| None` — the health monitor asking vision to slow down |
| `face_recognition_status`, `semantic_status`, `slam_status` | `dict` — `{status, backend}` from each optional module, published by the module itself |
| `slam_pose` | `dict \| None` — the pose SLAM published last |
| `slam_stats` | `dict` — `frames_in`, `frames_skipped`, `frames_processed`, `frames_dropped`, `frames_failed`, `buffered`: what the backend did with the frames it was given, cumulative for the run (`optional/slam_pi4.py`). A replay quotes processed-versus-lost from here instead of guessing. `frames_in` counts published frames — one entry per frame the producer replaced, deduped on `vision_frame_ts` (identity when a producer sets no stamp) — and `frames_skipped` counts the due ticks that found the same frame again or found none, so the two together account for every tick |
| `odometry` | `dict` — `steps`, `distance_cm`, `travelled_cm`, `x_cm`, `y_cm`, `yaw_deg`, `pose_valid`, `reason`, `step_cm`, `step_cm_source`, `surface`; centimetres along the heading, no encoders, and the source says whether the constant was measured |
| `localization` | `dict` — the chosen pose and why it is the best available: `tier` (`slam`/`place`/`user`/`dead_reckoning`/`reactive`), `frame`, `pose`, `confidence`, `age_s`, `reason` |
| `localization_event` | `dict` — one record per change of tier, `{from, to, reason}` |
| `pose_trail` | `list` — the walk so far, `[{x_cm, y_cm, yaw_deg, tier, ts}, ...]` in the **odometry** frame: one point per 5 cm of movement, capped at `TRAIL_MAX_POINTS`, emptied when a correction re-anchors the origin (M6). A SLAM-framed pose is never appended: a trail with two frames on it is a walk through rooms the dog was never in |
| `pose_reset` | `dict \| None` — `{x_cm, y_cm, source, frame_ts}` written by `PUT /api/v1/map/pose`; `navigation/odometry.py` consumes it **once** and re-anchors the pose there. A bare `odometry_reset` still means "the origin now" (M5) |
| `route_request`, `route` | `dict` — the goal a client asked for (`{"goal_cm": {...}}`, written by `POST /api/v1/map/go`) and the plan `navigation/route_follower.py` made of it: waypoints, `index`, `total`, `state`, or the named refusal (M5, M6) |
| `current_room` | `dict` — the room the pose falls in (`navigation/room_context.py`): `id`, `name`, `valid`, `source` (`user_pose`/`place`/`odometry`, or `null` with no pose) and `reason` (`no_pose`, `pose_frame:slam`, `no_rooms`, `outside_every_room`). `id`/`name` are `null` whenever `valid` is `false`; the point is swapped into the **document** frame before any polygon test |
| `event_log_report` | `dict` — the event writer's own state (`logging/event_logger.py`) |

**Internal bookkeeping — not a contract**

| Key | Why it is private |
|---|---|
| `attention_active_ts`, `head_turn_follow_release_ts`, `health_status_last_log_ts`, `vision_frame_ts`, `gentle_recovery_until`, `orientation_bias_z` | Timestamps and accumulators a module keeps for itself — the `<name>_ts` suffix is the giveaway. They may change or vanish without a contract bump, and no module may read another module's. |

**Removed, and not coming back:** `safety_action`, `watchdog_action`, `navigation_action`,
`behavior_action`. Producers publish to the `IntentBoard` instead, and `hal_motors` never reads a
producer key.

---

## 5. Sensor data types

### `SensorReading` — `hal/sensors.py:48`

```python
@dataclass
class SensorReading:
    distance_cm: float | None
    touch: str                     # "N" when nothing is pressed
    sound_detected: bool
    sound_direction: int | None
    acc: tuple[float, float, float] | None
    gyro: tuple[float, float, float] | None
    timestamp: float
    distance_valid: bool
    touch_valid: bool
    sound_valid: bool
    imu_valid: bool
    battery_v: float | None = None   # optional feed: `None` is "no reading", never 0 V
    battery_valid: bool = False
```

The flags are not decoration. `distance_cm=100` with `distance_valid=False` is **not** "clear at
one metre" — it is "no measurement", and downstream logic must branch on the flag before the value.
`SensorReading.from_snapshot()` adapts the HAL's `SensorSnapshot` to this shape, so a module never
touches the vendor object.

The same rule reaches the snapshot itself: [`perception`, key by key](#4-context-keys) names each
key's companion flag, and a falsy one means that key is `distance_valid=False` — the value is
carried for whoever wants to log it, not believed by whoever would act on it.

**IMU units.** `acc` is in **g** and `gyro` in **deg/s**. `PidogHAL` converts the vendor's raw counts
at the boundary (`hal/vendor.py::to_physical`: 16384 LSB/g and 16.4 LSB/deg/s, or the sensor's own
`acc_scale`/`gyro_scale` when a calibration is stored). Until #258 it published the counts themselves,
so `orientation.gyro_scale: 1.0` integrated a heading roughly 16x too fast.

`|acc|` is 1 g when the dog is at rest. `python -m tools.hardware_checkup --skip-motion` prints an
`imu_gravity` line and warns when it is not 1.00 g ± 0.25: that means the accelerometer offsets were
never saved, and pitch, roll and the tilt latch are all biased by the same amount.

### `ScanReading` — `navigation/scanning.py:34`

```python
@dataclass(frozen=True)
class ScanReading:
    mode: str                                        # "sweep" | "three_way"
    data: dict[int, float] | dict[str, float]
    timestamp: float
```

`to_dict()` is the published form: a sweep becomes `{"mode", "timestamp", "angles": {angle: cm}}`,
and a three-way scan flattens to `{"mode", "timestamp", "left", "right", "forward"}`.

---

## 6. Configuration sections

`config/settings.jsonc` has two top-level blocks. `modules` holds only `enabled`/`required` per module;
everything you tune lives under `settings`:

| Section | Holds |
|---|---|
| `loop` | `tick_hz`, `max_cycles` |
| `sensors` | `poll_hz`, history length, distance sampling and filtering |
| `perception` | fusion thresholds |
| `navigation` | scan cadence, `turn_cooldown_s`, `safe_distance_cm`, stuck recovery |
| `mapping` | home map, occupancy grid, opening scoring |
| `behavior` | action sets, cooldowns, autonomy, micro-idle, habituation |
| `routines` | `dir` — where the routine files live (`docs/ROUTINES.md`), default `~/.houndmind/routines`; the runner reads it once at start |
| `personality`, `energy`, `emotion` | behaviour bias multipliers |
| `attention` | sound-direction head turns, `cooldown_s` |
| `motors` | `min_action_interval_s`, speed defaults |
| `safety` | emergency distance, tilt thresholds |
| `watchdog` | staleness timeouts, `restart_cooldown_s`, `restart_backoff_factor`, `max_restarts` |
| `balance` | IMU compensation gains |
| `calibration` | servo offsets, `request`, persistence ([§9](#9-calibration-workflow)) |
| `logging` | console/file/JSONL, rotation, trace id |
| `led` | LED priority and colours |
| `performance` | safe mode, `sensor_poll_hz_max` |
| `battery`, `quiet_mode` | voltage thresholds, quiet hours |
| `api` | control plane (`docs/CONTROL_API.md` [§2](CONTROL_API.md#2-endpoints)) |
| `vision_pi4`, `voice_assistant`, `face_recognition`, `semantic_labeler`, `slam_pi4` | Pi4 optional modules |

Validation is strict: an unknown key, a wrong type, or a value outside its documented range is a
**load-time error** with a did-you-mean, and the process exits before hardware opens. A leftover
`settings.<module>.http` block from the pre-8420 servers is exactly this kind of error — delete it.

---

## 7. Configuration examples

Enable the safety module and slow everything down for a bench test:

```jsonc
{
  "profile": "auto",
  "modules": { "safety": { "enabled": true }, "balance": { "enabled": false } },
  "navigation": { "max_speed_cm_s": 10, "turn_cooldown_s": 1.2 },
  "motors": { "min_action_interval_s": 1.0 }
}
```

Make the dog quieter and less twitchy:

```jsonc
{
  "behavior": { "micro_idle_chance": 0.05, "action_cooldown_s": 2.5 },
  "quiet_mode": { "enabled": true }
}
```

Point the runtime at a different file (useful for a second profile without editing the tracked one):

```bash
python -m houndmind_ai --config /home/pi/bench-settings.jsonc
```

---

## 8. Safety defaults and onboarding

Two different things share the word "safety", and conflating them is how the old documentation went
wrong:

- **`act/interlock.py` — the mandatory interlock.** Always applied by `motion_gateway` to every
  command, from every source. It cannot be disabled from configuration. It is what refuses forward
  motion into an obstacle, refuses motion from a tilted dog, refuses below `min_battery_v`, and clamps
  speed. Nothing you set in `settings.jsonc` turns it off.
- **`modules.safety` — the optional safety module.** Ships **disabled**. It is the higher-level
  emergency-backing behaviour: it publishes a `system` intent when it wants the dog to retreat. That
  is the piece you enable deliberately, after validation.

Because the interlock is always live, the bench procedure is about the *dog*, not the config:

1. `python -m tools.hardware_checkup --skip-motion` — validates sensors with no movement at all.
2. Copy `config/settings.jsonc` to a bench file and set `modules.safety.enabled = true` there.
3. `python -m tools.smoke_test --cycles 3 --tick-hz 5` — the loop and the sensors, no motion
   (`scan_latest` and `mapping_openings` need `--include-motion`).
4. Only then run with movement, dog on blocks or held, and one hand on `Ctrl-C`.
5. Enable `modules.balance` last, and only after the IMU calibration looks sane.

Never widen `emergency_stop_cm`, `tilt_latch_deg` or `min_battery_v` to make a test pass. They live in
`InterlockLimits` precisely so they are not editable from config, and if you find yourself wanting to
change them, the sensor is probably lying to you — check `device` validity instead.

The one exception runs the other way: `settings.movement.min_battery_v` may be **raised** to protect
a pack you know is tired (the loader refuses anything under 6.4 V, #208). It ships at 7.6 V for that
reason — a gait rebooted the bench dog twice with the pack idle at 7.85 V (#292) — so the compiled
floor is the widest the envelope may ever be, not the value to run. Narrowing the envelope is a
decision about your hardware; widening it is a decision about your servos.

---

## 9. Calibration workflow

Calibration is **request-driven**. There is no CLI subcommand and no HTTP route that runs it, because
every calibration moves servos.

Trigger it either in config:

```jsonc
"calibration": { "request": "servo_zero" }
```

or at runtime, which is how a test does it:

```python
context.set("calibration_request", "servo_zero")
```

Supported requests (`calibration/workflow.py`): `servo_zero`, `wall_follow`, `corner_seek`,
`landmark_align`. The module reads `context["calibration_request"]` first, then
`settings.calibration.request`, and publishes the outcome as `calibration_result`.

`servo_zero` reads the trim the hardware already has through `context["hal"]`
(`DogHAL.read_offsets()`). It never writes and never moves the dog. The joints are named in the
vendor's own list order (`hal/iface.py`, `SERVO_GROUPS`):

| Group | Names |
|---|---|
| legs | `lf_shoulder` `lf_leg` `rf_shoulder` `rf_leg` `lh_shoulder` `lh_leg` `rh_shoulder` `rh_leg` |
| head | `head_yaw` `head_roll` `head_pitch` |
| tail | `tail` |

Writing goes through `DogHAL.apply_offsets()`: values are clamped to ±20°, each group is merged
over the values already loaded — the vendor setter replaces a whole list, so one joint must not
zero the rest — and a group whose current values cannot be read is skipped rather than written as
zeros. Saving a trim is not a move; the dog takes the new offsets on its next motion command.

The vendor's interactive step is `examples/0_calibration.py` in the `pidog` package (keys `1`-`8`
for the legs, `9`/`0`/`-` for yaw/roll/pitch, `=` for the tail). HoundMind's own step is
non-interactive — `python -m tools.calibrate_servos` (`docs/TOOLS.md` [§12](TOOLS.md#12-calibrate_servos)): it prints this table with
the values the dog has loaded, takes `--set joint=deg` and writes only with `--apply`. Both write the
same vendor file, so use one of them, not both in one session.

Persistence and application, both off the critical path:

| Key | Default | Meaning |
|---|---|---|
| `servo_zero_offsets` | `{}` | The stored offsets, name → degrees. Filled by a calibration run. |
| `persist_enabled` | `true` | Write results to disk |
| `persist_path` | `data/calibration.json` | Where |
| `auto_apply_servo_offsets` | `false` | Apply the stored offsets on start |

Treat `servo_zero_offsets` as user data: read it, never overwrite it, never invent a default for a
servo you have not measured. A wrong offset is a servo driven into its mechanical stop.

---

## 10. Logging and diagnostics

- Console log plus `logs/houndmind.log` (rotating), and JSONL events in `logs/events.jsonl` when
  `logging.enable_file` / event logging are on. `docs/LOGGING.md` is the runbook.
- Correlate a run with a trace id: `export HOUNDMIND_TRACE_ID=trace-12345` (PowerShell:
  `$env:HOUNDMIND_TRACE_ID='trace-12345'`). It flows into every log record through the context filter
  and into `trace_id` in `GET /api/v1/state`.
- Support bundle from the shell:

```bash
python -m tools.collect_support_bundle /tmp/support.zip
```

- Or over the network, with the `admin` scope: `GET /api/v1/support-bundle`. The two bundles are **not
  identical** — the HTTP one carries state, modules, redacted config, audit and sessions but not log
  files; the CLI one carries `logs/` and a `metadata.json`. `docs/LOGGING.md` has both shapes.

Query the event log with `jq`:

```bash
jq -r 'select(.event=="navigation_decision") | .timestamp + " " + .payload.direction' logs/events.jsonl
```

Module health, without reading a log at all:

```bash
curl -H "Authorization: Bearer $(cat ~/.houndmind/api_token)" \
     http://127.0.0.1:8420/api/v1/modules
```

(With `settings.api.tls_enabled` on, that is `https://` plus `--cacert ~/.houndmind/tls/cert.pem`;
`GET /api/v1/meta` reports the `scheme` the server is actually serving.)

---

## 11. Autonomy, attention and behaviour tuning

- **Autonomy** — `settings.behavior.autonomy_*`. Modes are `idle`, `patrol`, `play`, `rest`; weights
  bias the choice and `energy` gates it through `autonomy_rest_energy_max` /
  `autonomy_play_energy_min`.
- **Micro-idle** — `micro_idle_interval_s` and `micro_idle_chance` control the small "alive" actions
  (`shake head`, `wag tail`, `stretch`). They are safe and never gate navigation.
- **Habituation** — `settings.habituation` repeats fewer of the same action over time; the effect is
  bounded so the dog never stops responding to a genuine trigger.
- **Personality** — `settings.personality.{curiosity,sociability,activity}` multiply exploratory,
  interactive and locomotor selection. `apply_to_autonomy: false` opts out entirely.
- **Attention** — sound direction turns the head; `attention.cooldown_s` is what stops the oscillation
  you get without it. `AttentionModule` emits `led_request:attention` alongside.

Energy and emotion (`optional/energy_emotion.py`) feed the same bias inputs, so enabling them changes
which actions the dog picks — motion-adjacent, not a display-only module. It derives from
`energy_level` rather than producing it: with `settings.energy.enabled: false` the reading does not
exist and the module publishes nothing.

---

## 12. Mapping and path planning

- `MappingModule` accumulates `mapping_openings` and safe paths from scans, and can write a home-map
  snapshot under `data/maps/` when enabled.
- `mapping/path_planner.py::astar` is a library helper over a grid, with **no caller in the runtime**:
  the hook and the `path_planning` key were retired because a route needs a position estimate this
  stack does not have (#121). The example below is the whole feature surface. Goal-directed walking
  is `navigation/place_navigator.py` (`docs/CONTROL_API.md` [§8](CONTROL_API.md#8-places)).
- `mapping/room_scale.py::RoomScale` is the same shape of helper for the stride: a room the user drew
  supplies the reference, so a walk inside it measures `step_cm` with no tape measure and no
  dimension the user has to type (#285, H4). Fed samples, it returns `scale_progress`; it ticks
  nothing and publishes nothing. Its sufficiency table is in
  [FEATURES_GUIDE.md §6](FEATURES_GUIDE.md#6-mapping).

```python
from houndmind_ai.mapping.path_planner import astar

grid = [
    [0, 0, 0, 1, 0],
    [1, 1, 0, 1, 0],
    [0, 0, 0, 0, 0],
    [0, 1, 1, 1, 0],
    [0, 0, 0, 0, 0],
]
path = astar(grid, (0, 0), (4, 4))
# [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (3, 2), (4, 2), (4, 3), (4, 4)]
```

Use the public module API and the hook; do not call `_`-prefixed helpers, and do not add a second
planner. There is a runnable demo in `examples/houndmind_mapping_demo.py`.

---

## 13. On-device validation

The checklist in `docs/INSTALL.md` is the full version. The short version, in order:

1. Sensors stable at rest — no ultrasonic spikes, IMU not drifting.
2. Scans: three-way returns three valid readings, sweep returns to centre.
3. Navigation recovery: obstacle turns, stuck handling, no oscillation.
4. Watchdog holds and releases on stale data.
5. Logging writes, and a support bundle builds.

No item passes because it "seemed fine" on a workstation. `FakeDogHAL` proves the logic, not the dog.

---

## 14. Extending the system

To add a module:

1. Create it in the package it belongs to (`navigation/`, `optional/`, …) — rarely a new top-level
   package, and never a second implementation of an existing one.
2. Subclass `Module` with `start(context)`, `tick(context)`, `stop(context)`. Constructor is
   `(name, enabled=True, required=False, **kwargs)` and must tolerate unknown kwargs.
3. **Register it.** `main.build_registry()` is a manual list — a module that is not in it never runs,
   however correct it is.
4. Add its config section to `kernel/config_schema.py` **and** a commented default to
   `config/settings.jsonc`. An unregistered key is a load error, so this step is not optional.
5. Document it: `docs/FEATURES_GUIDE.md` (what it does, how to disable) and [§4](FEATURES_GUIDE.md#4-scanning) of this file if it
   publishes a context key.
6. Test it against `FakeDogHAL`, with no dog attached.

A logger module, done correctly:

```python
from __future__ import annotations

import logging

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class HeartbeatLogger(Module):
    def tick(self, context) -> None:
        tick = context.get("tick")
        if isinstance(tick, int) and tick % 10 == 0:
            logger.debug("heartbeat tick=%s", tick)  # logging, never print
```

`print` does not belong in `src/houndmind_ai/`. Log with `%s` placeholders so the arguments are only
formatted when the level is enabled, and `self.disable("missing dependency: x")` rather than raising
when an optional import fails.

---

## 15. Pi4 profile and deferred work

`profile: "pi5"` (or `pi4`) permits the heavy modules; it does not enable them. Each one is still
`enabled: false` in the shipped config, and each needs its own install step
(`docs/FEATURES_GUIDE.md` [§19](FEATURES_GUIDE.md#19-voice-assistant-pi4)–23, and `scripts/install_rtabmap_pi4.md` for RTAB-Map).

The one-line version: if it needs `numpy` and a camera, it is not something to switch on before the
board has been measured. Nothing in this list has been measured on a Pi 5 yet, which is why `pi5`
ships the same cadence as `pi4` rather than a faster one.

---

## 16. Developer commands

Run everything from the repository root with the package importable. CI uses Python **3.11**; a newer
local interpreter proves the tooling runs, not that the package is supported on it (`pyproject.toml`
declares `>=3.11,<3.14`).

```bash
pip install -e .[lite,dev]                 # pytest, ruff, mypy, json5

PYTHONPATH=src python -m pytest -q         # the suite
PYTHONPATH=src python -m pytest -q tests/test_gateway.py   # one file

python -m ruff check src                   # src only; CI does not lint tests
python -m mypy src --ignore-missing-imports
```

On Windows PowerShell, set the path once per session instead:

```powershell
$env:PYTHONPATH='src'; python -m pytest -q
```

Device tools (never run by a test, and `hardware_checkup` moves the dog without `--skip-motion`):

```bash
python -m tools.calibrate_servos            # read-only: the 12 joints and the saved trim
python -m tools.hardware_checkup --skip-motion
python -m tools.smoke_test
python -m tools.camera_check --list-devices
python -m tools.collect_support_bundle /tmp/support.zip
```

Replaying a recorded session — no dog, no motion. With `logging.decision_log_file_enabled: true` the
runtime writes `logs/houndmind_decisions.jsonl`; this tool serves that history through the real
control plane, so a client can be built against a dog that is not on the desk:

```bash
python -m tools.replay_decisions logs/houndmind_decisions.jsonl --check   # validate, serve nothing
python -m tools.replay_decisions logs/houndmind_decisions.jsonl            # 1x, then exit
python -m tools.replay_decisions logs/houndmind_decisions.jsonl --speed 0 --limit 300 --linger 60
```

`GET /api/v1/decisions`, `state.decision` and the `decision` socket event behave exactly as they do
on the device. Three limits, all deliberate: the record carries no touch or sound reading, so those
stay invalid in `state.sensors`; `POST /command` answers 503, because nothing drains the command bus;
and `decision.ts` is the device's monotonic clock, not this machine's. The token file *path* is
printed, never the token.

A camera clip is the one dataset a SLAM claim can be measured on, so it is recorded once and
replayed everywhere. `tools.camera_record` starts the runtime with every motion-capable module
switched off, borrows the frame `services/camera.py` already holds — it does not open the camera a
second time — and writes `clip.jsonl` plus `manifest.json`: resolution, cadence, IMU magnitude and
gyro bias, the host and the commit under test (`houndmind_ai/optional/slam_clip.py`). It needs the
camera, not the legs, and it never binds the control plane:

```bash
python -m tools.camera_record --seconds 60 --out data/clips/room-01
python -m tools.camera_record --seconds 5 --frames 20 --out /tmp/clip   # a short check
```

`tools.slam_replay` has two halves. `--verify` needs no camera, no SLAM library and no OpenCV — the
dimensions come from each frame's own JPEG header — and refuses a clip by name when the count is not
the one the manifest promises, a line is not a JPEG, or the cadence is too irregular to pace
(`--tolerance-pct`, default 25). `--host pi|pi5|pc` publishes the clip into the **real** runtime with
`slam_pi4` switched on, so the number includes the loop rather than a bare benchmark: a frame goes on
the context when its own recorded timestamp comes round (`--speed` compresses the clip without
speeding the loop), every motion-capable module stays off, and `hal_sensors` stays off too because the
IMU has to come from the clip. Each run writes one JSON report beside the clip — sustained fps, CPU
per core, temperature before and after, `slam_pi4`'s tick percentiles, the ticks that overran the
budget, and the frames the module buffered, skipped, processed, dropped or failed (`slam_stats`) — plus a
verdict sentence. A host without OpenCV gets the JPEG bytes rather than a decoded array, and the
report says so: a backend that cannot read them processes nothing, which is a finding, not a crash:

```bash
python -m tools.slam_replay --verify data/clips/room-01
python -m tools.slam_replay data/clips/room-01 --host pi --backend rtabmap
python -m tools.slam_replay data/clips/room-01 --host pc --json            # one row of the table
```

Installer:

```bash
bash scripts/install_houndmind.sh              # interactive
RUN_I2SAMP=1 bash scripts/install_houndmind.sh # non-interactive, configures the I2S mic
```