# HoundMind Roadmap

## Unified Runtime & Migration
- [x] PackMind and CanineCore unified into a single runtime
- [x] Simulation mode removed (hardware-only)

## Documentation & Release
- [x] All guides updated for unified system, no sim mode, and Pi OS Lite recommendation
- [x] Changelog and README reflect all major changes
- [x] Release QA checklist: tests, docs, tag, changelog, install validation
- [ ] Expand troubleshooting checklist in `docs/INSTALL.md` (common errors + support bundle steps)
 - [ ] Improve and consolidate docs in `docs/` (API reference, programming guide, CONTRIBUTING.md, architecture overview)
- [x] Packaging & release automation: complete `pyproject.toml` metadata, automate builds, changelog generation, and release pipelines

Purpose: Track completion for each module needed for the PiDog hardware-only build (Pi 3 target). Check items as they’re implemented and verified on hardware.

## Core Runtime
- [x] Runtime loop + module lifecycle hardened (`core/runtime.py`)
- [x] Config loading + validation (`core/config.py`)
- [x] Module status/health reporting (`core/module.py`)
 - [ ] Provide a JSON Schema for `config/settings.jsonc` and runtime validation with clear errors and examples

## HAL (Hardware Abstraction Layer)
- [x] Motor control integration (servo actions, head/tail) (`hal/motors.py`)
- [x] Sensor integration (ultrasonic, IMU, touch, sound dir) (`hal/sensors.py`)
- [x] Emergency stop procedure (hardware-only)
- [x] Calibration workflow hook (servo zero / offsets)
 - [ ] Refactor HAL into clearer interfaces/adapters to allow Pi3/Pi4/simulator swaps and unit-testable adapters

## Sensor Stream
- [x] Sensor polling service loop (single thread + fixed cadence)
- [x] SensorReading schema (distance, touch, sound dir, accel, gyro, timestamp)
- [x] Configurable sampling + thresholds (min/max, samples, debounce)
- [x] Publish latest reading + history into `RuntimeContext`
- [x] Reactive callbacks for perception + safety modules
- [x] Optional subscriber API for future modules
- [x] Ultrasonic outlier rejection (z-score)
- [x] Distance EMA smoothing + debounce tuning
- [x] IMU low-pass filtering (configurable alpha)

## Orientation (Yaw Integration)
- [x] Heading integration from gyro Z (deg) with wraparound
- [x] Configurable gyro scale + bias
- [x] `RuntimeContext.current_heading` updates
- [x] Reset/zero heading on startup
- [x] Turn-by-angle helper uses IMU heading
- [x] Optional gyro bias calibration (toggle + duration)
- [x] Calibration settle delay + bias clamp

## Perception
- [x] Sensor fusion data model (`perception/fusion.py`)
- [x] Obstacle detection thresholds and smoothing
- [x] Touch + sound attention signals

## Scanning
- [x] Scanning module wired into runtime (reactive scan stream)
- [x] Three-way scan helper (forward/left/right)
- [x] Configurable settle time + sample count
- [x] Sweep scan helper for arbitrary yaw angles
- [x] Continuous scan loop + callback hook for streaming scans
- [x] Always return head to center after scan

## Navigation & Obstacle Avoidance
- [x] Obstacle avoidance with scan-based direction selection and cooldowns
- [x] Dead-end / loop avoidance (no-go memory + turn cooldowns)
- [x] Gentle recovery after repeated stuck events
- [x] Clear-path streak to reduce scan jitter when safe
- [x] Emit compact `navigation_decision` snapshots for tuning
- [ ] WiFi localization (Pi/Linux scan + AP parsing) for Pi hardware
- [ ] Fingerprint matching to estimate position from WiFi scans
- [ ] Fuse WiFi localization with IMU/mapping/vision and publish confidence
- [ ] Lost recovery when localization confidence drops
- [ ] Context-aware patrol/explore behaviors (coverage, recent obstacles, boredom)
- [ ] Curiosity/goal-seeking bias toward unmapped areas
- [ ] User-defined patrol routes/zones and waypoint linger behaviors
- [ ] Map-history bias to reduce repeated visits
- [ ] Scenario tests for navigation/patrol behaviors (dead-ends, loops, recovery)


## Mapping
- [x] Mapping module + home map storage (`mapping/mapper.py`)
- [x] Mapping data model (grid or graph)
- [x] Opening detection from scan data
- [x] Safe path heuristics from scan data
- [x] Best safe-path scoring output
- [x] Mapping sample retention (max count + max age)
- [x] Home map snapshot sample cap
- [x] Home map snapshot age cap
- [x] Path planning hooks (Pi4) — default A* hook added, mapper calls `path_planning_hook`, tests and docs updated
 - [ ] Add map-based measurement functions (point landmark distance and line/wall distance) for use by localization and range-matching.
 - [ ] Expose API in `mapping/mapper.py` to query nearest wall/landmark for ultrasonic range association.

## Behavior
- [x] Behavior FSM state definitions (`behavior/fsm.py`)
- [x] Core behaviors: stand, idle, avoid, alert
- [x] Action prioritization vs safety overrides
- [x] Behavior library + action catalog selector (`behavior/library.py`)

## Safety
- [x] Safety supervisor rules (`safety/supervisor.py`)
- [x] Emergency stop command
- [x] Watchdog heartbeat + timeout stop
 - [ ] Review and tighten safety defaults (emergency stop, balance); add automated tests and an onboarding validation checklist before enabling on-device

## Calibration
- [x] Wall-follow calibration routine
- [x] Corner-seek calibration routine
- [x] Landmark/anchor alignment routine (if mapping supports anchors)
- [x] Calibration success bumps localization confidence (when available)

## Logging & Telemetry (Lightweight)
- [x] Minimal event logger (in-memory ring buffer)
- [x] Optional JSONL file logging (rotating)
- [x] Session summary report (events, obstacles, interactions)
- [x] Global logging setup (console + rotating file)
- [x] Status log toggle + interval control
 - [ ] Standardize structured JSON logging across modules (JSONL snapshots, consistent schema)
 - [ ] Add log rotation configuration and retention defaults (config-driven)
 - [ ] Add telemetry hooks for optional remote metrics/telemetry export (explicit opt-in)

## Logging Tasks

The following checkable tasks cover robustness, observability, and supportability for logging and troubleshooting:

 - [x] Centralize logger setup in `src/houndmind_ai/core/logging_setup.py` (JSON formatter, handlers, rotation, level overrides).
 - [x] Add a `ContextFilter` to inject `device_id`, `runtime_tick`, `mission_id`/`trace_id` into all log records.
 - [x] Implement log rotation and retention policy (daily rotate + gzip backups, configurable `backupCount`).
 - [ ] Add optional error aggregation (Sentry/Logstash) with explicit opt-in and privacy documentation in `docs/INSTALL.md`.
 - [ ] Implement log sampling and rate-limiting for high-frequency sensors and debug streams.
 - [x] Provide `scripts/logs_collect.sh` or `python -m tools.collect_support_bundle` to bundle logs, config, and a telemetry snapshot for support uploads.
 - [x] Add `docs/LOGGING.md` runbook with collection commands, jq examples, and common troubleshooting steps.
 - [ ] Add unit tests verifying required log fields and that `logging_setup` responds to config/env overrides.
 - [x] Add unit tests verifying required log fields and that `logging_setup` responds to config/env overrides.
 - [ ] Surface `trace_id` in `RuntimeContext` and include it in telemetry snapshots to correlate logs + telemetry + support bundles.
 - [x] Surface `trace_id` in `RuntimeContext` and include it in telemetry snapshots to correlate logs + telemetry + support bundles.


## Optional (Disabled until later)
- [x] Vision module wiring (`optional/vision.py`) — disabled
- [x] Voice module wiring (`optional/voice.py`) — disabled

## Utilities & Tooling
- [x] Hardware checkup script (minimal motion + sensor sanity)
- [x] Config validation warnings (threshold ordering, scan cadence, speeds)
- [x] Readable config sections + Pi 3 performance guardrails
- [x] Health monitor module (CPU/mem/temp sampling)
- [x] Scan throttling when health is degraded
- [x] README usage + setup for Pi 3
 - [ ] Add CI pipeline (GitHub Actions) to run linting, tests, type checks, build, and packaging on PRs
 - [ ] Add typing and static checks (`mypy`, `ruff`/`flake8`) and enforce in CI
 - [ ] Pin and manage dependencies, add Dependabot config and guidance for `requirements-lite.txt`
 - [ ] Performance profiling harnesses for hot loops (navigation/scan processing) and document targets

## Tests (Hardware-validated)
- [x] Core runtime tests (non-hardware)
- [x] Automated on-device smoke test script
- [x] Gentle recovery test (navigation/obstacle avoidance)
 - [ ] Add localization unit and replay tests (EKF convergence, ZUPT, range-corrections) to validate pose accuracy on Pi3.
 - [ ] Increase unit and integration test coverage across HAL, navigation, mapping, and behavior; add hardware mocks for CI

## Bug Fixes / Hardening
- [x] Runtime loop: account for tick duration when sleeping to reduce drift.
- [x] Watchdog: ensure recovery defaults are applied when config values are null.
- [x] Safety: honor emergency stop cooldown to avoid repeated triggers each tick.
- [x] Navigation: treat negative yaw as left for three-way scans (align direction mapping).
- [x] Mapping: use actual scan step for opening width estimation.
- [x] Logging: make log paths consistent (relative to repo root or config base).
- [x] Behavior: use configured idle action sets as default, not only random idle.
- [x] Config: robust JSONC parsing (inline comments and trailing commas).

## Fixes

The following fixes are planned and prioritized. Each item should be implemented, documented, and validated on-device or via unit tests before being checked off.

- [x] **Fix config numeric coercions (HIGH):** Ensure numeric config fields (for example `loop.max_cycles`) are coerced to the expected types to avoid runtime TypeError. File: src/houndmind_ai/core/config.py
- **Clarify packaging and dependencies (HIGH):** Update `pyproject.toml` to declare core dependencies or document installer-only install flow. File: pyproject.toml
- **Remove/implement placeholder `build_default_modules` (MEDIUM):** Clean up or implement the placeholder in `src/houndmind_ai/core/runtime.py` to avoid duplicate module builders.
- **Harden JSONC parsing (MEDIUM):** Replace or harden the in-house `_load_jsonc` parser (consider `json5`/`commentjson`) in `src/houndmind_ai/core/config.py`.
- **Improve exception logging (MEDIUM):** Use `logger.exception` or include stack traces in broad `except Exception` blocks for actionable diagnostics. Files: core/runtime.py and module start/stop/tick handlers.
- **Add CI and test automation (MEDIUM):** Add GitHub Actions CI to run tests/lint and keep test/dev dependencies in `requirements-dev.txt` or `pyproject.toml`.
- **Telemetry security hardening (LOW→MEDIUM):** Add config options to bind dashboard to `127.0.0.1` and document authentication/ACL guidance. File: src/houndmind_ai/optional/telemetry_dashboard.py
- **Add unit tests for config & runtime edge cases (LOW):** Add tests for JSONC parsing, numeric coercion, and `max_cycles` loop behavior. Files: tests/
- **Document installer expectations (LOW):** Clarify in README and `pyproject.toml` whether the package is installer-first or pip-installable by developers.


## Migration (CanineCore + PackMind)
### Phase 1 — Behavior & Orchestration
- [x] Define behavior registry API (register, select, run)
- [x] Add idle selection modes (weighted/sequential)
- [x] Wire registry into `behavior/fsm.py`
- [x] Add behavior selection settings to config

### Phase 2 — Safety & Watchdog
- [x] Add watchdog module (heartbeat, timeout action)
- [x] Define safety override priority rules
- [x] Add watchdog config options
- [x] Watchdog recovery modes (behavior vs action)
- [x] Watchdog module restart logic
- [x] Per-module heartbeats + targeted restarts

### Phase 3 — Scanning & Navigation
- [x] Normalize scan data pipeline (scan_reading → navigation)
- [x] Threat tiers: immediate vs approaching
- [x] Confirmation windows for scan decisions
- [x] Stuck detection loop (accel magnitude history)

### Phase 4 — Energy & Emotion
// Deferred (not a priority)

### Phase 5 — Calibration & Orientation
- [x] IMU heading integration
- [x] Turn calibration helpers (degrees per step)

### Phase 6 — Mapping (Pi 3 subset)
- [x] Home map snapshot + openings/safe paths
- [x] Keep SLAM and sensor fusion OFF on Pi 3

### Phase 7 — Logging & Reports
- [x] Event logger (ring buffer + JSONL)
- [x] Session summary report

### Pi 3 — Priority (lightweight, Pi3-friendly)
- [x] Lightweight local planner: use `mapping.safe_paths` and `mapping.best_path` as short-range planning hints for navigation (no global A*). 
- [x] Minimal sensor-fusion localization: anchor-based pose hints using IMU + distance samples (keep CPU/lightweight).
- [x] Tilt/pose warning: simple dynamic that logs IMU tilt and sets `safety_action` when thresholds exceeded (no continuous correction).
- [x] Robust voice fallback: ensure voice subsystem disables gracefully when mic/audio unavailable and logs reason.
- [x] Installer verification for Pi3 lite preset: validate `requirements-lite.txt` and guided installer flow on Pi3.
- [x] Expand unit tests for core, mapping, and navigation modules (hardware-agnostic tests where possible).
- [x] Pi3 on-device validation checklist (sensors, scan, navigation, safety, logging).
- [x] Persist calibration outputs to config or a JSON file (servo offsets + calibration results).
- [x] Add `config/actions.jsonc` sanity validation for missing action sets.
- [x] Add a Pi3 “safe mode” preset (reduced scan rates + conservative movement).
 - [ ] Improve `examples/` with runnable demos, device setup scripts, and example configs for Pi3/Pi4
 - [ ] Implement a lightweight `localization` module (EKF) that fuses IMU (accel/gyro) predictions with ultrasonic range corrections and publishes `pose_estimate` (position, heading + covariance) into `RuntimeContext`.
 - [ ] Add ZUPT (zero-velocity update) detection and accelerometer-bias estimation to reduce dead-reckoning drift during stationary periods.
 - [ ] Integrate map-based measurement models (point landmark & wall distance) into the EKF measurement updates for stronger corrections.
 - [ ] Add telemetry/logging hooks for `pose_estimate` and estimator residuals so corrections can be inspected via the telemetry dashboard.
 - [ ] Add unit and integration tests for localization (EKF convergence on synthetic trajectories, ZUPT behavior, and replay-based validation with real logs).

### Pi 3 — Enhancement Ideas (lightweight)
- [x] Head-follow + attention coordination mode (avoid head follow right after attention).
- [x] Quiet mode schedule (reduce scan cadence + action frequency on demand).
- [x] Battery/voltage alert hook to trigger rest behavior (if available).
- [x] No-go memory for angles that repeatedly cause avoidance.
- [x] Gentle recovery: reduce speed after repeated stuck events.
- [x] Adaptive scan step (coarser when clear, finer when near obstacles).
- [x] Sensor health summary badge (LED/log) with thresholds.

### Pi 3 — Enhancement Ideas (lightweight)
- [x] Head-follow + attention coordination mode (avoid head follow right after attention).
	- [ ] Define head-follow state machine and avoidance cooldown in `behavior/fsm.py`.
	- [ ] Add unit tests for coordination timing `tests/test_head_follow_coordination.py`.
- [x] Quiet mode schedule (reduce scan cadence + action frequency on demand).
	- [ ] Add `behavior.quiet_mode` config with schedule and implement cadence overrides in `core/runtime.py`.
	- [ ] Tests: `tests/test_quiet_mode_schedule.py`.
- [x] Battery/voltage alert hook to trigger rest behavior (if available).
	- [ ] Add battery monitor hooks in `src/tools/hardware_checkup.py` and `core/health.py`.
	- [ ] Add config thresholds and rest behavior trigger test `tests/test_battery_rest_trigger.py`.
- [x] No-go memory for angles that repeatedly cause avoidance.
	- [ ] Implement `no_go_angles` LRU in `core/runtime.py` and expose tuning in config.
	- [ ] Integrate with navigation decision scoring and add tests `tests/test_no_go_memory.py`.
- [x] Gentle recovery: reduce speed after repeated stuck events.
	- [ ] Implement stuck counter and speed reduction policy in `navigation/avoidance.py`.
	- [ ] Tests: `tests/test_gentle_recovery.py` (already exists; extend scenarios).
- [x] Adaptive scan step (coarser when clear, finer when near obstacles).
	- [ ] Add adaptive scan step logic in `mapping/scan_helpers.py` and tests `tests/test_adaptive_scan_step.py`.
- [x] Sensor health summary badge (LED/log) with thresholds.
	- [ ] Emit periodic sensor health snapshot to telemetry and LED manager; add tests `tests/test_sensor_health_snapshot.py`.

### Pi 3 — Audit Suggestions (module polish)
- [x] Runtime: add tick overrun timing warnings and graceful shutdown handling.
- [x] Config: validate action catalog references and missing action sets.
- [x] Sensors: publish per-sensor health/stale flags in context.
- [x] Motors: use `energy_speed_hint` to bias turn/walk speed when enabled.
- [x] Perception: include `sound_direction` in `perception` payload.
- [x] Scanning: emit scan-quality summary (valid ratio, min distance).
- [x] Navigation: add dead-end memory and turn cooldown to avoid oscillation.
- [x] Navigation: add clear-path streak to reduce scan jitter when safe.
- [x] Navigation: log a compact `navigation_decision` snapshot for tuning.
- [x] Mapping: save a final home-map snapshot on shutdown (optional).
- [x] Behavior: add action cooldown to avoid rapid toggles.
- [x] Safety: add tilt cooldown / recovery clear to avoid repeated triggers.
- [x] Watchdog: per-module restart cooldowns to reduce thrash.
- [x] Health: emit high-water marks and last-degraded reasons.
- [x] Logging: include `navigation_decision` in event log snapshots.

### Pi 3 — Audit Suggestions (module polish)
- [x] Runtime: add tick overrun timing warnings and graceful shutdown handling.
	- [ ] Add regression/unit tests that simulate tick overruns and assert warnings are emitted.
- [x] Config: validate action catalog references and missing action sets.
	- [ ] Add config validation rules and tests `tests/test_config_action_catalog.py`.
- [x] Sensors: publish per-sensor health/stale flags in context.
	- [ ] Implement sensor health aggregation and tests `tests/test_sensor_health_flags.py`.
- [x] Motors: use `energy_speed_hint` to bias turn/walk speed when enabled.
	- [ ] Add integration tests that verify `energy_speed_hint` influences motor commands.
- [x] Perception: include `sound_direction` in `perception` payload.
	- [ ] Add unit tests for perception payload schema and ingest `tests/test_perception_schema.py`.
- [x] Scanning: emit scan-quality summary (valid ratio, min distance).
	- [ ] Implement scan-quality summary exporter and tests.
- [x] Navigation: add dead-end memory and turn cooldown to avoid oscillation.
	- [ ] Add scenario tests for dead-end avoidance and cooldown enforcement.
- [x] Navigation: add clear-path streak to reduce scan jitter when safe.
	- [ ] Add unit tests and telemetry assertions for clear-path streak logic.
- [x] Navigation: log a compact `navigation_decision` snapshot for tuning.
	- [ ] Add logging hooks and examples for `docs/LOGGING.md` with jq snippets.
- [x] Mapping: save a final home-map snapshot on shutdown (optional).
	- [ ] Add safe write + rotate behavior and test for permissions/failure modes.
- [x] Behavior: add action cooldown to avoid rapid toggles.
	- [ ] Ensure cooldowns are configurable and covered by `tests/test_action_cooldowns.py`.
- [x] Safety: add tilt cooldown / recovery clear to avoid repeated triggers.
	- [ ] Add tests simulating tilt events across ticks and ensure cooldown clearing works.
- [x] Watchdog: per-module restart cooldowns to reduce thrash.
	- [ ] Implement cooldown policy and tests that ensure restarts are rate-limited.
- [x] Health: emit high-water marks and last-degraded reasons.
	- [ ] Add telemetry snapshot fields and tests to validate high-water and reason fields.
- [x] Logging: include `navigation_decision` in event log snapshots.
	- [ ] Add unit test that composes an event snapshot including `navigation_decision` and validates JSON schema.

### Pi 4 — Heavy-Duty Variant Roadmap

#### Platform & Performance
- [x] Pi4 profile in config with higher tick rates and feature flags.
- [x] CPU/GPU thermal monitoring and adaptive throttling.
- [x] Background service watchdog and graceful restart policies.
- [x] Performance telemetry (FPS, latency, CPU/GPU/RAM).

#### Vision Pipeline
- [x] Camera capture service (Pi4-optimized, low-latency).
- [x] Frame pre-processing (resize, normalize, ROI selection).
	- [x] Vision inference scheduler (separate process/thread).
	- [ ] Replace dummy inference with a pluggable model interface + reference model
	- [ ] Camera streaming UI (local preview + debug overlay).
		- [ ] Toggle overlays on/off (bounding boxes, labels, FPS, inference results)
		- [ ] Switch between raw and annotated video streams
		- [ ] Adjustable overlay transparency and color schemes
		- [ ] Real-time telemetry panel (FPS, CPU/GPU/RAM, temp, inference latency)
		- [ ] Show module health/status (vision, mapping, navigation)
		- [ ] Show last N inference results or detected objects
		- [ ] Click-to-inspect pixel/ROI or trigger actions
		- [ ] Draw/select regions of interest (ROI) live from UI
		- [ ] Multi-stream support (multiple cameras, PiP)
		- [ ] Event & alert overlay (highlight on detection, errors, warnings)
		- [ ] Timeline & playback (buffer/replay recent video, step through frames)
		- [ ] Remote control & tuning (adjust vision params, trigger calibration)
		- [ ] Data export & annotation (download frames/clips, mark for training)
		- [ ] WebSocket/REST API for telemetry and control
		- [ ] User authentication & access control (password, roles)
		- [ ] Modular overlay system for future extensibility
		- [ ] Mobile-friendly UI
		- [ ] Support for custom plugins/scripts

#### Facial Recognition & Identity
- [x] Face detection model integration (fast on Pi4).
- [x] Face embedding generation + storage.
- [x] Face recognition (match/re-id) and enrollment flow.
- [ ] Add unit tests + sample assets for face recognition backends (opencv + face_recognition).
- [ ] Multi-person tracking with re-identification across frames.
- [ ] Privacy controls (local-only data, easy reset).

#### Mapping, SLAM & Localization
- [ ] Full SLAM pipeline (visual/IMU fusion).
	- [x] Evaluate and select a SLAM backend (RTAB-Map chosen for initial integration; adapter added).
	- [x] Integrate the chosen SLAM backend as a runtime module (rtabmap adapter in `slam_pi4.py`) — defensive adapter + stub fallback implemented.
	- [x] Implement camera and IMU data pipeline for SLAM backend (buffering and timestamp pairing implemented in module).
	- [x] Add configuration options for SLAM backend selection and tuning in `settings.slam_pi4`.
	- [x] Implement pose output: publish `slam_pose` (x, y, yaw, confidence) and `slam_status` to context.
	- [x] Add map output: expose map/trajectory data for visualization and debugging (map/trajectory now available via telemetry download endpoints).
	- [ ] Implement loop-closure detection and map optimization (if supported by backend).
	- [x] Add fallback to stub mode if backend is unavailable or fails.
	- [ ] Validate SLAM accuracy and robustness in real-world Pi4 tests (varied lighting, movement, and environments) — hardware validation pending.
	- [ ] Validate RTAB-Map adapter on Pi4 hardware and adapt adapter calls to the installed Python bindings if needed.
	- [x] Document SLAM usage, configuration, and troubleshooting in the features guide and programming guide (README + docs updated with RTAB-Map notes).
	- [x] Add unit and scenario tests for SLAM integration and pose/map outputs (basic tests added; more scenarios recommended).
	- [x] Expose SLAM status and map in the telemetry dashboard for live monitoring (download endpoints + snapshot keys added).
	- [ ] Add simulated camera+IMU tests to CI to catch adapter regressions before hardware runs.
- [ ] Sensor-fusion localization (IMU + vision + distance).
- [ ] Global pathfinding (A* or similar) across mapped spaces.
- [ ] Path planning hooks + planner integration in runtime.
- [ ] Loop-closure handling and map optimization.

#### Semantic Understanding
- [x] Object/obstacle semantic labeling (vision-based).
- [ ] Provide default model assets + download helper for semantic labeler (OpenCV DNN).
- [ ] Add unit tests for semantic labeler output schema and thresholds.
- [ ] Semantic zones (e.g., “kitchen”, “charging area”).
- [ ] Behavior hooks triggered by semantic labels.

#### Audio & Voice
- [ ] Wake word detection (offline).
- [ ] Local ASR pipeline (offline first).
- [ ] VAD and noise suppression tuned for Pi4.
- [ ] TTS integration (local or optional cloud).
- [ ] Voice intent parsing and command routing.

#### Behavior & Interaction

- **Gesture & Attention**
	- [ ] Gesture recognition for simple commands.
		- [ ] Define gesture schema and events (`behavior/gestures.py`).
		- [ ] Add a gated handler that maps gestures to behavior intents.
		- [ ] Unit test: `tests/test_gesture_integration.py` with simulated events.
	- [ ] Multi-person attention model (follow owner priority).
		- [ ] Define attention scorer (distance, recency, owner flag) in `behavior/attention.py`.
		- [ ] Integrate with `behavior/fsm.py` as an attention input.
		- [ ] Tests: simulated multi-attendee scenarios.

- **Internal State & Personality**
	- [ ] Add persistent internal state (energy/mood/engagement) that decays over minutes.
		- [ ] Define `RuntimeContext` fields: `energy`, `mood`, `engagement` in `core/runtime.py`.
		- [ ] Implement decay/update per tick and config-driven decay rates in `config/settings.jsonc`.
		- [ ] Persist state snapshot on graceful shutdown and restore on startup.
		- [ ] Unit tests: `tests/test_energy_decay.py`, `tests/test_state_persist.py`.
	- [ ] Add a `personality` config section and multipliers.
		- [ ] Add `personality.{curiosity,sociability,activity}` defaults to `config/settings.jsonc`.
		- [ ] Read personality multipliers in action/selection code (`behavior/fsm.py`).
		- [ ] Tests: `tests/test_personality_bias.py`.

- **Behavior Mechanics & Quality**
	- [x] Behavior parity: add explore/interact behaviors from legacy PackMind.
	- [x] Behavior parity: update action catalog for patrol/explore/interact.
	- [x] Add behavior state transition cooldowns + confidence gates to reduce jitter.
	- [x] Add habituation to repeated stimuli with recovery after quiet periods.
	- [ ] Add intent blending (patrol/explore/rest mix) based on energy + recent stimuli.
		- [ ] Design a scoring-based arbiter that produces blended intent scores.
		- [ ] Implement arbiter in `behavior/fsm.py` and expose debugging telemetry `behavior_snapshot`.
		- [ ] Tests: `tests/test_intent_blending.py` (unit and scenario tests).
	- [ ] Add action cooldowns and micro-behavior sequences.
		- [ ] Define micro-behavior script format and cooldown metadata in `behavior/library.py`.
		- [ ] Add sequencing runner + tests `tests/test_action_cooldowns.py`.

- **Memory & Navigation Support**
	- [ ] Add goal memory (recent waypoints, no-go zones) to reduce loops.
		- [ ] Implement small LRU ring in `core/runtime.py` or `mapping/mapper.py` as `goal_memory`.
		- [ ] Integrate as a soft cost in navigation decision heuristics.
		- [ ] Tests: `tests/test_goal_memory.py` (simulated loop scenarios).
	- [ ] Add return-to-home behavior when confidence/pose quality drops.
		- [ ] Define confidence thresholds and safe return heuristic in `behavior/fsm.py`.
		- [ ] Tests: `tests/test_return_home.py`.
	- [ ] Add safe exploration bounds (max distance/time) with automatic reset.
		- [ ] Add config settings `behavior.explore.max_distance` and `behavior.explore.max_time`.
		- [ ] Implement bounding logic and add tests.

- **Behaviors Library & UX**
	- [ ] Add a library of short behavior scripts (greet, investigate, stretch, rest).
		- [ ] Provide JSONC script examples in `config/actions.jsonc`.
		- [ ] Add playback and interruptable semantics in `behavior/library.py`.
		- [ ] Tests: `tests/test_behavior_scripts.py`.
	- [ ] Ensure chest LED always reflects the current behavior/safety/emotion state (clear priority rules).
		- [ ] Define LED priority mapping and unit tests `tests/test_led_priority.py`.

#### Safety & Control
- [ ] Dynamic balance service with active IMU corrections.
- [ ] Vision-assisted obstacle avoidance.
- [ ] Safety gating for aggressive motions when uncertain.

#### Telemetry & UI
- [x] Telemetry server + dashboard (device status, map, logs).
- [ ] Live map/scan/event visualization.
- [ ] On-device debug UI for tuning thresholds.
- [ ] Implement in-browser SLAM map/trajectory overlay (canvas/WebGL) consuming `/download_slam_map` and `/download_slam_trajectory`.
- [ ] Add telemetry authentication/ACL options for remote access and mobile UI control.
- [ ] Add a lightweight mobile debug view (last pose, recent events, map status).

#### Installer & Packaging (Pi4)
- [x] Pi4 installer preset (full dependencies).
- [ ] Optional GPU acceleration toggles.
- [ ] Post-install validation suite (vision/audio/mapping).
- [ ] Add an optional `full` extras group in `pyproject.toml` to simplify full-feature installs.

#### Tests & Validation
- [ ] Pi4 hardware validation checklist.
- [ ] End-to-end scenario tests (vision + mapping + behavior).
- [ ] Add a post-install `scripts/smoke_check.sh` for sensors/logs/telemetry sanity.
- [ ] Add CI fixtures for vision inference + SLAM (simulated frames/IMU) to validate adapters
- [ ] Add CI smoke tests for optional modules (face recognition, semantic labeling, telemetry endpoints).

Note: some vision-related tests require compiled C-extensions (NumPy/OpenCV). If your local Python environment lacks a compatible `numpy` wheel for your Python version/platform, these tests will fail during collection. Run vision tests on CI or a machine where `pip install numpy opencv-python` has been completed with matching binaries.


