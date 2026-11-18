# HoundMind Install Guide (PiDog, Raspberry Pi 4 and 5)

Status: **guide** — install, verify, and recover. Written for a fresh Raspberry Pi OS Bookworm image.
Pairs with: `README.md` (the one-liner), `docs/FEATURES_GUIDE.md` (what each module does)

This guide installs HoundMind, the unified AI system for SunFounder PiDog. Simulation mode is no
longer supported. PackMind and CanineCore are now a single system.

**Preferred OS (recommended):** Raspberry Pi OS Bookworm (64-bit).

## Contents

- [Headless over SSH: the path most people take](#headless-over-ssh-the-path-most-people-take) — clone,
  install, enable the service, verify, open the console
- [Supported boards](#supported-boards) — Pi 4 and 5 only, and the HAT version rule
- [Python](#python) — 3.11–3.13, and what refuses what
- [Prerequisites](#prerequisites)
- [Recommended: Guided Install (Beginner-Friendly)](#recommended-guided-install-beginner-friendly)
- [Manual Install (Step-by-Step, Advanced)](#manual-install-step-by-step-advanced)
- [What ships enabled](#what-ships-enabled)
- [Bench checklist (before calling a build done)](#bench-checklist-before-calling-a-build-done)
- [Troubleshooting & Support Bundles](#troubleshooting--support-bundles)
- [Run](#run)
- [TLS for the control plane (optional)](#tls-for-the-control-plane-optional)
- [Feature Guide](#feature-guide)
- [Fallback: Run the Official PiDog Software](#fallback-run-the-official-pidog-software)
- [Notes](#notes)
- [PiDog & Dependency Installation (Official)](#pidog--dependency-installation-official)

---

## Headless over SSH: the path most people take

A PiDog does not need a monitor: the console is a web page served by the dog. The whole path is eight
steps, and each one links to the detail further down.

| # | Step | Command / where |
|---|---|---|
| 1 | Flash **Bookworm 64-bit**, boot with the 40-pin HAT seated, and get on the network | `ssh pi@<address>` |
| 2 | Enable **I2C and SPI**, then reboot - the sound sensor is an SPI device and is dead without it | `sudo raspi-config nonint do_i2c 0`, `sudo raspi-config nonint do_spi 0`, [Prerequisites](#prerequisites) |
| 3 | Clone and install | `git clone https://github.com/seven-lynx/HoundMind.git ~/HoundMind && cd ~/HoundMind && bash scripts/install_houndmind.sh` |
| 4 | Read the preflight - free space, pack health, camera | printed before anything downloads; `Preflight: OK` is the normal line |
| 5 | Start the service and check the logs | `sudo systemctl start houndmind`, `journalctl -u houndmind -n 50` |
| 6 | Prove the sensors without moving the dog | `python -m tools.hardware_checkup --skip-motion` - exit 0 and four valid flags |
| 7 | Open the console from your laptop | `http://<pi-address>:8420`, then paste the token from `~/.houndmind/api_token` |
| 8 | Optional: TLS so the console is installable, and the phone notifications | [TLS for the control plane](#tls-for-the-control-plane-optional) |

Two things that surprise people, both measured on a bench dog:

- **The service resumes; a command in flight does not.** After a reboot the modules come back, and a
  gait cannot survive it: `motion_command` and the intent board are context-only and every intent
  expires, so a routine mid-run is lost rather than replayed. **Autonomy does come back** — the runtime
  starts in `mode idle`, where `behavior` and the navigator may drive, so a dog with those modules
  enabled can start moving on its own. Park it with `mode rest` if it must stay put.
- **A second process cannot open the dog.** The runtime holds `~/.houndmind/run.lock`; a tool started
  while it runs exits **3** with `the servo bus is owned by pid N (runtime)` instead of hanging. That
  is the answer to "why did `hardware_checkup` print nothing?", not a dead tool.

A longer walk-through, including the traps that cost real bench time (`origin/master`, `pyaudio` on
the lite preset, `/tmp` being wiped at boot, the journald `Storage=volatile` default), is
[`SSH_INSTALL_AND_BRINGUP.md`](SSH_INSTALL_AND_BRINGUP.md).

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
- If you encounter build failures on newer OS releases (Trixie or later), switch to Bookworm: this release supports **Bookworm 64-bit only**, and the installer refuses any other release with one line (`--allow-unsupported-os` overrides it for a maintainer who wants to see how far it gets).

## Prerequisites
- Raspberry Pi OS Lite (no desktop environment) with **I2C and SPI** enabled. The HAT's devices need
  I2C; the sound sensor (`dog.ears`) is an SPI device and is dead without it (#204).
- A Raspberry Pi 4 or 5, with a Robot HAT V5 (or a V4 for a bench test) seated on the 40-pin header.
- Python 3.11, 3.12 or 3.13 (Bookworm's `python3` is 3.11).
- Internet access for dependency downloads.

Both interfaces are one command each, and take effect after a reboot:

```bash
sudo raspi-config nonint do_i2c 0      # 0 enables, 1 disables - the numbering is inverted
sudo raspi-config nonint do_spi 0
sudo reboot
ls /dev/i2c-1 /dev/spidev0.0           # both must exist before the installer runs
```

The installer runs that pair for you on a Linux host when `raspi-config` is present; it cannot
reboot the Pi, so it prints the reminder instead.

Check the interpreter the installer will run under:

```bash
python3 --version
```

## Recommended: Guided Install (Beginner-Friendly)

The installer script will:
1. **Refuse an OS it was not validated on** - Bookworm 64-bit - before anything is written
   (`--allow-unsupported-os` overrides that for a maintainer).
2. Print a **preflight**: free space (it refuses under 2 GB), pack health from
   `vcgencmd get_throttled`, and whether a camera node exists.
3. Enable **I2C and SPI**, and install the apt packages the HAT, the camera binding and the audio
   stack need.
4. Create the venv with **`--system-site-packages`**, so Debian-provided bindings (`picamera2`) are
   importable at all.
5. Install SunFounder dependencies (`robot-hat`, `vilib`, `pidog`) **into the same environment**,
   along with the modules `robot_hat doctor` checks for - `pyserial` included, whose import name is
   `serial` and which nothing used to install (#255).
6. Copy the vendor `sounds/` directory to `~/pidog/sounds`, where `Pidog.speak()` looks for it: the
   wheel carries code only, so barks and growls were silent on a fresh install (#256).
7. Install HoundMind, then install and **enable** `houndmind.service` (`--no-service` skips it).
8. Verify the imports, and the camera binding on a Pi, ending at `Installer check: OK`.

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
- `--no-service` (do not install or enable `houndmind.service`; the unit is still in the tree at
  `packaging/systemd/houndmind.service`)
- `--allow-unsupported-os` (continue on a release other than Bookworm; not supported, for maintainers)

Additional installer flags (new):
- `--build-rtabmap`: clone, build and install RTAB‑Map and its Python bindings into the environment (runs `cmake`/`make`, needs system build deps and `sudo`, and takes the better part of an hour on a Pi 4). It is the **only** way that build happens: `--preset full` no longer implies it, because the Python bindings can no longer be installed (#181), so the build produced nothing but time spent. The installer checks for an installable bindings source straight after the clone and refuses before the build, so a tree without one costs a minute rather than an hour. Leave it off unless you are deliberately experimenting with the C++ library.
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
- **SLAM is not part of `full`.** `rtabmap-py` is not on PyPI and upstream no longer ships the Python bindings source, so nothing in this tree can install it: `slam_pi4` ships off and reports itself unavailable. If you want to try the manual build, `scripts/install_rtabmap_pi4.md` has the steps and the known failure; the backend decision is tracked as #181.
- On Raspberry Pi OS Trixie (Python 3.13) the installer refuses to run: this release supports Bookworm only, because that is what the kernel, camera stack and vendor bindings were validated against. Reimage with Bookworm 64-bit rather than fighting the wheels.

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

Two things that install does not give you, both of which the guided installer handles:

- `robot_hat doctor` checks `pyserial` (import name `serial`); without it the vendor's own health
  check reports its library section as broken. `python -m pip install pyserial` fixes that (#255).
- `Pidog.speak()` reads `~/pidog/sounds/`, and the pack lives in the clone's root `sounds/`
  directory rather than inside the installed package, so every bark and growl is silent with only a
  missing-sound warning in the log. Copy it once (#256):

```bash
mkdir -p ~/pidog/sounds && cp -n ./pidog/sounds/* ~/pidog/sounds/
```

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

On a Pi that also reports the camera stack. `picamera2` is the one binding that is **not** a wheel:
it comes from the `python3-picamera2` Debian package, and the venv has to be created with
`--system-site-packages` to see it (the installer does that). If the import fails, leave
`modules.vision_pi4.enabled` at `false` — enabling it only buys a `Picamera2 unavailable` line on
every start (#215).

An IMU that was never calibrated biases every angle derived from it: `|acc|` should read 1.00 g at
rest, and `python -m tools.hardware_checkup --skip-motion` warns when it does not. The vendor's
`examples/imu_calibration.py`, the only path this page used to point at, is not part of the
installed package; `docs/pidog/PIDOG-SENSORS.md` section 4.5 lists the setters that write the same
values, and #259 tracks what replaces the example on the device.

## What ships enabled

The shipped `config/settings.jsonc` starts **18 of the 30 modules**. This is what a fresh install does
before you change anything; `GET /api/v1/modules` is the live answer, and `docs/FEATURES_GUIDE.md`
says how to turn each one off.

| State | Modules |
|---|---|
| **On** | `hal`, `hal_sensors`, `hal_motors`, `motion_gateway`, `api`, `perception`, `scanning`, `navigation`, `orientation`, `mapping`, `behavior`, `attention`, `routine_runner`, `place_navigator`, `event_log`, `decision_log`, `led_manager`, `watchdog` |
| **Off** | `safety`, `health`, `sensor_health`, `balance`, `calibration`, `vision`, `vision_pi4`, `voice`, `face_recognition`, `semantic_labeler`, `slam_pi4`, `energy_emotion` |

Three things worth knowing about that list:

- **The safety stack is off on purpose** in this build - `safety`, `health`, `sensor_health` and
  `balance` are the four that need a soak on a real dog before they are anybody's default, and #26 is
  that soak. `watchdog` is on and holds motion; the *interlock* is always on and is not a module.
- **The voice stack needs three things beyond the Python install**: the vendor
  `sunfounder-voice-assistant` package (the installer installs it), the HAT speaker enabled
  (`setup_robot_hat_audio.sh`, then a reboot) and `espeak-ng` for the local `pyttsx3` fallback. Voice
  ships off in all three of its switches - `modules.voice.enabled`, `voice_assistant.stt.enabled` and
  `voice_assistant.tts.enabled` - and `voice_assistant.tts.backend` picks the engine
  (`FEATURES_GUIDE.md` [§19](FEATURES_GUIDE.md#19-voice-assistant-pi4), #240, #245, #246).
- **`slam_pi4` cannot be enabled usefully yet**: the `rtabmap` backend's bindings are not installable
  and the `stub` backend is dead reckoning, not visual SLAM
  (`FEATURES_GUIDE.md` [§23](FEATURES_GUIDE.md#23-slam-pi4), #181).

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
- `sudo .venv/bin/robot_hat doctor` is the vendor's own health check, and its `Library` section
  should be all ticks now that `pyserial` is installed (#255). If that section is green and the
  speaker is still silent, the finding is #254 - a hardware question, not a code one.

What still has to be judged by a human, because no command here asserts it: obstacle avoidance
selecting sensible turns, stuck recovery completing, the watchdog holding motion on stale sensors
(`state.supervisor`), and the event log rotating at `event_log_max_mb`.

## Troubleshooting & Support Bundles

If you run into install or runtime issues, follow this checklist to gather information and resolve common failures.

- **Missing imports (ModuleNotFoundError like `No module named 'tools'`):**
   - Ensure HoundMind is installed into the same environment where you run tests/commands: `python -m pip install -e .`.
   - When running tests or scripts directly from the repo, set `PYTHONPATH=src` or use the editable install above.

- **Build failures for heavy packages (OpenCV, dlib/face_recognition, vosk):**
   - Use Raspberry Pi OS Bookworm (Python 3.11): it is the only supported release, and the installer refuses others. Bookworm is also where the prebuilt wheels are.
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

### The service: what starts at boot

The installer writes `/etc/systemd/system/houndmind.service` and enables it, and stops there — the
runtime starts when you tell it to:

```bash
sudo systemctl start houndmind      # now, and after every boot from here on
sudo systemctl status houndmind
sudo systemctl stop houndmind       # graceful: SIGTERM, the tick finishes, the HAL closes
sudo systemctl restart houndmind
```

The unit is in the tree at `packaging/systemd/houndmind.service`, with three placeholders
(`@HOUNDMIND_USER@`, `@HOUNDMIND_ROOT@`, `@HOUNDMIND_PYTHON@`) that the installer fills from the
account and checkout it ran with. Passing `--no-service` skips the step.

To install it by hand — the case for a device that was set up before the unit existed — render the
three values from the checkout that is actually there, rather than editing the template:

```bash
cd ~/HoundMind
sed -e "s|@HOUNDMIND_USER@|$(whoami)|g" \
    -e "s|@HOUNDMIND_ROOT@|$(pwd)|g" \
    -e "s|@HOUNDMIND_PYTHON@|$(pwd)/.venv/bin/python|g" \
    packaging/systemd/houndmind.service > /tmp/houndmind.service
sudo install -m 0644 /tmp/houndmind.service /etc/systemd/system/houndmind.service
sudo systemctl daemon-reload
sudo systemctl enable --now houndmind
systemctl is-enabled houndmind      # enabled
```

The installer itself only runs `enable`, so an install never opens the servo bus on its own. The
`--now` above is the operator saying "start it too", which is the deliberate extra step. From then on
`multi-user.target` starts it at every boot.

**The service resumes; a command in flight does not.** A gait cannot survive a restart, because
`motion_command` and the intent board are context-only and every intent expires, and a routine that was
mid-run is lost rather than replayed. What does come back is autonomy: the runtime starts in `mode
idle`, where `behavior` and the navigator may drive, so a dog with those modules enabled can start
moving on its own after a boot — set `mode rest` if it must stay put. The next start says how the
previous one ended — `~/.houndmind/session.json`, #214.

A unit that fails three times in a minute stops instead of looping, so a broken `settings.jsonc`
gives a message rather than a restart storm: `journalctl -u houndmind -n 50`.

Running it in the foreground is still supported, and is the way to watch it:

```bash
cd ~/HoundMind && source .venv/bin/activate
python -m houndmind_ai.main
```

| Task | What to do |
|---|---|
| Stop | `sudo systemctl stop houndmind`, or `Ctrl-C` in a foreground run. Either way the tick finishes and the HAL is closed. |
| Restart | `sudo systemctl restart houndmind`. A routine file added or edited since boot is read at this point (`docs/ROUTINES.md`). |
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

### Why you want TLS on: the installable console and its notifications

A **secure context** (`https://`, or `localhost`) is a browser requirement for three things the console
does when it can, and skips when it cannot (#176, #177):

| Feature | Needs | On plain http |
|---|---|---|
| Installable app (`manifest.webmanifest`, service worker) | secure context | the manifest is ignored, `/sw.js` is never registered, the console works normally |
| App shell cached for a reload while offline | secure context | nothing is cached; a reload needs the device |
| Desktop notifications for safety events | secure context **and** permission | no permission prompt is offered; the event ticker still shows every event |

Nothing turns this on for you, and nothing needs to: `tls_enabled: false` is still the default because
a self-signed certificate has to be trusted by every client before it is useful, and the trust steps
above are the user's. Turning it on is what makes the console installable to a phone's home screen.

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
