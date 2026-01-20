# HoundMind Install Guide (PiDog, Pi 3/4/5)

Version: v2026.01.18 • Author: 7Lynx

This guide installs HoundMind, the unified AI system for SunFounder PiDog. Simulation mode is no longer supported. PackMind and CanineCore are now a single system.

**Preferred OS (recommended):** Raspberry Pi OS Bookworm (64-bit) with Python 3.11.

IMPORTANT: Bookworm is the preferred distribution for this project because many heavy, platform-specific packages (for example `dlib`/`face_recognition`, `pyaudio`, and `rtabmap-py`) provide prebuilt wheels for Bookworm but may not have wheels available for newer releases such as Trixie (Python 3.13). If you use Trixie and encounter build failures during the full install, switch to Bookworm or use the `--preset lite` option.

## Prerequisites
- Raspberry Pi OS Lite (no desktop environment) with I2C enabled.
- Python 3.9+ available on the system.
- Internet access for dependency downloads.

## Recommended: Guided Install (Beginner-Friendly)

The installer script will:
1) Create a local virtual environment (unless you skip it).
2) Install system packages needed for PiDog (Linux only, uses `sudo`).
3) Install SunFounder dependencies (`robot-hat`, `vilib`, `pidog`) **into the same environment**.
4) Install HoundMind and verify imports.

### Pi3 vs Pi4 Detection
- **Pi 3**: installer uses the **lite** preset for best compatibility.
- **Pi 4/5**: installer defaults to **full** if `requirements.txt` exists; otherwise uses **lite**.

You can override with:
- `--preset lite`
- `--preset full`

When using the **full** preset, the installer verifies heavier imports (NumPy, SciPy, OpenCV, face_recognition, sounddevice). For most users, **lite** is recommended unless you need advanced vision/voice features.

```bash
bash scripts/install_houndmind.sh
```

Optional flags:
- `--skip-venv` (use the current Python environment)
- `--skip-pidog` (skip SunFounder install if already done)
- `--run-i2samp` (runs the PiDog audio setup script)
- `--preset auto|lite|full` (auto detects Pi model)

Installer behavior for i2samp:
- If you pass `--run-i2samp` the installer will run `i2samp.sh` after installing `pidog`.
- You can also set `RUN_I2SAMP=1` to enable the same behavior non-interactively (useful for CI or scripts).
- When running the top-level `scripts/install_houndmind.sh` interactively, the installer will prompt to run the PiDog audio helper by default (you can answer yes/no).

## Manual Install (Step-by-Step, Advanced)

### 1) Create and activate a virtual environment

```bash
python3 -m venv .venv
. .venv/bin/activate
```

### 2) Install PiDog system dependencies (Linux, Raspberry Pi OS Lite)

```bash
sudo apt-get update
sudo apt-get install -y git python3-pip python3-setuptools python3-smbus
```

### Full (Pi4) system dependencies for vision/face/SLAM

If you plan to use the full feature set on Pi4 (OpenCV, `face_recognition`/`dlib`, RTAB-Map), install the additional build tools and libraries before attempting `pip install` for heavy packages. These are recommended when using the `--auto-system-deps` flag with the guided installer or when preparing a Pi4 for development:

```bash
sudo apt-get update
sudo apt-get install -y \
   build-essential cmake g++ git python3-dev pkg-config \
   libatlas-base-dev libopenblas-dev liblapack-dev \
   libjpeg-dev libtiff-dev libavcodec-dev libavformat-dev libswscale-dev \
   libv4l-dev libxvidcore-dev libx264-dev libgtk-3-dev \
   libboost-all-dev libeigen3-dev libusb-1.0-0-dev libsqlite3-dev libopenni2-dev libproj-dev \
   libasound2-dev libportaudio2 portaudio19-dev
```

Notes:
- `face_recognition` requires `dlib` which typically needs `cmake` and a C++ toolchain; installing the packages above will make building `dlib` much smoother.
- RTAB-Map (`rtabmap-py`) is often built from source on Pi4; see `scripts/install_rtabmap_pi4.md` for detailed RTAB-Map build steps.
- On Raspberry Pi OS Trixie (Python 3.13), many packages (e.g., `face_recognition`, `pyaudio`) may not have wheels yet. If you hit build errors, use Bookworm (Python 3.11) or install the **lite** preset.

### 3) Install SunFounder PiDog libraries into the same Python environment

```bash
git clone -b v2.0 https://github.com/sunfounder/robot-hat.git
python -m pip install ./robot-hat

git clone -b picamera2 https://github.com/sunfounder/vilib.git
python -m pip install ./vilib

git clone https://github.com/sunfounder/pidog.git
python -m pip install ./pidog
```

Note: `pidog` is **not** published on PyPI. Do not add it to your `requirements.txt`; install from the repo as shown above or use the guided installer.

Optional audio setup:

```bash
cd pidog
sudo bash i2samp.sh
```

### 4) Install HoundMind in the same Python environment

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-lite.txt
python -m pip install -e .

If you are on Pi4 and want the full feature set, replace `requirements-lite.txt` with `requirements.txt` (or use the installer `--preset full` / `--auto-system-deps` to trigger a full install):

```bash
python -m pip install -r requirements.txt
```
```

### 5) Verify the install

```bash
python -m tools.installer_verify  # recommended after `pip install -e .` or with `PYTHONPATH=src`
```

## Troubleshooting & Support Bundles

If you run into install or runtime issues, follow this checklist to gather information and resolve common failures.

- **Missing imports (ModuleNotFoundError like `No module named 'tools'`):**
   - Ensure HoundMind is installed into the same environment where you run tests/commands: `python -m pip install -e .`.
   - When running tests or scripts directly from the repo, set `PYTHONPATH=src` or use the editable install above.

- **Build failures for heavy packages (OpenCV, dlib/face_recognition, rtabmap-py):**
   - Prefer Raspberry Pi OS Bookworm (Python 3.11) for prebuilt wheels. On newer OS (Trixie/Python 3.13+) many wheels may be missing.
   - Use the **lite** preset if you don't need vision/voice: `python -m pip install -r requirements-lite.txt`.
   - Install the system build packages listed earlier before attempting `pip install` for heavy packages.

- **How to collect a support bundle (useful when filing issues):**
    - The repo includes a support-bundle helper available as a module: `python -m tools.collect_support_bundle` or run the script directly `python src/tools/collect_support_bundle.py`.
   - Example: `python -m tools.collect_support_bundle /tmp/support.zip`.
   - Set a trace id to correlate logs and telemetry: on Linux/macOS `export HOUNDMIND_TRACE_ID=trace-12345`, on PowerShell `setx HOUNDMIND_TRACE_ID trace-12345` then reproduce the issue and collect a bundle.
   - Support bundles include `metadata.json` (timestamp, git commit, trace_id), logs, and key config files — include this bundle when opening issues.

- **Pre-push local checks:**
   - The repo provides a pre-push hook that runs `ruff` and `pytest` before pushing. Enable it with:
      ```powershell
      git config core.hooksPath .githooks
      ```
   - If the hook prevents a push during urgent work you can bypass it with `git push --no-verify` (use sparingly).

- **Common runtime checks:**
   - Inspect JSON logs in `logs/houndmind.log` or use the support bundle's `metadata.json` for timestamps and trace ids.
   - Run the lightweight smoke test for on-device validation: `python -m tools.smoke_test --cycles 5 --tick-hz 5` (use with caution on hardware).
   - Re-run `python -m tools.installer_verify --preset lite` to validate a minimal working environment.

- **When opening an issue:**
   - Attach the support bundle and include the `metadata.json` trace id and git commit SHA.
   - Include the exact command you ran and the output of `python -m pip freeze` from the environment used.


## Run
```bash
python -m houndmind_ai
```

## Feature Guide
See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) for what each feature does, how to use it, and how to disable it.

## Fallback: Run the Official PiDog Software

If HoundMind ever fails, you can still run the original PiDog examples from the SunFounder repo:

```bash
# Replace <example>.py with an example script from the official PiDog repo.
python pidog/examples/<example>.py
```

## Notes
- This project runs on real PiDog hardware only.
- Optional modules (vision/voice/energy-emotion) are disabled by default.
- Keep HoundMind and PiDog installed in the **same Python environment** to avoid import errors.
	- If you use a virtual environment, install **everything** inside it (recommended for beginners).
	- If you prefer system-wide installs, skip the venv and install everything system-wide (advanced users only).

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

For more details, see the [official PiDog repo](https://github.com/sunfounder/pidog) and [official docs](https://docs.sunfounder.com/projects/pidog/en/latest/).
