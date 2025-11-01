# Face Recognition Setup (Raspberry Pi)

Face recognition in PackMind is powered by the `face_recognition` Python package, which depends on `dlib`.
Compiling `dlib` on older Raspberry Pi models (e.g., Pi 3B) can be very slow and may fail due to limited RAM/CPU.
This guide offers practical paths depending on your device and goals.

## TL;DR
- Pi 3B or lower-power devices: recommended to DISABLE face recognition.
- Pi 4/5 (2GB+ RAM): use prebuilt wheels from piwheels when possible; otherwise prepare to build.
- Everyone: you’ll likely need `cmake` (and build tools) if a wheel isn’t available.

## Option A — Disable the feature (simplest)
Edit `packmind/packmind_config.py`:

```python
class PiDogConfig:
    ENABLE_FACE_RECOGNITION = False
```

This turns off the FaceRecognitionService while keeping the rest of PackMind fully functional.

## Option B — Use prebuilt wheels (preferred)
On Raspberry Pi OS, `pip` typically uses the piwheels.org mirror that provides prebuilt wheels for ARM.
Make sure it’s enabled (it usually is by default on Raspberry Pi OS). Then try:

```bash
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install face-recognition
```

If a compatible wheel exists for your Python version/architecture, this avoids compiling `dlib` locally.

Tips:
- 64-bit Raspberry Pi OS often has better wheel coverage and performance.
- If installation still tries to compile dlib from source, consider upgrading Python or switching to 64-bit OS.

## Option C — Build from source (advanced, slow)
If a wheel isn’t available for your combo (Python/OS/arch), you may need to build `dlib`.
Expect lengthy builds (often hours) on Pi 3B; consider doing this on Pi 4/5 or cross-compiling.

Install prerequisites:

```bash
sudo apt update
sudo apt install -y cmake build-essential python3-dev libopenblas-dev liblapack-dev
```

Then:

```bash
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install dlib==19.24.0
python3 -m pip install face-recognition
```

Notes:
- Increase swap space if you run out of memory (Pi 3B):
  - Edit `/etc/dphys-swapfile` and set `CONF_SWAPSIZE=2048`, then run:
    ```bash
    sudo dphys-swapfile swapoff
    sudo dphys-swapfile setup
    sudo dphys-swapfile swapon
    ```
  - Revert swap size after installation to reduce SD wear.
- Make sure you have enough free disk space.

## Lightweight alternatives
If you only need detection (not identity recognition), consider using OpenCV-based detectors (e.g., Haar or DNN) and skip `face_recognition` entirely. That path is much lighter on older Pi hardware.

At runtime, PackMind will operate normally with `ENABLE_FACE_RECOGNITION = False`.

## Troubleshooting
- “No error after hours” while compiling on Pi 3B: it’s probably swapping/thrashing. Prefer wheel route or disable.
- Verify piwheels is active: on Raspberry Pi OS it should be default; check `/etc/pip.conf` or try `pip debug --verbose`.
- Check Python version compatibility with piwheels for `dlib`.
- Still stuck? Open an issue with your model, OS, Python version, and full install log.
