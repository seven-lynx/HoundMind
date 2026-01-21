# HoundMind Programming Guide (Pi3 Hardware-Only)

Version: v2026.01.18 • Author: 7Lynx

This guide helps developers run, tune, and extend HoundMind on the SunFounder PiDog (Pi3 target). It focuses on practical examples, configuration snippets, and extension points. Simulation mode is no longer supported; use hardware or the `--dry-run` example below.

## 1) Quick Start
- Prepare: edit `config/settings.jsonc` to set `profile: "pi3"` (or rely on the default).
- Create and activate a venv, install minimal requirements:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-lite.txt
python -m pip install -e .
```

- Run the main runtime (safe default profile):

Run HoundMind from the install virtualenv. Recommended methods:

```bash
# Activate the venv then run
source .venv/bin/activate
python -m houndmind_ai

# Or run with the venv Python directly
.venv/bin/python -m houndmind_ai
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m houndmind_ai
```

- Dry-run example (imports only, no hardware):

```bash
python -c "import importlib; importlib.import_module('houndmind_ai'); print('houndmind_ai import OK')"
```

## 2) Runtime Model (practical)
HoundMind runs a fixed-tick loop. Each tick collects sensor inputs, performs perception and scanning, updates navigation and behavior, and finally emits motor actions. Key developer concepts:

- `RuntimeContext`: shared dictionary-like object modules read/write keys on each tick (e.g. `sensor_reading`, `scan_latest`, `navigation_action`).
- `Module` lifecycle: implement `start(context)`, `tick(context)`, and `stop()` for new modules (see example below).
- Tick rate: configured in `config/settings.jsonc` under `core.tick_hz` — lowering it reduces CPU use on Pi3.

Example: minimal module skeleton

```python
from houndmind_ai.core.module import Module

class ExampleModule(Module):
    def start(self, context):
        context.set('example.started', True)

    def tick(self, context):
        # read sensor state
        sr = context.get('sensor_reading')
        # publish a debug snapshot
        context.set('example.last', {'tick': context.get('tick')})

    def stop(self):
        pass
```

Register modules via `houndmind_ai.main.build_modules` or by adding to the runtime module registry.

## 3) Modules Overview (Pi3)
This section expands each high-level module with what to expect and what to test.

Core
- `core/runtime.py`: loop management and module lifecycle. Watch for tick overruns in logs (`tick_latency_ms`).
- `core/config.py`: JSONC parsing and config profile handling (pi3 vs pi4).

HAL (Hardware Abstraction Layer)
- Sensors: ultrasonic, touch, IMU, and sound-direction. Key context keys: `sensor_reading`, `sensors`, `sensor_health`.
- Motors: action submission via `context.set('behavior_action', action_dict)` and the motors adapter converts to `pidog` calls.

Navigation
- Scanning helpers: `three_way_scan()` and sweep helpers return `scan_reading` structures. Prefer `scan_quality` checks before trusting long-range values.
- Obstacle avoidance: uses scan clustering and a no-go memory; tune `navigation.turn_cooldown_s` for oscillation prevention.

Mapping
- Lightweight mapping records openings and safe paths. Home-map snapshots are stored as JSON under `data/maps/` when enabled.
- Path planning hook exists but full A* global planning is reserved for Pi4.

Behavior
- Behavior registry and action catalog: actions live in `config/actions.jsonc`. Use `behavior_library` to add new scripted actions.
- Autonomy settings are in `settings.behavior` and can be tuned for energy thresholds and mode weights.

Safety & Watchdogs
- Safety: emergency stop and tilt protection (disabled by default). Enable only after on-device validation.
- Watchdogs: per-module heartbeats and a service watchdog restart policy exist to prevent thrashing.

Optional (Disabled by Default)
- Vision, voice, and heavy mapping modules are disabled in the Pi3 profile; enable only in `pi4` profile.

## 4) Configuration (examples)
All settings are in `config/settings.jsonc`. Small example snippets for common edits:

Enable safety and conservative speeds for testing:

```jsonc
{
  "profile": "pi3",
  "modules": { "safety": { "enabled": true }, "balance": { "enabled": false } },
  "navigation": { "max_speed_cm_s": 10, "turn_cooldown_s": 1.2 }
}
```

Enable a safe-mode preset (reduce scan cadence and movement): add a `pi3_safe` profile or set these keys under `performance.safe_mode`.

JSON Schema: For contributors, we recommend adding a `schema/settings.schema.json` and validating at runtime, but the code currently performs runtime checks and warns for missing keys.

## 5) Safety Defaults & Onboarding
Because safety features are sensitive, follow this onboarding checklist on a bench before enabling automatic emergency stop:

1. Run `python -m tools.hardware_checkup --skip-motion` to validate sensors.
2. Enable `modules.safety.enabled=true` in a local copy of `config/settings.jsonc`.
3. Run smoke tests: `python -m tools.smoke_test --cycles 3 --tick-hz 5`.
4. Physically restrain PiDog (or keep it off the floor) when first enabling emergency stop behaviors.

Only enable `balance` after validating IMU calibration results.

## 6) Calibration Workflow (practical)
Calibration is request-driven via the config or CLI. Examples:

Request servo zero calibration in `config/settings.jsonc`:

```jsonc
"calibration": { "request": "servo_zero" }
```

Run the runtime and watch `data/calibration.json` for results. For iterative calibration, use the small helper:

```bash
python -m tools.installer_verify --calibrate=servo_zero
```

Calibration results are persisted under `data/calibration.json` by default.

## 7) Logging & Diagnostics
- Event logs are JSONL by default in `logs/events.jsonl`. Use `jq` to query.
- Add a trace id for a run to correlate logs: `export HOUNDMIND_TRACE_ID=trace-12345` (PowerShell: `setx HOUNDMIND_TRACE_ID trace-12345`).

Example: collect support bundle (recommended when debugging hardware issues):

```bash
python -m tools.collect_support_bundle /tmp/support.zip
```

Quick `jq` to show navigation decisions:

```bash
jq -r 'select(.event=="navigation_decision") | .timestamp + " " + .payload.direction' logs/events.jsonl
```

## 8) Autonomy, Attention & Behavior Tuning
- Autonomy modes (idle/patrol/play/rest) follow `settings.behavior.autonomy_weights` and `settings.energy` when enabled.
- Tune `settings.behavior.micro_idle_interval_s` and `micro_idle_chance` to control idle behavior frequency.
- Sound attention publishes `sound_direction` into perception; the head-turning module respects `attention.cooldown_s` to avoid rapid oscillation.

## 9) On-Device Validation (checklist)
Follow `docs/PI3_VALIDATION.md` for a runnable checklist. Key items:
- Sensor stability
- Scan fidelity (three-way + sweep)
- Navigation recovery (stuck handling)
- Logging & support bundle generation

## 10) Extending the System (how-to)
To add a new module:

1. Create a new file under `src/houndmind_ai/your_module/`
2. Implement a `Module` subclass with `start`, `tick`, and `stop`.
3. Register the module in `houndmind_ai.main.build_modules()` by importing and appending to the module list.
4. Add config defaults in `config/settings.jsonc` and document keys in `docs/`.

Example: adding a simple logger module

```python
from houndmind_ai.core.module import Module

class HeartbeatLogger(Module):
    def tick(self, context):
        tick = context.get('tick')
        if tick % 10 == 0:
            print('heartbeat', tick)

# register in build_modules
```

Testing: write a unit test that imports your module and exercises `start`/`tick` with a mocked `RuntimeContext` (see `tests/` for patterns).

## 11) Pi4 Profile and Deferred Work
Use profile `pi4` to enable heavy modules. See `docs/FEATURES_GUIDE.md` for Pi4-specific setup and SLAM/vision guidance. On Pi3 keep those modules disabled by default.

## 12) Helpful Developer Commands

Run unit tests:

```bash
pytest -q
```

Run linters (requires dev deps):

```bash
ruff src tests
mypy src || true
```

Run installer in interactive mode (prompts to run i2samp):

```bash
bash scripts/install_houndmind.sh
```

Run installer non-interactively (also run i2samp):

```bash
RUN_I2SAMP=1 bash scripts/install_houndmind.sh
```

## 13) Contacts & Contribution
- Add `CONTRIBUTING.md` (recommended) with PR and testing guidance.
- For device-specific issues attach a support bundle and include the `metadata.json` trace id.

---

If you want, I can also:
- add runnable `examples/pi3_demo.py` and a `docs/PI3_DEVICE_SETUP.md` with step-by-step photos/commands, or
- create a `settings.schema.json` and a runtime validator to strengthen config checks.

Which would you like me to do next?
