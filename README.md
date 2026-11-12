# HoundMind (PiDog Unified AI)

Version: v2026.01.18 • Author: 7Lynx

HoundMind is a unified AI control framework for the SunFounder PiDog. Simulation mode is no longer supported; all features require real PiDog hardware. PackMind and CanineCore are now a single system.

## Current scope
- Target hardware: **Raspberry Pi 4 and 5** (recommended: Raspberry Pi OS Lite, no desktop). Pi 3 support was dropped in the 2026.11 refactor; `v2026.01.18` is the last release that runs on one.
- Simulation mode is not supported; all features require real hardware.
- All features (movement, sensors, navigation, mapping, safety, logging) are unified in a single runtime.
- Vision, voice, and Pi4/5 optional modules are **disabled by default**; basic watchdogs are enabled.
- Safety and throttling features are **opt-in** (disabled by default for bug testing).

## Installer Quickstart (Recommended)
Run the automated installer on a Raspberry Pi:

```bash
bash scripts/install_houndmind.sh
```

This installs the SunFounder PiDog dependencies **and** HoundMind in the same environment. It reads the board from the device tree, refuses a Pi 3 or older, and picks the matching profile. For manual steps, see [docs/INSTALL.md](docs/INSTALL.md).

## Before You Start (Pi OS Checklist)
- Flash Raspberry Pi OS and complete first boot setup.
- Preferred OS: **Raspberry Pi OS Bookworm (64-bit)**, which ships Python 3.11. HoundMind supports Python 3.11–3.13; 3.10 is end of life and is refused by `pip install`.

IMPORTANT: Bookworm is recommended because many heavy packages used by the full preset have prebuilt wheels for Bookworm but may not yet provide wheels for newer distributions (for example, Trixie with Python 3.13). If you hit build errors, switch to Bookworm or run the installer with `--preset lite`.
- A **Robot HAT V5** is the supported HAT for a Pi 5. The V4 supplies 5V/3A where the Pi 5 requires 5V/5A, so a Pi 5 on a V4 can shut down mid-run; see [docs/INSTALL.md](docs/INSTALL.md).
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

## Start HoundMind
- Recommended: run HoundMind inside the install virtualenv.

- Activate the venv, then run:

```bash
source .venv/bin/activate
python -m houndmind_ai
```

- Or run directly with the venv Python (no activation):

```bash
.venv/bin/python -m houndmind_ai
```

- On Windows PowerShell use:

```powershell
.venv\Scripts\Activate.ps1
python -m houndmind_ai
```

### Developer installation (editable)

For development you can install HoundMind in editable mode and select a dependency preset. Use the `lite` preset for a minimal developer environment, or the `full` preset to install optional vision/audio/SLAM packages (heavy, may require system build tools):

```bash
# Minimal (fast) development install
pip install -e .[lite]

# Full install (may need build tools and can take a long time on Pi)
pip install -e .[full]
```

If you prefer not to install editable packages you can run code directly with `PYTHONPATH=src` (Linux/macOS) or by adding `src` to `PYTHONPATH` on Windows. For example:

```bash
PYTHONPATH=src python -m houndmind_ai
```

## Hardware checkup
- Run a minimal sensor + motion check on the PiDog hardware:
 - Run a minimal sensor + motion check on the PiDog hardware:
  - `python -m tools.hardware_checkup` (recommended after `pip install -e .` or with `PYTHONPATH=src`)
- Use `--skip-motion` to avoid any movement.

## Automated smoke test
- Run a non-motion smoke test (sensors + scan + mapping):
  - `python -m tools.smoke_test` (recommended after `pip install -e .` or with `PYTHONPATH=src`)
- Add `--include-motion` to allow navigation/motor actions.

## Configuration
Edit [config/settings.jsonc](config/settings.jsonc) to enable/disable modules and tune behavior (comments included). Optional modules should remain `enabled: false` until tested.
Action catalogs live in [config/actions.jsonc](config/actions.jsonc) so the main config stays clean and readable.

## Profiles
`profile` ships as `auto`, which reads the board from the device tree and picks its profile. Override it in [config/settings.jsonc](config/settings.jsonc) or via `HOUNDMIND_PROFILE`:
- `pi4` — 10 Hz loop, Pi 4/5 feature flags permitted
- `pi5` — the same cadence and enablement, plus thermal warning thresholds that suit a Pi 5

A Pi 3 or older is refused at load, with the last release that supported it named (`v2026.01.18`).

Pi4/5 modules (vision, face recognition, semantic labeling, SLAM) remain opt-in.


## SLAM (RTAB-Map for Pi4/5)
For robust mapping and localization on Pi4/5, HoundMind supports RTAB-Map as the recommended SLAM backend. See [scripts/install_rtabmap_pi4.md](scripts/install_rtabmap_pi4.md) for installation steps and troubleshooting.

## Feature Guide
See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for what each feature does, how to use it, and how to disable it.

## Control plane and web app

One process, one port. Enable it with `modules.api.enabled = true` (default in the shipped
config) and open:

- `http://<pi-ip>:8420/` — web app: telemetry, camera, hold-to-move d-pad, event feed
- `http://<pi-ip>:8420/api/v1/state` — JSON snapshot (token required)
- `http://<pi-ip>:8420/api/v1/camera/stream` — MJPEG (token required)

Everything under `/api/v1` needs the token from `~/.houndmind/api_token`; `/health` and `/meta`
do not. The full contract is [docs/CONTROL_API.md](docs/CONTROL_API.md), and the token and pairing
story is §26 of [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md).

The old per-feature servers are gone — there is no separate telemetry dashboard on 8092, vision
stream on 8090, voice control on 8091 or face enrollment on 8088. Each was an unauthenticated
listener; the control plane replaces all four behind one token. A `settings.*.http` block left over
from an older config is a load-time error with a suggestion to delete it.

Configuration (example `config/settings.jsonc` snippet):

```jsonc
"api": {
  // Reachable on the LAN by design: the token is the security boundary.
  "host": "0.0.0.0",
  "port": 8420,
  "token_path": "~/.houndmind/api_token"
}
```

See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for every key and its default.

## Project layout (key paths)
- `src/houndmind_ai/` — core runtime and modules
- `src/tools/` — device CLIs, run as `python -m tools.<name>`
- `config/settings.jsonc` — module enablement and parameters
- `tests/` — hardware-free unit tests (`PYTHONPATH=src python -m pytest`)

## Documentation
[docs/README.md](docs/README.md) is the index: every file, its status, and when to read it.

| I want to… | Read |
|---|---|
| Install and verify on a Pi | [docs/INSTALL.md](docs/INSTALL.md) |
| Know what a feature does, or turn it off | [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) |
| Write a module, or find a context key | [docs/HOUNDMIND_PROGRAMMING_GUIDE.md](docs/HOUNDMIND_PROGRAMMING_GUIDE.md) |
| Drive the vendor `pidog` library directly | [docs/PIDOG_PROGRAMMING_GUIDE.md](docs/PIDOG_PROGRAMMING_GUIDE.md) |
| Build a client against the API | [docs/CONTROL_API.md](docs/CONTROL_API.md) |
| Understand why the runtime is shaped this way | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Read the logs, or build a support bundle | [docs/LOGGING.md](docs/LOGGING.md) |
| Know what the code looked like before the refactor | [docs/BASELINE.md](docs/BASELINE.md) |

## Notes
- This project now runs **only on the real PiDog hardware** (no simulation/shim mode).
- PackMind and CanineCore are now unified; all features are part of a single runtime.
- Hardware access is required for `houndmind_ai/hal/*` modules.
- Watchdogs are enabled by default. The watchdog never poses the dog: when sensor or scan data
  goes stale it holds motion with a `stop`, and it restarts a module only after that module has
  actually stopped ticking.

## Troubleshooting (Quick)
- **`ModuleNotFoundError: pidog`** → Install the official PiDog repo first, then HoundMind in the same environment.
- **Camera not opening** → Enable camera in OS settings; try a different device index.
- **Audio not working** → Ensure PortAudio headers are installed; rerun audio setup.
- **Port in use** → `settings.api.port` is the only listener (8420). Change it there, or set
  `modules.api.enabled = false` to remove the network surface.

- **Build errors for heavy packages (face_recognition, dlib, pyaudio, rtabmap-py)** → These commonly occur on newer Raspberry Pi OS releases (for example, Trixie with Python 3.13) because prebuilt wheels are not yet available. Preferred OS: **Raspberry Pi OS Bookworm (64-bit, Python 3.11)**. If you see many `wheel`/`gcc`/`dlib` build failures during the full install, either switch to Bookworm or run the installer with `--preset lite`.

- **`ERROR: Could not find a version that satisfies the requirement pidog`** → `pidog` is not on PyPI; the guided installer (`scripts/install_houndmind.sh`) will clone and install it from the SunFounder repo into the same environment. See `docs/INSTALL.md` for manual steps.

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
| Mapping                        | Enabled     |                                       |
| Behavior                       | Enabled     |                                       |
| Attention                      | Enabled     |                                       |
| Watchdog                       | Enabled     | Holds motion on stale data; restarts stopped modules with backoff |
| Event Logging                  | Enabled     |                                       |
| Decision Feed                  | Enabled     | Last 200 decisions behind `/decisions`; JSONL off by default |
| Control Plane (REST/WS/web)    | Enabled     | Port 8420, token-gated; `modules.api`  |
| LED Manager                    | Enabled     |                                       |
| Calibration                    | Enabled     |                                       |
| Safety                         | Disabled    | Opt-in for emergency stop/tilt        |
| Health Monitor                 | Disabled    | Opt-in for CPU/mem/temp/throttling    |
| Balance                        | Disabled    | Opt-in for IMU posture                |
| Sensor Health                  | Disabled    | Opt-in; staleness badge + LED colour   |
| Vision (legacy vilib)          | Disabled    | Opt-in, legacy camera                 |
| Voice (legacy input)           | Disabled    | Opt-in, legacy voice                  |
| Voice Assistant (Pi4)          | Disabled    | Opt-in, requires Pi4                  |
| Face Recognition (Pi4)         | Disabled    | Opt-in, requires Pi4                  |
| Pi4 Vision Feed (Pi4)          | Disabled    | Opt-in, requires Pi4                  |
| Semantic Labeler (Pi4)         | Disabled    | Opt-in, requires Pi4                  |
| SLAM (Pi4)                     | Disabled    | Opt-in, requires Pi4                  |
| Telemetry Dashboard            | Removed     | Use the control plane / web app        |

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

The installer can optionally run the PiDog audio helper (`i2samp.sh`). You can:

- Pass `--run-i2samp` to `scripts/install_houndmind.sh`.
- Set the environment variable `RUN_I2SAMP=1` to enable it non-interactively.
- When run interactively the installer will prompt whether to run `i2samp.sh`.

Example (interactive):

```bash
bash scripts/install_houndmind.sh
```

Example (non-interactive):

```bash
RUN_I2SAMP=1 bash scripts/install_houndmind.sh
```

Use `scripts/install_houndmind.sh --help` or see `docs/INSTALL.md` for installer flags (e.g. `--auto-system-deps`).

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
