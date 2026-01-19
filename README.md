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


## SLAM (RTAB-Map for Pi4/5)
For robust mapping and localization on Pi4/5, HoundMind supports RTAB-Map as the recommended SLAM backend. See [scripts/install_rtabmap_pi4.md](scripts/install_rtabmap_pi4.md) for installation steps and troubleshooting.

## Feature Guide
See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for what each feature does, how to use it, and how to disable it.

## Telemetry Dashboard (Pi4 Optional)
Enable the optional telemetry dashboard module and open the dashboard in a browser:

- `http://<pi-ip>:8092/` — mobile-friendly dashboard (camera preview + snapshot view)
- `http://<pi-ip>:8092/snapshot` — JSON snapshot of selected runtime context keys

Configuration (example `config/settings.jsonc` snippet):

```jsonc
"telemetry_dashboard": {
  "enabled": true,
  "http": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8092,
    // URL path to embed the camera stream or single-frame image.
    // For MJPEG streams use "/stream.mjpg" or similar; for single-frame endpoints
    // point to an image URL (the dashboard will auto-refresh with a cache-busting ts param).
    "camera_path": "/camera"
  },
  "snapshot_interval_s": 0.5
}
```

Notes:
- `camera_path` can be any HTTP-accessible path served by your device (MJPEG stream or single-frame image).
- For single-frame camera endpoints the dashboard reloads the image periodically (cache-busted). For MJPEG streams, set `camera_path` to the stream endpoint and the browser will display it directly.
- The dashboard polls `/snapshot` to display telemetry (tick latency, vision FPS, CPU/memory) — disable or restrict access as needed for security.

See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for detailed enable/disable steps and security recommendations.

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



## Primary Features

| Feature                        | Default      | Notes (Enable/Disable)                |
|--------------------------------|-------------|---------------------------------------|
| Core Runtime                   | Enabled     | Always required                       |
| HAL: Sensors & Motors          | Enabled     |                                       |
| Perception                     | Enabled     |                                       |
| Scanning                       | Enabled     |                                       |
| Navigation & Obstacle Avoidance| Enabled     |                                       |
| Mapping (Pi3-safe)             | Enabled     |                                       |
| Behavior                       | Enabled     |                                       |
| Attention                      | Enabled     |                                       |
| Watchdog                       | Enabled     | Low-impact defaults                   |
| Service Watchdog               | Enabled     |                                       |
| Event Logging                  | Enabled     |                                       |
| LED Manager                    | Enabled     |                                       |
| Calibration                    | Enabled     |                                       |
| Safety                         | Disabled    | Opt-in for emergency stop/tilt        |
| Health Monitor                 | Disabled    | Opt-in for CPU/mem/temp/throttling    |
| Balance                        | Disabled    | Opt-in for IMU posture                |
| Vision (Pi3 legacy)            | Disabled    | Opt-in, legacy camera                 |
| Voice (Pi3 legacy)             | Disabled    | Opt-in, legacy voice                  |
| Voice Assistant (Pi4)          | Disabled    | Opt-in, requires Pi4                  |
| Face Recognition (Pi4)         | Disabled    | Opt-in, requires Pi4                  |
| Pi4 Vision Feed (Pi4)          | Disabled    | Opt-in, requires Pi4                  |
| Semantic Labeler (Pi4)         | Disabled    | Opt-in, requires Pi4                  |
| SLAM (Pi4)                     | Disabled    | Opt-in, requires Pi4                  |
| Telemetry Dashboard (Pi4)      | Disabled    | Opt-in, requires Pi4                  |

See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for details and enable/disable instructions for each module.

## PiDog & Dependency Installation (Official)

To use HoundMind with SunFounder PiDog hardware, install the following dependencies on your Raspberry Pi (Pi 4 recommended):

1. **Install system tools:**
   ```sh
   sudo apt install git python3-pip python3-setuptools python3-smbus
   ```
2. **Install robot-hat library:**
   ```sh
   cd ~/
   git clone -b v2.0 https://github.com/sunfounder/robot-hat.git
   cd robot-hat
   sudo python3 setup.py install
   ```
3. **Install vilib library:**
   ```sh
   cd ~/
   git clone -b picamera2 https://github.com/sunfounder/vilib.git
   cd vilib
   sudo python3 install.py
   ```
4. **Install pidog library:**
   ```sh
   cd ~/
   git clone https://github.com/sunfounder/pidog.git
   cd pidog
   sudo python3 setup.py install
   ```
5. **Install i2samp (for sound):**
  ```sh
  cd ~/pidog
  sudo bash i2samp.sh
  ```

Note: The guided installer performs steps 1–4 automatically. Run the recommended installer to have `robot-hat`, `vilib`, and `pidog` cloned and installed into the same Python environment as HoundMind:

```bash
bash scripts/install_houndmind.sh
```

If you want the installer to also run the PiDog audio helper (`i2samp.sh`), pass the `--run-i2samp` flag which invokes the helper script with `sudo`:

```bash
bash scripts/install_houndmind.sh --run-i2samp
```

The shell wrapper forwards arguments to `scripts/pidog_install.py` (see `--help` on that script for more options, e.g. `--auto-system-deps`).

Important: `pidog` is **not** available on PyPI, so it will never install via `pip install pidog`. Use the guided installer or clone the repo and install it manually.

For more details, see the [official PiDog repo](https://github.com/sunfounder/pidog) and [official docs](https://docs.sunfounder.com/projects/pidog/en/latest/).

## Path Planning (A* for Pi4)
HoundMind now supports grid-based path planning using the A* algorithm on Pi4. When enabled in `config/settings.jsonc`, the mapping module will plan a path from the current cell to a specified goal using the current map. The planned path is available in the runtime context for navigation and debugging.

- Enable with `"path_planning_enabled": true` in the mapping section of your config.
- Set a goal with `"goal": [x, y]`.
- The planned path will be available in the context as `path_planning`.

Example grid and output:
```python
from houndmind_ai.mapping.path_planner import astar

grid = [
    [0, 0, 0, 1, 0],
    [1, 1, 0, 1, 0],
    [0, 0, 0, 0, 0],
    [0, 1, 1, 1, 0],
    [0, 0, 0, 0, 0],
]
start = (0, 0)
goal = (4, 4)
path = astar(grid, start, goal)
print("Path:", path)
# Output: [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (3, 2), (4, 2), (4, 3), (4, 4)]
```

See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for more details.
