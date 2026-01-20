# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and adheres to semantic-ish sections.

Current Release: v2026.01.18 • Author: 7Lynx


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
- `pidog` shim: uses the real hardware package by default on the Pi; provides a safe simulated `Pidog`/`PiDog` when `HOUNDMIND_SIM=1`.
- No-op motion with plausible sensor values for development on desktops.
- Optional noise via `HOUNDMIND_SIM_RANDOM=1`.
- OpenCV Haar-based detection with low-res grayscale frames; optional LBPH identity when `opencv-contrib-python` is installed.
- Configurable via `FACE_BACKEND = "lite"`; uses `FACE_LITE_DATA_DIR` for simple training assets.
- Pi 3B preset now defaults to the lite backend when face recognition is enabled.
- `scripts/train_faces_lite.py` — trains LBPH from `data/faces_lite/<name>/*.jpg`.
- `tools/lite_face_smoke_test.py` — runs the lite backend and logs detections for N seconds.

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
