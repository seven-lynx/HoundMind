# HoundMind Install Guide (PiDog, Raspberry Pi 4 and 5)

Status: **guide** — install, verify, and recover. Written for a fresh Raspberry Pi OS Bookworm image.
Version: v2026.01.18 • Author: 7Lynx
Pairs with: `README.md` (the one-liner), `docs/FEATURES_GUIDE.md` (what each module does)

This guide installs HoundMind, the unified AI system for SunFounder PiDog. Simulation mode is no
longer supported. PackMind and CanineCore are now a single system.

**Preferred OS (recommended):** Raspberry Pi OS Bookworm (64-bit).

## Supported boards

**Raspberry Pi 4 and Raspberry Pi 5 only.** Pi 3 support was dropped in the 2026.11 refactor: it is
the reason the loop used to run at 5 Hz and vision shipped off. `v2026.01.18` is the last release
that runs on one, and the installer reads the device tree and stops with that release named rather
than installing something half-working.

### A Pi 5 edition is a board *and* a HAT

SunFounder's own position: the Pi 5 is **software**-compatible with the PiDog code, but the standard
**Robot HAT V4 supplies 5V/3A where the Pi 5 requires 5V/5A**, so a Pi 5 on a V4 can shut down
mid-run, and some V4 owners report WiFi trouble. **Robot HAT V5 is the combination that is
supported.** A V4 is fine for a bench test; it is not an edition this project can call working.

The runtime cannot see which HAT is fitted, so this is not a configuration key. It is a power-supply
fact, and the reason the Pi 5 edition is documented as V5-only.

## Python

- Supported: **3.11, 3.12, 3.13** — the range `pyproject.toml` declares. Bookworm ships 3.11 (the
  recommended image); Trixie ships 3.13.
- **3.10 is not supported.** It is end of life, and `pip install` refuses the package on it.
- The installer creates the virtualenv with the interpreter it runs under. To force one:
  `PYTHON=python3.11 bash scripts/install_houndmind.sh`.
- If an existing `.venv` was created with an unsupported or different Python minor version, the installer will automatically recreate it to keep the environment consistent.
- If you encounter build failures on newer OS releases (Trixie or later), consider switching to Bookworm or use the `--preset lite` option.

## Prerequisites
- Raspberry Pi OS Lite (no desktop environment) with I2C enabled.
- A Raspberry Pi 4 or 5, with a Robot HAT V5 (or a V4 for a bench test) seated on the 40-pin header.
- Python 3.11, 3.12 or 3.13 (Bookworm's `python3` is 3.11).
- Internet access for dependency downloads.

Check the interpreter the installer will run under:

```bash
python3 --version
```

## Recommended: Guided Install (Beginner-Friendly)

The installer script will:
1) Create a local virtual environment (unless you skip it).
2) Install system packages needed for PiDog (Linux only, uses `sudo`).
3) Install SunFounder dependencies (`robot-hat`, `vilib`, `pidog`) **into the same environment**.
4) Install HoundMind and verify imports.

### Board detection
- **Pi 5**: honours `--preset`; the default is **lite**, because nothing has been measured on a Pi 5
  yet and a full install of dlib/rtabmap on an untested board is not something to do unattended.
- **Pi 4**: still forces the **full** preset, so `--preset` is ignored on a Pi 4. That is a known
  defect; it is fixed with the installer rewrite rather than quietly changed here.
- **Anything older**: refused before anything is installed, with the last supporting release named.

You can override with:
- `--preset lite`
- `--preset full`

When using the **full** preset, the installer verifies heavier imports (NumPy, SciPy, OpenCV, face_recognition, sounddevice). For most users, **lite** is recommended unless you need advanced vision/voice features.

```bash
bash scripts/install_houndmind.sh
```

Optional flags:
- `--skip-venv` (use the current Python environment)
- `--force-recreate-venv` (delete and recreate the venv even if it exists)
- `--skip-pidog` (skip SunFounder install if already done)
- `--run-i2samp` (runs the PiDog audio setup script)
- `--preset auto|lite|full` (auto detects Pi model)

Additional installer flags (new):
- `--build-rtabmap`: clone, build and install RTAB‑Map and its Python bindings into the environment (runs `cmake`/`make` and requires system build deps and `sudo`). Useful for Pi 4/5 full installs.
- `--no-rtabmap`: explicitly skip any RTAB‑Map build/install during this run (useful when you want the full preset but will install RTAB‑Map later by hand).
- `--auto-system-deps`: automatically install system packages via `apt` (needed before building heavy native dependencies).

Installer behavior for i2samp:
- If you pass `--run-i2samp` the installer will run `i2samp.sh` after installing `pidog`.
- You can also set `RUN_I2SAMP=1` to enable the same behavior non-interactively (useful for CI or scripts).
- When running the top-level `scripts/install_houndmind.sh` interactively, the installer will prompt to run the PiDog audio helper by default (you can answer yes/no).

Examples: build RTAB-Map during install (Pi 4/5; long-running):

```bash
# Let the installer attempt to install apt system deps and build RTAB-Map
bash scripts/install_houndmind.sh --build-rtabmap --auto-system-deps

# Force a specific interpreter when running the installer
PYTHON=python3.11 bash scripts/install_houndmind.sh --build-rtabmap --auto-system-deps
```

## Manual Install (Step-by-Step, Advanced)

### 1) Create and activate a virtual environment

```bash
python3.11 -m venv .venv
. .venv/bin/activate

If your `python3` is already 3.11–3.13, `python3 -m venv .venv` is equivalent.
```

### 2) Install PiDog system dependencies (Linux, Raspberry Pi OS Lite)

```bash
sudo apt-get update
sudo apt-get install -y git python3-pip python3-setuptools python3-smbus
```

### Full system dependencies for vision/face/SLAM

If you plan to use the full feature set on a Pi 4 or 5 (OpenCV, `face_recognition`/`dlib`, RTAB-Map), install the additional build tools and libraries before attempting `pip install` for heavy packages. These are recommended when using the `--auto-system-deps` flag with the guided installer or when preparing a board for development:

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
- RTAB-Map (`rtabmap-py`) is often built from source on a Pi 4/5; see `scripts/install_rtabmap_pi4.md` for detailed RTAB-Map build steps.
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
```

If you are on a Pi 4 or 5 and want the full feature set, replace `requirements-lite.txt` with `requirements.txt` (or use the installer `--preset full` / `--auto-system-deps` to trigger a full install):

```bash
python -m pip install -r requirements.txt
```

### 5) Verify the install

```bash
python -m tools.installer_verify  # recommended after `pip install -e .` or with `PYTHONPATH=src`
```

## Bench checklist (before calling a build done)

Nothing here can be ticked from a workstation. Run it on the dog, on blocks, with clearance, and
with the camera covered until the camera rows.

### Sensors
- [ ] Ultrasonic distance reads are stable (no spikes at rest).
- [ ] Touch sensor updates are reliable (debounce acceptable).
- [ ] Sound detection and direction work in normal room noise.
- [ ] IMU readings are stable; heading integration does not drift excessively.

### Scanning and navigation
- [ ] Three-way scan returns valid left/right/forward values.
- [ ] Sweep scan covers its full range and returns the head to centre.
- [ ] The scan interval matches settings and the tick does not stutter while a sweep runs.
- [ ] Obstacle avoidance selects sensible turns; stuck recovery triggers and completes.
- [ ] A clear-path streak reduces scan jitter.

### Safety
- [ ] `POST /api/v1/stop` stops the dog from a client, and a dropped connection does too.
- [ ] Emergency stop triggers at the configured distance (with `settings.safety.enabled: true`).
- [ ] Tilt protection triggers and its cooldown behaves.
- [ ] The watchdog holds motion on stale sensors or scans and says so in `state.supervisor`.
- [ ] No recovery poses the dog: recovery is stop-and-report by design.

### Mapping and logging
- [ ] Openings and safe paths appear in the event log.
- [ ] Event log JSONL files are created and rotate at `event_log_max_mb`.

### Tools
- [ ] `python -m tools.hardware_checkup --skip-motion` passes its basic checks.
- [ ] `python -m tools.smoke_test` completes with no errors. Add `--include-motion` only with
      clearance around the dog and a hand on the power.

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
   - The repo includes a support-bundle helper available as a module: `python -m tools.collect_support_bundle` (run inside the venv) or run the script directly `python src/tools/collect_support_bundle.py`.
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
Run HoundMind from the install virtualenv. Recommended methods:

```bash
# Activate venv then run
source .venv/bin/activate
python -m houndmind_ai

# Or run with the venv Python directly
.venv/bin/python -m houndmind_ai
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m houndmind_ai
```

## TLS for the control plane (optional)

The control plane serves **plaintext HTTP** by default: the device token, every command and every
camera frame cross the LAN in the clear (`docs/CONTROL_API.md` §1 names what that exposes and the
workarounds). Turning TLS on is one setting:

```jsonc
// config/settings.jsonc
"api": {
  "tls_enabled": true,
  "tls_cert": "~/.houndmind/tls/cert.pem",
  "tls_key": "~/.houndmind/tls/key.pem"
}
```

On the next start, if neither file exists, a **self-signed** certificate is generated for this device
(hostname plus every address it answers on, valid 10 years, key `0600`). Nothing is generated while
`tls_enabled` is `false`. Generation needs the `openssl` binary — `openssl version` should answer on
Raspberry Pi OS; if it does not, the control plane disables itself with a message naming the missing
command and the dog keeps running without an API.

The certificate is self-signed, so each client trusts it once:

- **Desktop browser** — open `https://<pi-ip>:8420/`, accept the warning once ("Advanced" →
  "Proceed"), or import `~/.houndmind/tls/cert.pem` into the OS trust store.
- **Phone** — transfer `cert.pem` and install it as a trusted CA (Android: *Settings → Security →
  Encryption & credentials → Install a certificate → CA certificate*; iOS: AirDrop it, then
  *Settings → General → VPN & Device Management*, and enable full trust). An Android HTTP client
  rejects a self-signed certificate by default, so **an app without its own trust step will not
  connect** — the browser workaround is to use the web app, which is same-origin.
- **curl** — `curl --cacert cert.pem https://<pi-ip>:8420/api/v1/meta`.

`GET /api/v1/meta` reports `"scheme"` (`"http"` or `"https"`) so a client can tell a wrong-scheme
attempt from a wrong host.

## Feature Guide
See [FEATURES_GUIDE.md](FEATURES_GUIDE.md) for what each feature does, how to use it, and how to disable it.

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
