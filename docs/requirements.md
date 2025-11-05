# Requirements and Dependency Notes

This document summarizes how dependencies are handled across platforms and models, and explains a few Pi-specific choices.

## Python versions

- Recommended: 3.10–3.12
- Supported: 3.9+ (desktop), 3.10+ (Pi)
- Python 3.13 on Raspberry Pi (ARMv7l, Pi 3B): some third-party wheels are not yet available. Use the Pi 3B lite path and install heavy packages from apt.

## Raspberry Pi 4/5 (full)

- Install system headers for audio and optional build tools:
  ```bash
  sudo apt install -y portaudio19-dev python3-dev cmake build-essential libopenblas-dev liblapack-dev python3-venv
  ```
- Install Python deps (pip):
  ```bash
  python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  ```
- Face recognition (optional):
  ```bash
  pip install face_recognition
  # If dlib builds from source, ensure build tools above are installed.
  ```

## Raspberry Pi 3B (lite)

To avoid source builds on py3.13/ARMv7, install heavy packages from apt and use a venv that can see system packages:

```bash
sudo apt install -y \
  portaudio19-dev python3-dev python3-venv \
  python3-numpy python3-scipy python3-matplotlib python3-opencv python3-pil \
  libopenblas-dev liblapack-dev
python3 -m venv .venv --system-site-packages
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-lite.txt
```

Notes:
- The lite requirements omit numpy/scipy/matplotlib/opencv/pillow to prevent pip compiling them.
- The venv is created with `--system-site-packages` so the apt packages are visible to Python inside the venv.
- If you prefer system Python over a venv, add `--break-system-packages` to pip (not recommended).

## Desktop (Windows/macOS/Linux)

- Create a venv and install minimal desktop requirements:
  ```bash
  python -m venv .venv
  # PowerShell: .venv\Scripts\Activate.ps1
  # Bash: source .venv/bin/activate
  pip install -r requirements-desktop.txt
  ```
- PyAudio on Windows:
  ```powershell
  pip install pipwin
  pipwin install pyaudio
  ```

## Known-heavy or optional packages

- face_recognition/dlib: Heavy; avoid on Pi 3B. On Pi 4/5, install build tools before pip.
- mediapipe, tflite-runtime: Often unavailable on 32-bit or Python 3.13. They are optional for HoundMind.

## Troubleshooting

- PEP 668 (externally-managed-environment): use a venv; on the Pi 3B path, prefer `--system-site-packages` to see apt packages.
- OpenCV build from source: use `python3-opencv` from apt on Pi 3B.
- NumPy/SciPy wheels missing on py3.13 ARMv7: install from apt as above.
