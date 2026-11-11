# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and adheres to semantic-ish sections.

Current Release: v2026.01.18 • Author: 7Lynx


## [Unreleased]

### Added
- `kernel/state.py`: a lock-protected state store behind `RuntimeContext`. Sensor and scan
  services publish from daemon threads while the loop reads, so the shared mapping now has a
  lock and snapshot reads instead of relying on `dict` operations being individually atomic.
- `kernel/registry.py`: modules are registered with a `Capability`, and asking for the sole
  provider of an exclusive capability (the servo bus) raises instead of guessing.
- `act/gateway.py`: one motion path. The gateway resolves `safety` > `watchdog` > `navigation` >
  `behavior` in a single declared place, sends the winner through the interlock, and publishes
  `motion_command` / `motion_verdict` / `tilt_latched`.
- `kernel/config_schema.py`: config validation is enforced, not advisory. Unknown keys are an
  error with a did-you-mean suggestion.
- `hal/vendor.py`: `PidogHAL`, the vendor-backed `DogHAL`, plus `hal/module.py`: `HalModule` owns
  the dog and publishes it as the context key `hal`. Before this, `hal/sensors.py`,
  `hal/motors.py` and `navigation/scanning.py` each opened their own `Pidog()` and raced over
  one servo bus; the last one to start also won the `pidog_owner` key that decided who closed it.
- `hal/sensors.py`: `SensorService` polls a `DogHAL` instead of a vendor object, and the sensor
  signal conditioning (multi-sample median, outlier rejection, debounce, EMA, IMU low-pass)
  lives in `PidogHAL` next to the reads it belongs to.
- `DogHAL` gained `sample_distance()` (a head scan needs the distance *after* the head moved) and
  `apply_offsets()` (calibration offsets are user data, applied by the owner of the servos).
  `SensorSnapshot` carries `acc`, `gyro` and `sound_detected`, which consumers already read.
- `main.build_registry(config, hal=...)` injects a `DogHAL`; `FakeDogHAL` is now enough to run
  the sensor, scan, LED, head and posture paths, and `tests/test_runtime_tick.py` no longer
  carries a `HARDWARE_MODULES` exclusion list.
- `kernel/config_schema.py`: `settings` is validated section by section. Every section the
  repo ships — `attention`, `balance`, `battery`, `behavior`, `calibration`, `emotion`,
  `energy`, `face_recognition`, `habituation`, `led`, `logging`, `mapping`, `motors`,
  `movement`, `navigation`, `orientation`, `perception`, `performance`, `personality`,
  `quiet_mode`, `safety`, `semantic_labeler`, `sensor_health`, `sensors`, `service_watchdog`,
  `slam_pi4`, `telemetry_dashboard`, `vision_pi4`, `voice_assistant`, `watchdog` — rejects an
  unknown key (with a suggestion) and a value of the wrong type, and profile overrides are
  validated the same way. An unknown *section* is an error too, so `settings.voice` instead of
  `settings.voice_assistant` no longer loads a table nothing reads. Enum-valued keys carry the
  choices the code branches on, and nullable keys say so.
- `settings.performance.runtime_ema_alpha` is a documented key (default `0.2`): the runtime
  read it with a hard-coded fallback but the shipped file never mentioned it.
- `settings.logging.console_level` is an accepted key, so the console can be quieter than the
  file without editing code.

### Changed
- `hal_motors` executes `motion_command` only; it no longer merges four context keys by `or` and
  deduplicates on the action string, which had made a `forward` from navigation and one from
  behaviour indistinguishable.
- `attention`, `led_manager`, `balance` and `scanning` reach the hardware through `hal.action()`
  instead of grabbing `context["pidog"]` and calling vendor methods themselves. `import pidog` in
  `src/` is now confined to `hal/vendor.py` (plus the optional voice module and the device CLI).
- `calibration/workflow.py` is the one remaining consumer of the raw vendor handle;
  `HalModule` still publishes it as `pidog` so a calibration run behaves as before until the
  wizard is rebuilt.
- `SensorHealthModule` is wired into the runtime (disabled by default, as before).
- Logging reads the keys `config/settings.jsonc` actually ships (`log_level`, `log_file_name`,
  `log_file_backups`, `log_file_max_mb`, `enable_console`, `enable_file`). Previously the
  configured DEBUG level was ignored and rotation was hardcoded to 10 MB.
- Log records carry four whitelisted context fields instead of every key in the runtime context,
  so a log line no longer serialises the whole config, the sensor history and the vendor
  hardware handle.
- The event log JSONL rotates at `logging.event_log_max_mb` (one generation) instead of growing
  until the SD card filled.
- `requires-python` is `>=3.11,<3.14`; Pi 3 support is dropped. `json5` is now a real dependency.
- Ruff is pinned (`0.17.4`) with an explicit rule set.
- `core/config.py` parses JSON5 with `json5` and nothing else. The 60-line comment stripper
  that duplicated it is deleted: it was only there because `json5` used to be optional, and a
  syntax error now names the file it came from instead of a hand-rolled message.
- `core/config.validate_config` is down to the cross-field rules a per-value schema cannot
  express (distance ordering, an interval inside its own bounds, turn speed above walk speed,
  `override_priority` keeping `safety`). The type and range checks it duplicated are gone with
  the schema that enforces them.

### Removed
- `optional/wifi_localization.py` and `modules.wifi_localization`. It shelled out to `netsh wlan
  show networks`, which does not exist on Raspberry Pi OS, had no test, and was never registered.
- Eighteen `settings` keys that nothing in `src/`, `tests/` or `src/tools/` read:
  `navigation.enable_dynamic_scan`, `navigation.dynamic_scan_yaw_max_deg`,
  `navigation.scan_debounce_s`, `navigation.scan_smoothing_alpha`,
  `navigation.planner_influence_weight`, `mapping.safe_path_min_length_cells`, and the whole
  `movement` step/speed table except `turn_degrees_per_step`, `speed_normal` and
  `speed_turn_slow|normal|fast` (`gentle_recovery_speed`, `turn_steps_*`, `walk_steps_*`,
  `backup_steps`, `speed_slow`, `speed_fast`, `speed_emergency`, `step_pause_s`). They were
  documented as tuning knobs and changed nothing; the gentle-recovery threshold that does work
  (`navigation.gentle_recovery_stuck_count`, `navigation.gentle_recovery_cooldown_s`) was read
  by the module but missing from the file, and is now shipped.

### Fixed
- `python -m houndmind_ai` no longer dies with `ModuleNotFoundError: cv2` on an install without
  OpenCV, which included the installer's own lite fallback.
- `loop.max_cycles` defaults to `null`; a fresh install used to run for two seconds and exit.
- `src/tools/smoke_test.py` is no longer collected as a test, so the suite can collect at all.
- `src/houndmind_ai/core` has an `__init__.py`; it was an accidental namespace package that
  package discovery could not see by name.
- The built wheel contains `tools/` and `houndmind_ai/core/`, so the documented
  `python -m tools.*` commands work after a real install.


## [v2026.01.18] - 2026-01-18

### Changed
- Simulation mode (shim/sim) is no longer supported; all features require real PiDog hardware.
- PackMind and CanineCore have been unified into a single system; all features and docs reflect this change.
- Release: bumped version and updated documentation headers to v2026.01.18.
- No functional changes since `v2026.01.16`; this release consolidates docs, metadata, and release notes.
 - Moved developer CLI/tools into a proper package: `src/tools` (removed top-level `tools/` copies). This fixes importability during CI and editable installs.
 - Docs: added troubleshooting and support bundle collection instructions to `docs/INSTALL.md`.
 - Fix: use timezone-aware UTC datetimes in logging and support-bundle metadata to avoid deprecation warnings.

### Notes
- Files updated: `pyproject.toml`, top-level docs and guides (version header updates).
- If you rely on runtime behavior, there were no code changes since the previous release (see v2026.01.16 notes).


## [v2026.01.16] - 2026-01-16

### Added
- Pi4 optional modules: vision feed, face recognition, semantic labeling, SLAM stub, voice assistant enhancements, telemetry dashboard.
- Telemetry performance metrics (FPS, tick latency, CPU/GPU/RAM) and dashboard snapshot integration.
- Pi4 profile overrides with higher tick rates and feature flags.
- Background service watchdog with restart policies (enabled by default, low-impact).
- Install automation and validation helpers plus camera/voice/face CLI tools.

### Changed
- Runtime package renamed from `pidog_ai` to `houndmind_ai` and imports updated.
- Installer flow extended with Pi3/Pi4 presets and dependency verification.
- Docs consolidated and updated across README, install guides, and API reference.
- Default configuration: basic watchdog enabled; safety/throttling features disabled by default for bug testing.

### Notes
- Safety, balance, and health throttling are opt-in via `config/settings.jsonc`.

---

## [v2025.11.04] - 2025-11-04

### Improved
- Guided installer (`scripts/install_houndmind.sh`):
  - I2S audio setup now installs `alsa-utils`, guides reboot after `i2samp.sh`, and adds a dedicated audio test option (lists devices, sets volume, plays a test sound).
  - Header shows Python version and prints clear notes when on 32‑bit OS or Python 3.13 (heavy ML wheels like mediapipe/tflite may be unavailable and are optional).
  - Verify step prints `robot_hat` load path and whether it exports `Robot` to catch mismatched installs early.
  - New “Repair vendor modules” option to remove conflicting pip installs and reinstall Robot HAT (2.5.x), Vilib, and PiDog from vendor sources.

### Docs
- `docs/INSTALL.md`: Added a “Guided installer quick start (Raspberry Pi)” section at the top with exact commands and the recommended menu flow; clarified that mediapipe/tflite warnings on Pi 3B (32‑bit) or Python 3.13 are expected and safe to ignore when using the lite path.
- `README.md`: Added a concise guided installer quick‑start with the recommended menu flow under Install and run.

### Notes
- No behavior or runtime changes; improvements focus on installation reliability and first‑time setup clarity on the Pi.

## [v2025.11.03] - 2025-11-03 - Guided installer launcher, vendor-aligned install docs, and telemetry version sync

### Added
- Guided installer enhancements (`scripts/install_houndmind.sh`):
  - New launcher options to start CanineCore (main/control) and PackMind (with optional `PACKMIND_CONFIG` preset) directly from the menu.
  - One-stop menu: install vendor modules (Robot HAT 2.5.x, Vilib, PiDog), set up I2S audio, run vendor demo, verify imports/I2C, install HoundMind deps for Pi 4/5 (full) or Pi 3B (lite), and launch systems.
- Install guide overhaul (`docs/INSTALL.md`):
  - Linear Raspberry Pi flow with anchors: A0 (OS) → A1 (vendor modules) → A2 (checks/calibration) → A3 (deps per model) → A4 (run systems).
  - Clear separation of CanineCore vs PackMind; added a note that the guided installer can launch either system.
  - Pi 3B OS guidance (32-bit recommended; 64-bit supported with caveats) and vendor steps aligned with SunFounder docs (Robot HAT 2.5.x install.py, Vilib install.py, PiDog setup.py, I2S i2samp.sh).
- Tools: camera/audio helpers referenced from the guide to list devices and probe camera.

### Changed
- Telemetry server (`packmind/runtime/telemetry_server.py`) now reads version from `packmind.__version__` to avoid drift.
- `packmind.__version__` bumped to `2025.11.03` for release consistency.
- README and subsystem docs updated to reflect guided installer launch capability and current doc version.

### Notes
- Remaining file headers that still show 2025.11.01/02 are unchanged modules and will be updated on their next functional change.

## [v2025.11.02] - 2025-11-02 - Pi import robustness, explicit simulator alias, and docs

### Added
- `pidog_sim` package: explicit simulator alias that forces sim mode and re-exports the `pidog` shim. Use `from pidog_sim import Pidog` for examples/tests that must not touch hardware.
 - Telemetry server runner: `src/tools/run_telemetry.py` now starts the FastAPI dashboard using config defaults with `--host/--port` overrides and `--force` to run when disabled.
- Telemetry quickstart: `docs/telemetry_quickstart.md` with install instructions and usage.

### Changed
- `pidog` shim hardened to avoid self-import and to support multiple vendor class name variants (`Pidog`, `PiDog`, `PIDog`, `PIDOG`). On the Pi with the official package installed, the shim now reliably delegates to the real hardware library; otherwise it falls back to the simulator.
- `packmind/orchestrator.py` can be run directly (`python3 packmind/orchestrator.py`) without `PYTHONPATH` tweaks; a small bootstrap adds the repo root to `sys.path` when needed.
- `packmind/__main__.py` added so `python3 -m packmind` starts the orchestrator.
 - `src/tools/caninecore_checkup.py` now prepends the repo root to `sys.path` when run from `src/tools/`, fixing `ModuleNotFoundError: canine_core` on the Pi.
- README updated with a new "Hardware vs Simulator imports: pidog vs pidog_sim" section for clarity.
- Telemetry config flags (`TELEMETRY_ENABLED`, `TELEMETRY_HOST`, `TELEMETRY_PORT`, `TELEMETRY_BASIC_AUTH`) consolidated in `packmind/packmind_config.py`; duplicate `TELEMETRY_ENABLED` key removed from the logging section.

### Notes
- You can still force simulation anywhere with `HOUNDMIND_SIM=1`.
- On the robot, prefer `from pidog import Pidog` (uses real hardware automatically). For explicit sim in docs/tests, use `from pidog_sim import Pidog`.
- Docs: corrected voice setup to use the canonical PyPI name `SpeechRecognition` (import as `speech_recognition`) and added Pi-friendly PyAudio guidance (PortAudio headers + python3-dev, with apt fallback).

## [v2025.11.01] - 2025-11-01 - Desktop Simulation Mode, Lite Face Backend, and Setup Docs

### Added
- `pidog` shim: uses the real hardware package by default on the Pi; provides a safe simulated `Pidog`/`PiDog` when `HOUNDMIND_SIM=1`.
- No-op motion with plausible sensor values for development on desktops.
- Optional noise via `HOUNDMIND_SIM_RANDOM=1`.
- OpenCV Haar-based detection with low-res grayscale frames; optional LBPH identity when `opencv-contrib-python` is installed.
- Configurable via `FACE_BACKEND = "lite"`; uses `FACE_LITE_DATA_DIR` for simple training assets.
- Pi 3B preset now defaults to the lite backend when face recognition is enabled.
- `scripts/train_faces_lite.py` — trains LBPH from `data/faces_lite/<name>/*.jpg`.
 - `src/tools/lite_face_smoke_test.py` — runs the lite backend and logs detections for N seconds.

### Changed
- Added desktop simulation mode instructions and PowerShell/Bash examples.
- Added optional Face Recognition install block with cmake/build-tools note and a pointer to the setup guide; referenced `requirements-lite.txt` for Pi 3B.
- Added quick-start section for the lite face backend (config switch, training CLI, smoke test).
- Documented default vs lite face backends; added usage, training, and smoke test links.
- Added performance notes for Face Recognition on Pi 3B with link to the setup guide.
- Added `FACE_BACKEND` and `FACE_LITE_DATA_DIR` configuration keys.

### Maintenance
- Analyzer hardening and sim-safety:
  - Introduced a `PidogLike` Protocol and extended the pidog shim to align with runtime usage (read_distance, wait_head_done, rgb_strip.set_mode, stop_and_lie, close), reducing false-positive attribute warnings while keeping non-Pi runs safe.
  - Stabilized obstacle avoidance history slicing and recent-movement computations to avoid static analyzer mis-parses.
  - Enhanced audio service: robust float conversion for sound direction data, avoiding brittle casts.
  - Checkup tools and sensors now guard hardware calls with `getattr(...)/callable(...)` to prevent attribute errors on desktops.

### Notes
- See the full pre‑migration history in the original repository for entries prior to 2025‑10‑29.
