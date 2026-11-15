# HoundMind Install Guide (PiDog, Raspberry Pi 4 and 5)

Status: **guide** — install, verify, and recover. Written for a fresh Raspberry Pi OS Bookworm image.
Pairs with: `README.md` (the one-liner), `docs/FEATURES_GUIDE.md` (what each module does)

This guide installs HoundMind, the unified AI system for SunFounder PiDog. Simulation mode is no
longer supported. PackMind and CanineCore are now a single system.

**Preferred OS (recommended):** Raspberry Pi OS Bookworm (64-bit).

## Contents

- [Supported boards](#supported-boards) — Pi 4 and 5 only, and the HAT version rule
- [Python](#python) — 3.11–3.13, and what refuses what
- [Prerequisites](#prerequisites)
- [Recommended: Guided Install (Beginner-Friendly)](#recommended-guided-install-beginner-friendly)
- [Manual Install (Step-by-Step, Advanced)](#manual-install-step-by-step-advanced)
- [Bench checklist (before calling a build done)](#bench-checklist-before-calling-a-build-done)
- [Troubleshooting & Support Bundles](#troubleshooting--support-bundles)
- [Run](#run)
- [TLS for the control plane (optional)](#tls-for-the-control-plane-optional)
- [Feature Guide](#feature-guide)
- [Fallback: Run the Official PiDog Software](#fallback-run-the-official-pidog-software)
- [Notes](#notes)
- [PiDog & Dependency Installation (Official)](#pidog--dependency-installation-official)

---

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

### Power: a Pi 4 on the PiDog pack

The HAT feeds the Pi from the pack, so the pack's state is the Pi's supply. A Pi 4 under load - four
servos plus WiFi - draws more than a partly discharged pack can deliver through the HAT, and the
first symptom is not a warning: the Pi browns out and reboots, which reads exactly like a crash. The
runtime cannot prevent it, and `sensors.battery_poll_s` only reports what the HAT measures after the
fact.

Check the rail before a run, and after any reboot nobody asked for:

```bash
vcgencmd get_throttled     # 0x0 is clean; 0x50000 means under-voltage and throttling have occurred
```

Bits 16-18 are sticky for the life of the boot, so a non-zero value straight after a fresh boot means
the supply had already sagged. `docs/HARDWARE_TEST.md` [section 2](HARDWARE_TEST.md#2-before-you-start)
carries the full bit table.

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
- **Pi 4 and Pi 5**: both honour `--preset`. With `--preset auto` (the default) a Pi 4 installs
  **full** and a Pi 5 installs **lite**, because nothing has been measured on a Pi 5 yet and a
  full install of dlib/rtabmap on an untested board is not something to do unattended.
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
- `--preset auto|lite|full` (default `auto`: Pi 4 -> `full`, Pi 5 -> `lite`; an explicit choice wins on every board)

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
```

If your `python3` is already 3.11–3.13, `python3 -m venv .venv` is equivalent.

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
git clone -b 2.5.x https://github.com/sunfounder/robot-hat.git   # 2.5.x: docs/pidog/ is verified against it
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

Nothing on this list can be ticked from a workstation. [`docs/HARDWARE_TEST.md`](HARDWARE_TEST.md)
is the procedure: six steps, each with the exact command, the output to expect and what a failure
means, from the install verifier to the opt-in motion run.

Two rules that hold whatever that document says:

- Read-only first: `python -m tools.hardware_checkup --skip-motion`, then
  `python -m tools.smoke_test`. Neither can move the dog — on a checkup, leaving `--skip-motion`
  off *is* a motion run, and the smoke test disables `scanning` as well as the motors because it
  drives the head itself (#184).
- `--include-motion` only with clearance around the dog and a hand on the power.

What still has to be judged by a human, because no command here asserts it: obstacle avoidance
selecting sensible turns, stuck recovery completing, the watchdog holding motion on stale sensors
(`state.supervisor`), and the event log rotating at `event_log_max_mb`.

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

### Finding the device by name

The control plane advertises itself over mDNS (Avahi's protocol, already on Raspberry Pi OS
Bookworm), so a client does not have to be told an address that DHCP can change:

- Service type `_houndmind._tcp.local`, instance `<settings.api.discovery_name>._houndmind._tcp.local`
  (`houndmind._houndmind._tcp.local` by default).
- The TXT record carries `api_version`, `min_client` and `scheme` - the same values `/meta`
  publishes, and nothing else. No token, no device secret, no location.
- The host record is `<hostname>.local`, so `http://<hostname>.local:8420/` works from any machine
  that speaks mDNS (macOS and Windows 10+ do out of the box; Linux needs `avahi-daemon`, which
  Bookworm ships).

**When multicast is blocked** - a guest network, an IoT VLAN, a container, some managed switches -
discovery simply does not resolve. Nothing fails: the runtime logs one line and keeps serving.
Fall back to the address:

```bash
hostname -I                 # on the device: the LAN address
curl http://<pi-ip>:8420/api/v1/meta
```

Turn it off entirely with `"discovery_enabled": false` under `settings.api`; the address still
works.

### Stopping and restarting

The runtime is a foreground process: it runs until you stop it. **No service unit ships with this
tree** — there is no `houndmind.service`, so `sudo systemctl restart houndmind` has nothing to
restart. That is a decision, not an omission: a restart policy for a robot has to say what happens
to a gait that is halfway through, and no such rule is settled yet.

| Task | What to do |
|---|---|
| Stop | `Ctrl-C` in the terminal the runtime is running in. The tick finishes and the HAL is closed. |
| Restart | Stop it, then start it again with the command above. A routine file added or edited since boot is read at this point (`docs/ROUTINES.md`). |
| Check it is running | `curl http://127.0.0.1:8420/api/v1/health` answers without a token; `GET /api/v1/state` needs one. |
| Find the token | `~/.houndmind/api_token`, written `0600` on the first start. Read it into a variable — do not paste it into a URL. |
| Change the port | `settings.api.port` (default `8420`). |

If the process died on its own, `logs/houndmind.log` says why: the runtime logs the exception, not
only the exit.

## TLS for the control plane (optional)

The control plane serves **plaintext HTTP** by default: the device token, every command and every
camera frame cross the LAN in the clear (`docs/CONTROL_API.md` [§1](CONTROL_API.md#1-authentication) names what that exposes and the
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
   git clone -b 2.5.x https://github.com/sunfounder/robot-hat.git
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
