# HoundMind Programming Guide

Status: **guide** — how to run, tune and extend the runtime. The authoritative version of every
default is `config/settings.jsonc`; this file explains it.
Version: v2026.01.18 • Author: 7Lynx
Pairs with: `docs/ARCHITECTURE.md` (why), `docs/FEATURES_GUIDE.md` (what each module does),
`docs/PIDOG_PROGRAMMING_GUIDE.md` (the vendor library underneath)

HoundMind is an add-on to the SunFounder PiDog software: install the vendor library first, then
HoundMind into the **same** virtualenv. Simulation mode is not supported — there is no dry-run that
moves a virtual dog, so everything here either runs against hardware or against `FakeDogHAL` in a
test.

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
| `loop.tick_hz` | `5` (`pi3`) / `10` (`pi4`) | Decision-loop rate. Lower is safer and cheaper on a Pi 3. |
| `sensors.poll_hz` | `10` | Sensor sampling rate, capped by `performance.sensor_poll_hz_max`. |
| `navigation.scan_interval_s` | `0.3` | How often the sweep runs; bounded by `scan_interval_min_s` / `_max_s`. |
| `behavior.idle_action`, `behavior.action_sets` | see config | What the dog does with no reason to do anything else. |
| `motors.min_action_interval_s` | `0.6` | Floor between motor commands. |
| `loop.max_cycles` | `null` | `null` means run forever, which is the only sane default for a service. |

### Autonomy tuning

HoundMind can patrol, play and rest without input. The knobs all live under `settings.behavior`:

- `autonomy_enabled`, `autonomy_interval_s`, `autonomy_modes`, `autonomy_weights`
- `autonomy_rest_energy_max`, `autonomy_play_energy_min`

```jsonc
"behavior": {
  "autonomy_enabled": true,
  "autonomy_interval_s": 8.0,
  "autonomy_modes": ["idle", "patrol", "play", "rest"],
  "autonomy_weights": {"idle": 0.4, "patrol": 0.3, "play": 0.2, "rest": 0.1},
  "autonomy_rest_energy_max": 0.35,
  "autonomy_play_energy_min": 0.75
}
```

### Validating and stopping

Bench validation is `docs/PI3_VALIDATION.md`. Optional modules stay off until it passes. Stop the
runtime with `Ctrl-C` and let the process exit: the module `stop()` hooks run and the HAL closes the
servo bus. Do not kill -9 a moving dog.

---

## 2. Runtime model

HoundMind runs a fixed-tick loop. Each tick reads sensors, fuses them into perception, updates
scanning/navigation/behavior, and finally emits at most one motion command.

- **`RuntimeContext`** — the dict-like object every module reads and writes. Keys are contracts;
  §4 is the list.
- **`Module` lifecycle** — `start(context)`, `tick(context)`, `stop(context)`. A module that cannot
  start calls `self.disable(reason)` and stops; it does not raise unless it was registered
  `required=True`.
- **Tick rate** — `loop.tick_hz`. Lowering it cuts CPU on a Pi 3 and costs reaction time.
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
before the value. Registration is manual — §14.

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
- `navigation/local_planner.py` — `local_plan`, `mapping_recommendation`.
- `mapping/mapper.py` — openings, safe paths, optional home-map snapshots.
- `behavior/` — FSM, action library, registry, attention and habituation. Actions come from
  `config/actions.jsonc`.

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

**Sensors and perception**

| Key | Type |
|---|---|
| `hal` | `DogHAL \| None` — the only path to hardware |
| `sensor_reading` | `SensorReading` (§5) |
| `sensors`, `sensor_history`, `sensor_health` | `dict` |
| `scan_reading` | `ScanReading` (§5) |
| `scan_latest`, `scan_quality`, `scan_history` | `dict` |
| `scan_duration_s` | `float` — measured sweep length |
| `scan_in_flight` | `bool` |
| `scan_worker`, `scan_service` | worker and service handles |
| `current_heading` | `float` — degrees |

**Navigation, mapping and behaviour**

| Key | Type |
|---|---|
| `navigation_decision`, `navigation_turn`, `navigation_followup` | `dict` |
| `mapping_openings`, `mapping_state` | `dict` |
| `path_planning`, `path_planning_hook` | `list` / callable |
| `behavior_override` | `str \| None` |
| `runtime_mode` | `idle` \| `patrol` \| `manual` \| `rest` |

**Motion** — the only keys `hal_motors` reads

| Key | Type |
|---|---|
| `intent_board` | `IntentBoard` — what each source asks for right now |
| `motion_command` | `dict \| None` — the winning command |
| `motion_verdict` | `dict \| None` — accepted/vetoed, with reason |
| `motion_cancel` | `list` — lower-priority intents this tick displaced |
| `tilt_latched` | `bool` |

**Safety, health, LEDs**

| Key | Type |
|---|---|
| `safety_active`, `emergency_stop_active` | `bool` |
| `tilt_warning` | `dict` (`pitch`, `roll`) |
| `watchdog_hold`, `watchdog_status` | `dict` |
| `health_status`, `health_degraded` | `dict`, `bool` |
| `scan_interval_override_s` | `float \| None` |
| `led_request:safety` \| `:navigation` \| `:attention` \| `:emotion` \| `:health` | `dict` |

**Calibration and optional sources**

| Key | Type |
|---|---|
| `calibration_request`, `calibration_result` | `str`, `dict` (§9) |
| `localization_confidence` | `float` |
| `vision_frame`, `vision_frame_jpeg` | array, `bytes` |
| `face_recognition_command` | `dict` |
| `voice_text`, `voice_command` | `str` |
| `slam_map_data`, `slam_trajectory` | `dict` |

**Removed, and not coming back:** `safety_action`, `watchdog_action`, `navigation_action`,
`behavior_action`. Producers publish to the `IntentBoard` instead, and `hal_motors` never reads a
producer key.

---

## 5. Sensor data types

### `SensorReading` — `hal/sensors.py:48`

```python
@dataclass(frozen=True)
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
```

The four flags are not decoration. `distance_cm=100` with `distance_valid=False` is **not** "clear at
one metre" — it is "no measurement", and downstream logic must branch on the flag before the value.
`SensorReading.from_snapshot()` adapts the HAL's `SensorSnapshot` to this shape, so a module never
touches the vendor object.

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
| `mapping` | home map, `path_planning_enabled`, `goal` |
| `behavior` | action sets, cooldowns, autonomy, micro-idle, habituation |
| `personality`, `energy`, `emotion` | behaviour bias multipliers |
| `attention` | sound-direction head turns, `cooldown_s` |
| `motors` | `min_action_interval_s`, speed defaults |
| `safety` | emergency distance, tilt thresholds |
| `watchdog` | staleness timeouts, `restart_cooldown_s`, `restart_backoff_factor`, `max_restarts` |
| `balance` | IMU compensation gains |
| `calibration` | servo offsets, `request`, persistence (§9) |
| `logging` | console/file/JSONL, rotation, trace id |
| `led` | LED priority and colours |
| `performance` | safe mode, `sensor_poll_hz_max` |
| `battery`, `quiet_mode` | voltage thresholds, quiet hours |
| `api` | control plane (`docs/CONTROL_API.md` §2) |
| `vision_pi4`, `voice_assistant`, `face_recognition`, `semantic_labeler`, `slam_pi4` | Pi4 optional modules |

Validation is strict: an unknown key, a wrong type, or a value outside its documented range is a
**load-time error** with a did-you-mean, and the process exits before hardware opens. A leftover
`settings.<module>.http` block from the pre-8420 servers is exactly this kind of error — delete it.

---

## 7. Configuration examples

Enable the safety module and slow everything down for a bench test:

```jsonc
{
  "profile": "pi3",
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
3. `python -m tools.smoke_test --cycles 3 --tick-hz 5` — sensors, scan and mapping, no motion.
4. Only then run with movement, dog on blocks or held, and one hand on `Ctrl-C`.
5. Enable `modules.balance` last, and only after the IMU calibration looks sane.

Never widen `emergency_stop_cm`, `tilt_latch_deg` or `min_battery_v` to make a test pass. They live in
`InterlockLimits` precisely so they are not editable from config, and if you find yourself wanting to
change them, the sensor is probably lying to you — check `device` validity instead.

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
which actions the dog picks — motion-adjacent, not a display-only module.

---

## 12. Mapping and path planning

- `MappingModule` accumulates `mapping_openings` and safe paths from scans, and can write a home-map
  snapshot under `data/maps/` when enabled.
- Path planning is an A* hook over a grid (`mapping/path_planner.py`). Set
  `"path_planning_enabled": true` and `"goal": [x, y]` under `mapping`; the runtime registers the
  default hook as `path_planning_hook`, `MappingModule` calls it each tick, and the result appears as
  `path_planning`.

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

`docs/PI3_VALIDATION.md` is the checklist. The short version, in order:

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
5. Document it: `docs/FEATURES_GUIDE.md` (what it does, how to disable) and §4 of this file if it
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

`profile: "pi4"` raises the loop to 10 Hz and permits the heavy modules; it does not enable them. Each
one is still `enabled: false` in the shipped config, and each needs its own install step
(`docs/FEATURES_GUIDE.md` §19–23, and `scripts/install_rtabmap_pi4.md` for RTAB-Map).

On a Pi 3 keep all of them off. The one-line version: if it needs `numpy` and a camera, it is not a
Pi 3 feature.

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
python -m tools.hardware_checkup --skip-motion
python -m tools.smoke_test
python -m tools.camera_check --list-devices
python -m tools.collect_support_bundle /tmp/support.zip
```

Installer:

```bash
bash scripts/install_houndmind.sh              # interactive
RUN_I2SAMP=1 bash scripts/install_houndmind.sh # non-interactive, configures the I2S mic
```