# Changelog

## [v2025.11.02] - 2025-11-02 - Pi import robustness, explicit simulator alias, and docs

### Added
- `pidog_sim` package: explicit simulator alias that forces sim mode and re-exports the `pidog` shim. Use `from pidog_sim import Pidog` for examples/tests that must not touch hardware.
- Telemetry server runner: `tools/run_telemetry.py` now starts the FastAPI dashboard using config defaults with `--host/--port` overrides and `--force` to run when disabled.
- Telemetry quickstart: `docs/telemetry_quickstart.md` with install instructions and usage.

### Changed
- `pidog` shim hardened to avoid self-import and to support multiple vendor class name variants (`Pidog`, `PiDog`, `PIDog`, `PIDOG`). On the Pi with the official package installed, the shim now reliably delegates to the real hardware library; otherwise it falls back to the simulator.
- `packmind/orchestrator.py` can be run directly (`python3 packmind/orchestrator.py`) without `PYTHONPATH` tweaks; a small bootstrap adds the repo root to `sys.path` when needed.
- `packmind/__main__.py` added so `python3 -m packmind` starts the orchestrator.
- `tools/caninecore_checkup.py` now prepends the repo root to `sys.path` when run from `tools/`, fixing `ModuleNotFoundError: canine_core` on the Pi.
- README updated with a new "Hardware vs Simulator imports: pidog vs pidog_sim" section for clarity.
- Telemetry config flags (`TELEMETRY_ENABLED`, `TELEMETRY_HOST`, `TELEMETRY_PORT`, `TELEMETRY_BASIC_AUTH`) consolidated in `packmind/packmind_config.py`; duplicate `TELEMETRY_ENABLED` key removed from the logging section.

### Notes
- You can still force simulation anywhere with `HOUNDMIND_SIM=1`.
- On the robot, prefer `from pidog import Pidog` (uses real hardware automatically). For explicit sim in docs/tests, use `from pidog_sim import Pidog`.
 - Docs: corrected voice setup to use the canonical PyPI name `SpeechRecognition` (import as `speech_recognition`) and added Pi-friendly PyAudio guidance (PortAudio headers + python3-dev, with apt fallback).

## [v2025.11.01] - 2025-11-01 - Desktop Simulation Mode, Lite Face Backend, and Setup Docs

### Added
  `pidog/__init__.py`):
  - Uses the real hardware package by default on the Pi; provides a safe simulated `Pidog`/`PiDog` when `HOUNDMIND_SIM=1`.
  - No-op motion with plausible sensor values for development on desktops.
  - Optional noise via `HOUNDMIND_SIM_RANDOM=1`.
  - Explains piwheels/prebuilt wheels, required build tools (cmake, build-essential, python3-dev, BLAS/LAPACK), swap sizing, and when to disable the feature.
  - Clear guidance for Pi 3B where compiling dlib is slow/unreliable.
  - OpenCV Haar-based detection with low-res grayscale frames; optional LBPH identity when `opencv-contrib-python` is installed
  - Configurable via `FACE_BACKEND = "lite"`; uses `FACE_LITE_DATA_DIR` for simple training assets
  - Pi 3B preset now defaults to the lite backend when face recognition is enabled
  - `scripts/train_faces_lite.py` — trains LBPH from `data/faces_lite/<name>/*.jpg`
  - `tools/lite_face_smoke_test.py` — runs the lite backend and logs detections for N seconds
  - Omits heavy optional deps (dlib/face-recognition, tensorflow, etc.).
  - Pi 3B-friendly Lite Face backend (no dlib): `packmind/services/face_recognition_lite_service.py`
    - Detection via OpenCV Haar cascades; optional identity via LBPH (requires `opencv-contrib-python`).
    - Runs detection-only if `cv2.face` is unavailable.
  - Training CLI for the lite backend: `scripts/train_faces_lite.py`
  - Lite backend smoke test: `tools/lite_face_smoke_test.py`

### Changed
  - Added “Desktop simulation mode” instructions and PowerShell/Bash examples.
  - Added optional Face Recognition install block with cmake/build-tools note and a pointer to the setup guide; referenced `requirements-lite.txt` for Pi 3B.
  - Added quick-start section for the lite face backend (config switch, training CLI, smoke test)
  - Added desktop simulation usage.
  - Documented default vs lite face backends; added usage, training, and smoke test links
  - Added performance notes for Face Recognition on Pi 3B with link to the setup guide.
  - Added `FACE_BACKEND` and `FACE_LITE_DATA_DIR` configuration keys

### Maintenance
- Analyzer hardening and sim-safety:
  - Introduced a `PidogLike` Protocol and extended the pidog shim to align with runtime usage (read_distance, wait_head_done, rgb_strip.set_mode, stop_and_lie, close), reducing false-positive attribute warnings while keeping non-Pi runs safe.
  - Stabilized obstacle avoidance history slicing and recent-movement computations to avoid static analyzer mis-parses.
  - Enhanced audio service: robust float conversion for sound direction data, avoiding brittle casts.
  - Checkup tools and sensors now guard hardware calls with `getattr(...)/callable(...)` to prevent attribute errors on desktops.

### Notes

## [v2025.10.29b] - 2025-10-29 - HomeMap Mapping Refactor, Legacy Removal, and Documentation Overhaul

### Changed
- **PackMind mapping/navigation is now fully powered by the new HomeMap system:**
  - All legacy mapping logic and references (HouseMap, PiDogSLAM, etc.) have been removed from the codebase.
  - HomeMap now provides openings, safe_paths, anchors, semantic labels, sensor fusion, and advanced map visualization.
  - Navigation, pathfinding, and visualization modules refactored to use HomeMap exclusively.
- **Configuration:**
  - All advanced mapping features are now user-configurable in `packmind/packmind_config.py`.
  - Config guides updated to reflect new options and parameters.
- **Documentation:**
  - `README.md` updated to document the new mapping/navigation system, advanced features, and removal of legacy logic.
  - `docs/api_reference.md` now includes a full HomeMap API section with usage patterns and advanced features.
  - `docs/PIDOG_PROGRAMMING_GUIDE.md` references the new mapping/navigation system and provides usage examples.
  - All legacy mapping references removed from documentation.
- **To-Do List:**
  - All mapping/navigation refactor and integration tasks are now complete and checked off.

---
## [v2025.10.29] - 2025-10-29 - IMU Orientation (Yaw) integration and precise turns

### Added
- PackMind OrientationService: optional IMU-based heading integration (gyro Z → heading degrees). Controlled by `ENABLE_ORIENTATION_SERVICE` with tunables `ORIENTATION_GYRO_SCALE`, `ORIENTATION_BIAS_Z`, `ORIENTATION_TURN_TOLERANCE_DEG`, `ORIENTATION_MAX_TURN_TIME_S`.
- CanineCore OrientationService: mirrored optional module under `canine_core/core/services/orientation.py`; enabled via `ENABLE_ORIENTATION_SERVICE` with `ORIENTATION_GYRO_SCALE`, `ORIENTATION_BIAS_Z`, `ORIENTATION_CALIBRATION_S`, `ORIENTATION_TURN_TOLERANCE_DEG`, `ORIENTATION_MAX_TURN_TIME_S`.
- BehaviorContext now exposes `ctx.orientation` (CanineCore) for behaviors to read heading when available.
 - MotionService helper: `turn_by_angle(degrees, speed, ctx, tolerance_deg, timeout_s)` for IMU-based precise turning with step-based fallback.
 - Turn Calibration Tool: `tools/turn_calibration.py` measures degrees-per-step via IMU and updates configs automatically.
 - Localization active recovery: orchestrator monitors sensor-fusion confidence and performs brief ultrasonic sweep(s) to re-weight the particle filter when confidence is low. Configurable via `LOCALIZATION_*` keys in `packmind_config.py`.
 - IMU Turn Sanity Tool: `tools/imu_turn_test.py` to rotate ±90° via closed-loop IMU control and report final angular error.
 - Structural features: basic opening detection in the map (constricted gap with flanking obstacles) and A* cost bias to prefer paths that pass near detected openings.
 - Safe path detection: corridor-like passage detection (formerly "hallways") with centerline segments exposed as `safe_paths`; pathfinding prefers staying centered within these passages for smoother room-to-room travel.

### Changed
- PackMind obstacle avoidance uses IMU-based turn-by-angle when orientation is enabled; falls back to fixed step turns when disabled.
- Orchestrators wire and start OrientationService when enabled and IMU is present.

### Documentation
- Updated `docs/packmind_config_guide.md` and `docs/canine_core_config_guide.md` with a new "Orientation (IMU yaw)" section documenting flags and tuning.
 - Added guidance for the turn calibration tool and `TURN_DPS_BY_SPEED` mapping (CanineCore).
 - Documented localization recovery settings and how to run the IMU turn sanity test.

# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and adheres to semantic-ish sections.

## [v2025.10.24] - 2025-10-24 - Major AI Services Integration: Face Recognition, Dynamic Balance, and Enhanced Audio Processing

### Added
- **Face Recognition Service** (`packmind/services/face_recognition_service.py`):
  - Real-time facial detection and recognition using OpenCV + face_recognition library
  - Personal relationship building with interaction memory and personality adaptation
  - Local privacy-focused processing with encrypted person profiles
  - Automatic person database management with learning capabilities
  - 12 configurable parameters including recognition thresholds, camera settings, learning rates

- **Dynamic Balance Service** (`packmind/services/dynamic_balance_service.py`):
  - Real-time IMU monitoring with accelerometer and gyroscope integration
  - Advanced balance state analysis (Stable/Slight/Unstable/Critical/Falling)
  - Automatic tilt detection and correction trigger system
  - Balance event logging with comprehensive statistics and performance metrics
  - 11 configurable parameters including sampling rates, tilt thresholds, correction behaviors

- **Enhanced Audio Processing Service** (`packmind/services/enhanced_audio_processing_service.py`):
  - Multi-directional sound source detection and tracking
  - Advanced voice activity detection with frequency analysis
  - Background noise calibration and adaptive silence detection
  - Sound classification (Voice/Footsteps/Mechanical/Environmental/Alarm/etc.)
  - 18 configurable parameters covering hardware setup, voice detection, sound tracking

- **Service Integration & Orchestration**:
- **Tools**:
  - `tools/packmind_checkup.py`: Pi-only checkup tool to import all PackMind modules and perform safe service smoke tests
    - New `--move` flag to include a minimal ScanningService head sweep (limited motion)
  - `tools/caninecore_checkup.py`: Pi-only checkup tool to import all CanineCore modules; supports `--scope services` to instantiate core services and `--move` for a minimal head sweep
  - CanineCore services checkup extended to instantiate optional services: EnergyService, BalanceService, AudioProcessingService, and ScanningCoordinator, in addition to IMU, Safety, Battery, Telemetry, and SensorsFacade
  - Full integration of all three services into `packmind/orchestrator.py`
  - Automatic service lifecycle management (startup/shutdown)
  - Real-time event integration with emotional system and behavior logging
  - Thread-safe operation with proper resource management

- **Configuration System Enhancements**:
  - Added `ENABLE_FACE_RECOGNITION`, `ENABLE_DYNAMIC_BALANCE`, `ENABLE_ENHANCED_AUDIO` flags
  - CanineCore config: added `ENABLE_ENERGY_SYSTEM`, `ENABLE_BALANCE_MONITOR`, `ENABLE_AUDIO_PROCESSING`, `ENABLE_SCANNING_COORDINATOR` toggles with safe defaults
  - Specialized preset configurations for all four modes (Simple/Advanced/Indoor/Explorer)
  - 41 new configuration parameters with detailed documentation
  - Preset-specific optimizations (Advanced: enhanced capabilities, Simple: focused operation)

- **Documentation & Testing**:
 - **CanineCore LearningService** (`canine_core/core/services/learning.py`): A lightweight, JSON-backed counters service (interactions, commands, obstacles). Wired behind `ENABLE_LEARNING_SYSTEM` and exposed to behaviors via `ctx.learning`; persists to `data/canine_core/learning.json` with periodic autosave.
  - Comprehensive configuration guide updates in `PackMind_Configuration_Guide.txt`
  - Integration test suite in `tools/test_service_integration.py` 
  - Updated dependency management in `requirements.txt`

### Changed
- **Emotional System Integration**: Services now trigger appropriate emotional responses:
  - Face recognition → HAPPY (recognized) / EXCITED (unknown faces)
  - Balance issues → ALERT (critical) / CALM (recovery)
  - Audio detection → EXCITED (voice) / ALERT (loud noises)
- **Patrol Event Logging**: All service events automatically logged with metadata
- **Main AI Loop**: Added periodic service polling in `_ai_behavior_loop` method
- **Dependencies**: Added face-recognition, dlib, pyaudio, scipy for new services
 - **Folder Structure**: Renamed `scripts/` to `tools/` and updated documentation and references accordingly
 - **CanineCore Units**: Standardized distance units to centimeters (cm) in `canine_core/core/services/sensors.py`, `scanning.py`, and behavior docs (`behaviors/smart_patrol.py`); variable renamed `_baseline_mm` → `_baseline_cm`.
 - **CanineCore Modular Services**: Added optional services with `ENABLE_*` toggles in `canine_core/config/canine_config.py` and wired into orchestrator:
   - IMUService (`ENABLE_IMU_MONITOR`)
   - SafetyService (`ENABLE_SAFETY_SUPERVISOR`)
   - BatteryService (`ENABLE_BATTERY_MONITOR`)
   - TelemetryService (`ENABLE_TELEMETRY`)
 - **Event Bus**: Reintroduced lightweight `canine_core/core/bus.py` for internal pub/sub
 - **Default Hooks**: Added `canine_core/core/hooks.py` with default event-driven handlers (battery_low/critical, safety_emergency_tilt) and optional enable via `ENABLE_DEFAULT_HOOKS`.
 - **Sensors Facade**: New `canine_core/core/services/sensors_facade.py` for sim-safe ears (sound) and dual touch wrappers; gated via `ENABLE_SENSORS_FACADE`.
 - **Telemetry HUD**: Extended `canine_core/core/services/telemetry.py` to include `tilt_deg`, `battery_pct`, and head orientation (yaw/roll/pitch) when available.
 - **Behavior Watchdog**: Introduced `canine_core/core/watchdog.py` and integrated into orchestrator to cap dwell and stop on consecutive errors; controlled by `ENABLE_BEHAVIOR_WATCHDOG`, `WATCHDOG_MAX_BEHAVIOR_S`, `WATCHDOG_MAX_ERRORS`.
 - **Safety-First Preset**: New `SafetyFirstPreset` with conservative speeds, wider safe distances, and `SCAN_WHILE_MOVING=False`; added to presets as `"safety-first"` and fully applied in `canine_core/control.py`.
 - **Hardware Smoke Behavior**: New `canine_core/behaviors/hardware_smoke.py` to perform minimal OK/FAIL checks (distance, IMU, battery, ears/touch); optional limited motion via `SMOKE_ALLOW_MOVE` and `SMOKE_SPEED`.
 - **Pi-only Hardware Check Tool**: `tools/pidog_hardware_check.py` for direct on-robot validation (distance, IMU, ears, touch, audio, LED); `--move` enables limited motion/head sweep.
 - **Documentation canonicalization**: Consolidated duplicates; `docs/` is now the canonical location for configuration and API guides. Updated pointers:
   - `canine_core/canine_core_config_guide.md` now points to `docs/canine_core_config_guide.md`
   - `packmind/packmind_docs/api_reference.md` now points to `docs/api_reference.md`
   - Verified root `README.md` references target `docs/` paths

 - **CanineCore Behavior/Runtime improvements**:
   - Reactions Behavior now reads thresholds and cooldowns from config (`REACTIONS_*`, `TOUCH_DEBOUNCE_S`, `REACTION_COOLDOWN_S`, `SOUND_COOLDOWN_S`).
   - Orchestrator supports weighted behavior ordering when `BEHAVIOR_SELECTION_MODE="weighted"` using `BEHAVIOR_WEIGHTS`.
   - LoggingService consumes `LOG_LEVEL`, `LOG_FILE_MAX_MB`, and `LOG_FILE_BACKUPS` from config for JSONL rotation.
   - Smart Patrol adds a minimal intelligent scanning heuristic (narrow/widen sweep based on forward baseline vs `OBSTACLE_SAFE_DISTANCE`) when `ENABLE_INTELLIGENT_SCANNING` is true.

### Technical Metrics
- **2,236+ lines** of new service code across three major AI systems
- **41 new configuration parameters** with comprehensive documentation
- **12 integration points** with existing orchestrator system
- **5 test suites** for complete integration validation
- **4 preset configurations** updated with service-specific settings

## [v2025.10.23] - 2025-10-23 - CanineCore stabilization, PackMind docs restructure, and legacy tests archived

### Added
- Centralized JSON logging in CanineCore via `utils/logging_setup.py` and `core/services/logging.py` with rotation controls (`LOG_FILE_MAX_MB`, `LOG_FILE_BACKUPS`).
- Expanded `canine_core/config/canine_config.py` with grouped options and presets (Simple, Patrol, Interactive).
- Control script (`canine_core/control.py`) supports running single behaviors, sequences, random cycles, and presets.

### Changed
- `core/orchestrator.py` now uses `CanineConfig` and optional preset selection instead of YAML; derives the run queue from `AVAILABLE_BEHAVIORS` when no explicit queue is provided.
- Documentation: updated `canine_core/README.md` and `canine_core/canine_core_config_guide.md` to reflect the Python-based config and remove YAML references.

### Deprecated
- `core/services/config.py` deprecated and replaced with a hard error directing users to `config/canine_config.py`.

### Removed
- YAML-based configuration loader pathway in CanineCore.

### Notes
- Legacy bridge modules under `canine_core/core/` (e.g., `global_state.py`, `memory.py`, `state_functions.py`, `master.py`) are retained for backward compatibility.
- Tests migrated to `legacy/` with `_test` suffix removed; README updated accordingly.

