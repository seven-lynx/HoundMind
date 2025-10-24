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
  - `tools/caninecore_checkup.py`: Pi-only checkup tool to import all CanineCore modules; now supports `--scope services` to instantiate core services and `--move` for a minimal head sweep
  - CanineCore services checkup now includes IMU, Safety, Battery, and Telemetry instantiation tests
  - Full integration of all three services into `packmind/orchestrator.py`
  - Automatic service lifecycle management (startup/shutdown)
  - Real-time event integration with emotional system and behavior logging
  - Thread-safe operation with proper resource management

- **Configuration System Enhancements**:
  - Added `ENABLE_FACE_RECOGNITION`, `ENABLE_DYNAMIC_BALANCE`, `ENABLE_ENHANCED_AUDIO` flags
  - Specialized preset configurations for all four modes (Simple/Advanced/Indoor/Explorer)
  - 41 new configuration parameters with detailed documentation
  - Preset-specific optimizations (Advanced: enhanced capabilities, Simple: focused operation)

- **Documentation & Testing**:
  - Comprehensive configuration guide updates in `PackMind_Configuration_Guide.txt`
  - Integration test suite in `tools/test_service_integration.py` 
  - Complete project summary in `INTEGRATION_COMPLETE.md`
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

