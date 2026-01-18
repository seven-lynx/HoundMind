# HoundMind (PiDog Unified AI)

Version: v2026.01.18 • Author: 7Lynx

HoundMind is a unified AI control framework for the SunFounder PiDog. Simulation mode is no longer supported; all features require real PiDog hardware. PackMind and CanineCore are now a single system.

## Current scope
- Target hardware: **Raspberry Pi 3/4/5** (recommended: Raspberry Pi OS Lite, no desktop).
- Simulation mode is not supported; all features require real hardware.
- All features (movement, sensors, navigation, mapping, safety, logging) are unified in a single runtime.
- Vision, voice, and Pi4/5 optional modules are **disabled by default**; basic watchdogs are enabled.
- Safety and throttling features are **opt-in** (disabled by default for bug testing).

## Quick start
- Run the main loop on PiDog hardware:
  - `python -m houndmind_ai`

## Installer Quickstart (Recommended)
Run the automated installer on a Raspberry Pi:

```bash
bash scripts/install_houndmind.sh
```

This installs the SunFounder PiDog dependencies **and** HoundMind in the same environment. It auto-selects Pi3 lite or Pi4 full. For manual steps, see [docs/INSTALL.md](docs/INSTALL.md).

## Before You Start (Pi OS Checklist)
- Flash Raspberry Pi OS and complete first boot setup.
- Update and reboot:
  - `sudo apt update && sudo apt upgrade -y`
- Enable interfaces in `raspi-config`:
  - I2C (required)
  - Camera (optional; required for Pi4 vision)

## Guided Installer Overview
The guided installer can:
- Install vendor PiDog dependencies (robot-hat, vilib, pidog)
- Set up audio (optional)
- Install HoundMind dependencies
- Verify imports and hardware access

It is safe to re-run; it skips work that is already complete.

## Hardware checkup
- Run a minimal sensor + motion check on the PiDog hardware:
  - `python tools/hardware_checkup.py`
- Use `--skip-motion` to avoid any movement.

## Automated smoke test
- Run a non-motion smoke test (sensors + scan + mapping):
  - `python tools/smoke_test.py`
- Add `--include-motion` to allow navigation/motor actions.

## Configuration
Edit [config/settings.jsonc](config/settings.jsonc) to enable/disable modules and tune behavior (comments included). Optional modules should remain `enabled: false` until tested.
Action catalogs live in [config/actions.jsonc](config/actions.jsonc) so the main config stays clean and readable.

## Profiles
Set the profile in [config/settings.jsonc](config/settings.jsonc) or via `HOUNDMIND_PROFILE`:
- `pi3` (default, for Pi 3 hardware)
- `pi4` (enables Pi 4/5 feature flags)

Pi4/5 modules (vision, face recognition, semantic labeling, SLAM, telemetry) remain opt-in.

## Feature Guide
See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for what each feature does, how to use it, and how to disable it.

## Telemetry Dashboard (Pi4 Optional)
Enable the dashboard module and open:
- `http://<pi-ip>:8092/` for the live dashboard
- `http://<pi-ip>:8092/snapshot` for JSON snapshots

Performance telemetry includes tick latency, FPS, and CPU/GPU/RAM when enabled.

See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for enable/disable steps.

## Project layout (key paths)
- `src/houndmind_ai/` — core runtime and modules
- `config/settings.jsonc` — module enablement and parameters
- `tests/` — unit tests for modular behavior

## Notes
- This project now runs **only on the real PiDog hardware** (no simulation/shim mode).
- PackMind and CanineCore are now unified; all features are part of a single runtime.
- Hardware access is required for `houndmind_ai/hal/*` modules.
- Watchdogs are enabled by default but do not force actions or restarts unless configured.

## Troubleshooting (Quick)
- **`ModuleNotFoundError: pidog`** → Install the official PiDog repo first, then HoundMind in the same environment.
- **Camera not opening** → Enable camera in OS settings; try a different device index.
- **Audio not working** → Ensure PortAudio headers are installed; rerun audio setup.
- **Port in use** → Change HTTP ports in `config/settings.jsonc` for vision/telemetry/voice.

## Fallback (Original PiDog Software)
If HoundMind breaks, you can still run the official PiDog scripts from the SunFounder repo. See [docs/INSTALL.md](docs/INSTALL.md) for fallback instructions.

## Migration status
- Core runtime, safety/health, and logging foundations are complete.
- Remaining: minor polish and documentation; emergency stop procedure implemented.
