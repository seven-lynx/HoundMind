# HoundMind Roadmap

## Unified Runtime & Migration
- [x] PackMind and CanineCore unified into a single runtime
- [x] Simulation mode removed (hardware-only)

## Documentation & Release
- [x] All guides updated for unified system, no sim mode, and Pi OS Lite recommendation
- [x] Changelog and README reflect all major changes
- [x] Release QA checklist: tests, docs, tag, changelog, install validation

Purpose: Track completion for each module needed for the PiDog hardware-only build (Pi 3 target). Check items as they’re implemented and verified on hardware.

## Core Runtime
- [x] Runtime loop + module lifecycle hardened (`core/runtime.py`)
- [x] Config loading + validation (`core/config.py`)
- [x] Module status/health reporting (`core/module.py`)

## HAL (Hardware Abstraction Layer)
- [x] Motor control integration (servo actions, head/tail) (`hal/motors.py`)
- [x] Sensor integration (ultrasonic, IMU, touch, sound dir) (`hal/sensors.py`)
- [x] Emergency stop procedure (hardware-only)
- [x] Calibration workflow hook (servo zero / offsets)

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
- [x] Obstacle avoidance module (`navigation/obstacle_avoidance.py`)
- [x] Threat levels: `IMMEDIATE` vs `APPROACHING`
- [x] Avoidance history buffer (last 10–30s)
- [x] Strategy rotation: smart turn → backup turn → zigzag → reverse escape
- [x] Stuck detection via accel magnitude window
- [x] Scan-based open-space selection (yaw sweep + clustering)
- [x] Approach detection + retreat/turn escalation
- [x] Dynamic scan width (narrow when safe)
- [x] IMU-based turn-by-angle (uses heading integration)
- [x] Navigation LED feedback
- [x] Avoidance strategy rotation (backup/zigzag/reverse)
- [x] Stuck recovery telemetry (count + last strategy)
- [x] Turn confidence gating for scan decisions
- [x] Low-confidence cooldown to reduce scan jitter
- [x] Low-confidence scan retry limit before fallback
- [x] Optional mapping best_path bias for turn decisions
- [x] Mapping bias confidence threshold
- [x] Mapping bias cooldown


## Mapping
- [x] Mapping module + home map storage (`mapping/mapper.py`)
- [x] Mapping data model (grid or graph)
- [x] Opening detection from scan data
- [x] Safe path heuristics from scan data
- [x] Best safe-path scoring output
- [x] Mapping sample retention (max count + max age)
- [x] Home map snapshot sample cap
- [x] Home map snapshot age cap
- [ ] Path planning hooks (Pi4)

## Behavior
- [x] Behavior FSM state definitions (`behavior/fsm.py`)
- [x] Core behaviors: stand, idle, avoid, alert
- [x] Action prioritization vs safety overrides
- [x] Behavior library + action catalog selector (`behavior/library.py`)

## Safety
- [x] Safety supervisor rules (`safety/supervisor.py`)
- [x] Emergency stop command
- [x] Watchdog heartbeat + timeout stop

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

## Tests (Hardware-validated)
- [x] Core runtime tests (non-hardware)
- [x] Automated on-device smoke test script

## Bug Fixes / Hardening
- [x] Runtime loop: account for tick duration when sleeping to reduce drift.
- [x] Watchdog: ensure recovery defaults are applied when config values are null.
- [x] Safety: honor emergency stop cooldown to avoid repeated triggers each tick.
- [x] Navigation: treat negative yaw as left for three-way scans (align direction mapping).
- [x] Mapping: use actual scan step for opening width estimation.
- [x] Logging: make log paths consistent (relative to repo root or config base).
- [x] Behavior: use configured idle action sets as default, not only random idle.
- [x] Config: robust JSONC parsing (inline comments and trailing commas).

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

### Pi 3 — Enhancement Ideas (lightweight)
- [x] Head-follow + attention coordination mode (avoid head follow right after attention).
- [x] Quiet mode schedule (reduce scan cadence + action frequency on demand).
- [x] Battery/voltage alert hook to trigger rest behavior (if available).
- [x] No-go memory for angles that repeatedly cause avoidance.
- [x] Gentle recovery: reduce speed after repeated stuck events.
- [x] Adaptive scan step (coarser when clear, finer when near obstacles).
- [x] Sensor health summary badge (LED/log) with thresholds.

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

### Pi 4 — Heavy-Duty Variant Roadmap

#### Platform & Performance
- [x] Pi4 profile in config with higher tick rates and feature flags.
- [x] CPU/GPU thermal monitoring and adaptive throttling.
- [x] Background service watchdog and graceful restart policies.
- [x] Performance telemetry (FPS, latency, CPU/GPU/RAM).

#### Vision Pipeline
- [x] Camera capture service (Pi4-optimized, low-latency).
- [ ] Frame pre-processing (resize, normalize, ROI selection).
- [ ] Vision inference scheduler (separate process/thread).
- [ ] Camera streaming UI (local preview + debug overlay).

#### Facial Recognition & Identity
- [x] Face detection model integration (fast on Pi4).
- [x] Face embedding generation + storage.
- [x] Face recognition (match/re-id) and enrollment flow.
- [ ] Multi-person tracking with re-identification across frames.
- [ ] Privacy controls (local-only data, easy reset).

#### Mapping, SLAM & Localization
- [ ] Full SLAM pipeline (visual/IMU fusion).
- [ ] Sensor-fusion localization (IMU + vision + distance).
- [ ] Global pathfinding (A* or similar) across mapped spaces.
- [ ] Path planning hooks + planner integration in runtime.
- [ ] Loop-closure handling and map optimization.

#### Semantic Understanding
- [x] Object/obstacle semantic labeling (vision-based).
- [ ] Semantic zones (e.g., “kitchen”, “charging area”).
- [ ] Behavior hooks triggered by semantic labels.

#### Audio & Voice
- [ ] Wake word detection (offline).
- [ ] Local ASR pipeline (offline first).
- [ ] VAD and noise suppression tuned for Pi4.
- [ ] TTS integration (local or optional cloud).
- [ ] Voice intent parsing and command routing.

#### Behavior & Interaction
- [ ] Gesture recognition for simple commands.
- [ ] Multi-person attention model (follow owner priority).
- [ ] Emotion/energy model (Pi4 variant; optional).
 - [x] Behavior parity: add explore/interact behaviors from legacy PackMind.
 - [x] Behavior parity: update action catalog for patrol/explore/interact.

#### Safety & Control
- [ ] Dynamic balance service with active IMU corrections.
- [ ] Vision-assisted obstacle avoidance.
- [ ] Safety gating for aggressive motions when uncertain.

#### Telemetry & UI
- [x] Telemetry server + dashboard (device status, map, logs).
- [ ] Live map/scan/event visualization.
- [ ] On-device debug UI for tuning thresholds.

#### Data & Logging
- [ ] Structured logs for vision/SLAM decisions.
- [ ] Map snapshot exports + session archives.
- [ ] Dataset export tooling for training/debug.

#### Installer & Packaging (Pi4)
- [x] Pi4 installer preset (full dependencies).
- [ ] Optional GPU acceleration toggles.
- [ ] Post-install validation suite (vision/audio/mapping).

#### Tests & Validation
- [ ] Pi4 hardware validation checklist.
- [ ] End-to-end scenario tests (vision + mapping + behavior).

### Misc / Tooling
- [x] GitHub Actions: test matrix for linting and unit tests (exclude hardware-only modules) 
- [x] Release packaging checklist and tagging workflow (prepare for Pi3 and Pi4 presets)
