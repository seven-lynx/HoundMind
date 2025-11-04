# HoundMind Installation Guide

This guide walks you through installing and running HoundMind on two setups:
- Raspberry Pi (on the robot)
- Desktop PC (Windows/macOS/Linux) in simulation mode

Pick your path below and follow each step in order.

---

## Guided installer quick start (Raspberry Pi)

If you already imaged Raspberry Pi OS (see A0) and cloned this repo on the Pi, you can do almost everything from one menu: install vendor modules, set up audio, verify hardware, install HoundMind deps (Pi 4/5 or Pi 3B), and launch either system.

Run on the Pi (SSH or local terminal) from the repo root:

```bash
cd ~/HoundMind
python3 scripts/pidog_install.py
```

Recommended flow inside the menu:
- 1) Install vendor modules (Robot HAT 2.5.x, Vilib, PiDog)
- 2) I2S audio setup (reboot when prompted)
- 3) Run vendor wake‑up demo (checks servos and sound)
- 5) Verify imports and I2C devices
- 6) Install HoundMind deps: Pi 4/5 (full)   |   7) Pi 3B (lite)
- 8) Launch CanineCore (main)   |   9) CanineCore control   |   10) PackMind (with optional preset)

Notes and tips:
- Safe to run multiple times; it skips work when possible and will use sudo when needed.
- For PiDog Standard, use servo zeroing in the vendor examples; for PiDog V2, use the zeroing button on the HAT.
- Make sure I2C is enabled (A0) and set your Wi‑Fi country in raspi‑config.
- The installer covers A1 → A4 below. Do A0 (OS imaging) first.

## 0) Prerequisites

- Python 3.9+ (3.10–3.12 recommended)
- Git
- 2–4 GB free disk space (more if you install optional heavy packages)

Optional (but recommended): a Python virtual environment.

- Windows (PowerShell):
  ```powershell
  py -3 -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
- macOS/Linux:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

Clone the repository:
```bash
git clone https://github.com/seven-lynx/HoundMind.git
cd HoundMind
```

---

## A) Raspberry Pi (on the robot)

If you’re using actual PiDog hardware, install SunFounder’s vendor modules right after OS imaging and basic config, before installing HoundMind dependencies. After A0, go to A1 (vendor modules), then A2 (checks/calibration), then A3 (HoundMind per model).

Raspberry Pi quick index:
- [A0 — Install Raspberry Pi OS](#a0)
- [A1 — Install vendor modules (Robot HAT, Vilib, PiDog)](#a1)
- [A2 — Vendor checks and calibration](#a2)
- [A3 — Install HoundMind dependencies (per Pi model)](#a3)
  - [A3.1 — Pi 4/5 (full features)](#a3-1)
  - [A3.2 — Pi 3B (lite features)](#a3-2)
- [A4 — Run HoundMind (choose system)](#a4)

<a id="a0"></a>
### A0) Install Raspberry Pi OS (one-time on the microSD)

1. Prepare the microSD
  - Use a quality microSD card (16–32 GB, Class 10/U3 recommended).
  - Have a USB card reader ready on your PC.

2. Download and launch Raspberry Pi Imager
  - https://www.raspberrypi.com/software/
  - Works on Windows/macOS/Linux.

3. Choose OS and device
   - Device: your Pi model (Pi 3B, 4, or 5).
   - Note: PiDog versions
     - Standard: supports Raspberry Pi 3B+/4B/Zero 2W; does not support Raspberry Pi 5.
     - V2: supports Raspberry Pi 3/4/5 and Zero 2W; improved power and a hardware servo zeroing button. If you’re on a Pi 5, you need PiDog V2.
     - Details: https://docs.sunfounder.com/projects/pidog/en/latest/faq.html#q1-what-versions-of-pidog-are-available
   - OS:
     - Pi 4/5: Raspberry Pi OS (64-bit) Bookworm recommended.
     - Pi 3B: Raspberry Pi OS (32-bit) Bookworm recommended for best compatibility and lower memory overhead.
       - 64-bit also works on Pi 3B, but expect more source builds for some Python packages and slightly higher RAM usage. If you pick 64-bit on Pi 3B, prefer our lite path (no dlib/TensorFlow) and set `FACE_BACKEND = "lite"`.

4. Configure (Advanced options in Imager)
  - Set hostname (e.g., `pidog`)
  - Enable SSH and set username/password
  - Configure Wi‑Fi (SSID, password, country) if using wireless
  - Set locale, timezone, and keyboard

5. Write the image
  - Select your microSD card and click Write.
  - Eject the card when complete.

6. First boot and initial updates (on the Pi)
  - Insert the card, power on the PiDog, and connect over SSH:
    ```bash
    ssh pi@pidog.local   # or use the Pi's IP address
    ```
  - Update packages and firmware:
    ```bash
    sudo apt update && sudo apt upgrade -y
    sudo reboot
    ```

7. Enable required interfaces for PiDog
  - Open raspi-config:
    ```bash
    sudo raspi-config
    ```
  - Interface Options → I2C → Enable (required for the servo driver/hat)
  - (Optional) Interface Options → SPI → Enable (needed for the sound direction sensor on some kits)
  - (Optional) Interface Options → Camera → Enable (if using CSI camera; USB webcams typically just work)
  - Finish and reboot.

8. Verify I2C and camera (optional but useful)
  - I2C device node exists:
    ```bash
    ls -l /dev/i2c-1
    ```
  - Install i2c-tools (optional) and probe the bus (you may see 0x40 for PCA9685):
    ```bash
    sudo apt install -y i2c-tools
    i2cdetect -y 1
    ```
  - Camera quick check (USB): see section A1/A2 camera tools; for CSI cameras on Bookworm, libcamera apps can verify hardware.

Next steps on a real PiDog:
- A1: Install the official PiDog modules (Robot HAT, Vilib, PiDog)
- A2: Perform vendor checks and servo calibration
- A3: Install PackMind dependencies for your Pi model

<a id="a1"></a>
### A1) Install and verify the official PiDog modules (Robot HAT, Vilib, PiDog)

On a real PiDog, use SunFounder’s official install method so the Robot HAT, Vilib, and PiDog versions match. These commands come from SunFounder’s docs and FAQ.

Important: If you previously installed `pidog`, `robot-hat`, or `vilib` via pip, the steps below will replace them with the vendor-supported versions.

Source of truth (SunFounder):
- Install all modules (Important): https://docs.sunfounder.com/projects/pidog/en/latest/python/python_start/install_all_modules.html
- FAQ Q2 (install commands): https://docs.sunfounder.com/projects/pidog/en/latest/faq.html#q2-how-do-i-install-the-required-modules

Guided installer (recommended):
```bash
python3 scripts/pidog_install.py
```
This menu-driven helper can install Robot HAT/Vilib/PiDog, run I2S setup, demo, and install HoundMind dependencies for Pi 4/5 or Pi 3B.

0) Prerequisites (Lite OS only)

If you installed the Lite edition of Raspberry Pi OS, make sure Python 3 tools and smbus are present:

```bash
sudo apt install -y git python3-pip python3-setuptools python3-smbus
```

1) Install Robot HAT (branch 2.5.x)

```bash
git clone -b 2.5.x https://github.com/sunfounder/robot-hat.git --depth 1
cd robot-hat && sudo python3 install.py
```

2) Install Vilib

```bash
git clone https://github.com/sunfounder/vilib.git
cd vilib && sudo python3 install.py
```

3) Install PiDog

```bash
git clone https://github.com/sunfounder/pidog.git --depth 1
cd pidog && sudo python3 setup.py install
```

If there’s no sound (I2S speaker):

```bash
cd ~/robot-hat
sudo bash i2samp.sh
```

When prompted, type `y` to continue and allow `/dev/zero` to run in the background. Reboot when the script finishes. If there’s still no sound after reboot, you may need to run `i2samp.sh` multiple times.

Quick vendor demo (verifies servos and sounds):

```bash
cd ~/pidog/examples
sudo python3 1_wake_up.py
```

Then verify within HoundMind:

- Import check (non-root is fine):
  ```bash
  python3 - << 'PY'
  try:
    from pidog import Pidog
    print("OK: pidog import works")
  except Exception as e:
    print("FAIL:", e)
  PY
  ```
- Safe hardware check (no motion by default):
  ```bash
  python3 tools/pidog_hardware_check.py
  ```
- Include limited motion/head sweep when you have clear space:
  ```bash
  python3 tools/pidog_hardware_check.py --move
  ```
- Optional setup assistant (verifies config and deps):
  ```bash
  python3 tools/setup_pidog.py
  ```

Notes:
- Ensure I2C is enabled (see A0). You should see `/dev/i2c-1` and optionally `0x40` on `i2cdetect -y 1`.
- On some examples and hardware tests, `sudo` is required to access devices.
- For audio tests, plug in your speaker/amp and set a reasonable volume (e.g., `--volume 60`).
- On Pi 3B (32‑bit) or Python 3.13, vendor installers may print messages like “mediapipe is only supported on 64‑bit” or “tflite‑runtime only supported on Python ≤3.12”. These components are optional for HoundMind and safe to ignore; use the Pi 3B lite path below (A3.2).

<a id="a2"></a>
### A2) Vendor checks and calibration (recommended)

Before running PackMind, complete these vendor checks:
- Check I2C and SPI interfaces (per SunFounder docs):
  https://docs.sunfounder.com/projects/pidog/en/latest/python/python_start/enable_i2c_spi.html
- Servo adjust/zeroing (Important), especially for the Standard version:
  https://docs.sunfounder.com/projects/pidog/en/latest/python/python_start/py_servo_adjust.html

Tips by version:
- PiDog V2: Use the zeroing button on the Robot HAT to set all servos to 0° before mechanical alignment.
- PiDog Standard: Run the zeroing script, then align per the calibration ruler:
  ```bash
  cd ~/pidog/examples
  sudo python3 servo_zeroing.py
  ```

Once checks and calibration are complete, proceed to A3 based on your Pi model.

<a id="a3"></a>
### A3) Install HoundMind dependencies on Raspberry Pi (choose your model)

Pick the subsection that matches your device.

<a id="a3-1"></a>
#### A3.1) Pi 4/5 (full features)

1. Update system packages
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
2. Install system headers for audio (voice features)
   ```bash
   sudo apt install -y portaudio19-dev python3-dev
   ```
3. (Optional) If you plan to use dlib/face_recognition on Pi 4/5, install build tools:
   ```bash
   sudo apt install -y cmake build-essential libopenblas-dev liblapack-dev
   ```
4. Install Python dependencies (full)
   ```bash
   python3 -m pip install --upgrade pip
   pip3 install -r requirements.txt
   ```
   - If PyAudio build fails on your Pi OS, you can use the apt package:
     ```bash
     sudo apt install -y python3-pyaudio
     pip3 install SpeechRecognition
     ```
5. Verify camera and audio
   - List microphones and indexes:
     ```bash
     python3 tools/list_audio_devices.py
     ```
   - Probe the camera and save a test frame:
     ```bash
     python3 tools/camera_check.py --list-devices --max-index 5 --save frame.jpg
     ```
6. Run HoundMind (see A4 for system choices)
  - Example (PackMind with a preset):
    ```bash
    PACKMIND_CONFIG=advanced python3 packmind/orchestrator.py
    ```

<a id="a3-2"></a>
#### A3.2) Pi 3B (lite features, faster install)

Pi 3B is resource constrained; prefer the lightweight path.

Note on OS choice:
- 32-bit Raspberry Pi OS (Bookworm) is recommended for the Pi 3B due to broader prebuilt wheels (piwheels) and lower memory overhead.
- 64-bit Raspberry Pi OS is supported, but you may encounter more source builds and need additional system headers. If using 64-bit, stick to `requirements-lite.txt` and the lite face backend.

1. Update system packages and audio headers
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y portaudio19-dev python3-dev
   ```
2. Install lightweight Python dependencies
   ```bash
   python3 -m pip install --upgrade pip
   pip3 install -r requirements-lite.txt
   ```
3. Enable the lite face backend (optional detection only)
   - In `packmind/packmind_config.py`:
     ```python
     ENABLE_FACE_RECOGNITION = True
     FACE_BACKEND = "lite"
     ```
   - Detection-only works with `opencv-python`. For identity (LBPH), install:
     ```bash
     pip3 install opencv-contrib-python
     ```
4. Verify camera and audio (same as Pi 4/5)
   ```bash
   python3 tools/list_audio_devices.py
   python3 tools/camera_check.py --index 0 --save frame.jpg
   ```
5. Run HoundMind (see A4 for system choices)
  - Example (PackMind with Pi3 preset):
    ```bash
    PACKMIND_CONFIG=pi3 python3 packmind/orchestrator.py
    ```

Tips:
- If camera access fails on Bookworm with libcamera-only modules, try a USB webcam or ensure V4L2 compatibility.
- If voice capture is silent, pick the right `VOICE_MIC_INDEX` in `packmind/packmind_config.py` using the audio lister.

 

 

---

<a id="a4"></a>
### A4) Run HoundMind (choose your system)

HoundMind includes two systems. Pick the one you want to run:

Tip: You can also launch either system from the guided installer (see A1):
```bash
python3 scripts/pidog_install.py
```

- CanineCore (modular behaviors):
  ```bash
  python3 main.py                # Default orchestrator
  # Or interactive behavior menu
  python3 canine_core/control.py
  ```

- PackMind (AI orchestrator with mapping/navigation and advanced services):
  ```bash
  python3 packmind/orchestrator.py
  # or
  python3 packmind.py
  # or
  python -m packmind
  ```

Tip: Both systems share the same vendor modules (Robot HAT, Vilib, PiDog). The dependency sets above (A3.1/A3.2) prepare a suitable Python environment for either system.

## B) Desktop (Windows/macOS/Linux) — Simulation Mode

Run HoundMind without hardware using the built-in simulator.

1. Create and activate a virtual environment (recommended)
   - Windows (PowerShell):
     ```powershell
     py -3 -m venv .venv
     .venv\Scripts\Activate.ps1
     ```
   - macOS/Linux:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
2. Install minimal desktop requirements
   ```powershell
   pip install -r requirements-desktop.txt
   ```
   Notes:
   - On Windows, if PyAudio fails to install:
     ```powershell
     pip install pipwin
     pipwin install pyaudio
     ```
   - Voice is optional; you can skip PyAudio and SpeechRecognition entirely if you won’t use voice.
3. (Optional) Telemetry dashboard
   ```powershell
   pip install fastapi uvicorn
   python tools/run_telemetry.py --host 127.0.0.1 --port 8765 --force
   # Visit http://127.0.0.1:8765
   ```
4. Run in simulation (choose your system)
   - CanineCore:
     ```powershell
     $env:HOUNDMIND_SIM = "1"
     python main.py
     ```
   - PackMind:
     ```powershell
     $env:HOUNDMIND_SIM = "1"
     python packmind/orchestrator.py
     # or
     $env:HOUNDMIND_SIM = "1"
     python -m packmind
     ```

Troubleshooting on desktop:
- If OpenCV can’t open your camera, use the camera tool:
  ```powershell
  python tools/camera_check.py --list-devices --max-index 10
  ```
- To run without any camera/audio dependencies, you can comment out voice/camera features in `packmind/packmind_config.py` and just simulate behaviors.

---

## Optional: Telemetry (server + client)

- Enable in `packmind/packmind_config.py`:
  ```python
  TELEMETRY_ENABLED = True
  TELEMETRY_HOST = "0.0.0.0"
  TELEMETRY_PORT = 8765
  # TELEMETRY_BASIC_AUTH = ("user","pass")  # optional
  ```
- Start the telemetry server (if not already running):
  ```bash
  python tools/run_telemetry.py --force
  ```
- Open http://<host>:8765 and watch events stream (scan, health, behavior, emotion).

---

## Verification checklist

- Audio devices list shows your mic and index: `tools/list_audio_devices.py`
- Camera probe saves a frame: `tools/camera_check.py --save frame.jpg`
- PackMind starts and logs activity; in simulation, motions are safe no-ops.
- Telemetry page shows live events when enabled.

---

## Common issues & fixes

- PyAudio won’t install on Windows: use `pipwin install pyaudio`.
- dlib/face_recognition slow or fails to build on Pi 3B: use the lite backend.
- OpenCV camera fails on Windows: try `--backend dshow` in `camera_check.py`.
- Address in use for telemetry: change port with `--port` or stop other servers.

For more, see README “Troubleshooting”.
