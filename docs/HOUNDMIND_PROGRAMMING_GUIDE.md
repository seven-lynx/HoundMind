# HoundMind Programming Guide (Pi3 Hardware-Only)

Version: v2026.01.18 • Author: 7Lynx

This guide explains how to run, tune, and extend the HoundMind AI on the SunFounder PiDog. Simulation mode is no longer supported. PackMind and CanineCore are now unified into a single system.

## 1) Quick Start
- Configure modules and settings in [config/settings.jsonc](config/settings.jsonc).
- Run the main runtime:
  - python -m houndmind_ai

## 2) Runtime Model
HoundMind runs a fixed-tick loop that calls each module in order. The runtime provides a shared context for sensor data, scan data, safety overrides, watchdog status, and action selection.

Core flow:
- Sensors → Perception → Navigation → Behavior → Motors
- Watchdog modules can request restarts, but do not force behavior/actions by default.

## 3) Modules Overview (Pi3)
### Core
- Runtime: tick loop, module lifecycle, status snapshot per tick.
- Config: JSONC parsing, validation warnings, action catalog load.

### HAL
- Sensors: ultrasonic, touch, sound direction, IMU; produces sensor_reading, sensors, sensor_health.
- Motors: action flow control, turn-by-angle with IMU, optional hardware stop.

### Navigation
- Scanning: three-way or sweep scan; scan_latest and scan_quality.
- Obstacle Avoidance: scan clustering + confirmation, mapping bias, stuck recovery, turn cooldown.
- Local Planner: lightweight hints from mapping (no global planning).

### Mapping
- Tracks openings, safe paths, and best path from scans.
- Optional home map snapshots (JSON).
- Path planning hook is Pi4-only.

### Behavior
- Behavior library and registry; idle/alert/avoid modes.
- Uses action catalog; supports selection modes and cooldown.
- Autonomy: patrol/play/rest are chosen using weighted modes and energy thresholds.

### Safety & Watchdogs
- Safety supervisor: emergency stop and tilt protection (disabled by default).
- Basic watchdog: stale sensor/scan detection (enabled, low-impact defaults).
- Service watchdog: restarts failed modules with backoff (enabled by default).
- Health monitor: system load/temp/memory with throttling hooks (disabled by default).
- Balance: IMU compensation (disabled by default).

### Optional (Disabled by Default)
- Vision, voice, energy/emotion, and Pi4 modules are disabled on Pi3.

## 4) Configuration
All settings live in [config/settings.jsonc](config/settings.jsonc). Key sections:
- modules: enable/disable modules
- sensors: polling cadence and filtering
- navigation: scan behavior and decision rules
- safety: emergency stop and tilt options (opt-in)
- mapping: home map settings
- behavior: action catalog settings
- performance: safe mode, warnings, and throttling hooks

## 5) Safety Defaults
- Safety and balance modules are disabled by default for bug testing.
- Emergency stop is also disabled by default; enable intentionally after validation.

## 6) Calibration Workflow
Calibration is request-driven:
- settings.calibration.request = servo_zero | wall_follow | corner_seek | landmark_align
- Results are persisted to a separate JSON file (data/calibration.json by default).

## 7) Logging & Diagnostics
- Event logger writes JSONL snapshots and a summary report.
- navigation_decision can include raw scan angles if enabled.
- health_status includes degraded reasons and high-water marks when health is enabled.
- telemetry dashboard (Pi4) can expose performance metrics when enabled.

## 8) Autonomy & Attention
- Autonomy cycles between idle/patrol/play/rest without user input.
- Sound attention turns the head toward the detected direction (cooldown and scan-safe).
- LED manager consolidates status signals (safety > navigation > attention > emotion).

## 9) On-Device Validation
Follow [docs/PI3_VALIDATION.md](docs/PI3_VALIDATION.md) to validate sensors, scanning, navigation, and logging before declaring Pi3 complete.

## 10) Extending the System
- Add new modules by extending houndmind_ai.core.module.Module.
- Register modules in houndmind_ai.main.build_modules.
- Use context keys consistently and document new settings in [config/settings.jsonc](config/settings.jsonc).

## 11) Pi4 Profile and Deferred Work
- Use profile `pi4` in [config/settings.jsonc](config/settings.jsonc) or set HOUNDMIND_PROFILE=pi4.
- All heavy mapping, vision, audio, and global planning features remain Pi4-only.
