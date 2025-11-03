# HoundMind Release QA Checklist

Date: 2025-11-03
Release: v2025.11.03

Use this checklist before and after cutting a new CalVer tag. Keep it pragmatic and fast—smoke the critical paths on Desktop and the Pi.

## 1) Version and Tag
- [ ] `packmind/__init__.py` __version__ matches tag (e.g., 2025.11.03)
- [ ] Telemetry server root page shows the same version (reads packmind.__version__)
- [ ] Tag pushed: `git tag -l v2025.11.03` shows locally; GitHub displays the tag
- [ ] Release notes file exists: `docs/releases/v2025.11.03.md`

## 2) Desktop (Windows, Simulation)
- [ ] Create/activate venv
- [ ] Install minimal deps
  ```powershell
  pip install -r requirements-desktop.txt
  ```
- [ ] CanineCore (sim)
  ```powershell
  $env:HOUNDMIND_SIM = "1"
  python main.py
  ```
  Expect: clean startup, log messages; no hardware exceptions.
- [ ] PackMind (sim)
  ```powershell
  $env:HOUNDMIND_SIM = "1"
  python packmind/orchestrator.py
  ```
  Expect: clean startup, optional mapping/nav logs; no cv2/dlib import errors (desktop reqs omit heavy deps).

## 3) Raspberry Pi 3B (Lite path)
- [ ] OS: Raspberry Pi OS 32-bit (Bookworm) recommended
- [ ] Run guided installer menu
  ```bash
  python3 scripts/pidog_install.py
  ```
- [ ] Option 1: Install vendor modules (Robot HAT 2.5.x, Vilib, PiDog)
- [ ] Option 2: I2S audio setup (reboot after)
- [ ] Option 3: Vendor "wake up" demo
- [ ] Option 5: Verify imports + I2C (`/dev/i2c-1`, `i2cdetect -y 1`)
- [ ] Option 7: Install HoundMind deps (Pi 3B lite)
- [ ] Option 8/9: Launch CanineCore (main/control)
- [ ] Option 10: Launch PackMind (try without and with `PACKMIND_CONFIG=pi3`)
  Expect: services start; no heavy deps required; voice optional.

## 4) Raspberry Pi 4/5 (Full path)
- [ ] OS: Raspberry Pi OS 64-bit (Bookworm)
- [ ] Run guided installer
  ```bash
  python3 scripts/pidog_install.py
  ```
- [ ] Option 1 → 2 → 3 → 5: vendor install, I2S, demo, verify
- [ ] Option 6: Install HoundMind deps (Pi 4/5 full)
- [ ] Option 8/9: CanineCore runs
- [ ] Option 10: PackMind runs with preset (e.g., `advanced`)
  Expect: camera/audio ok; optional face recognition if installed.

## 5) Tools sanity
- [ ] Audio devices listing
  ```bash
  python3 tools/list_audio_devices.py
  ```
- [ ] Camera probe (save frame)
  ```bash
  python3 tools/camera_check.py --list-devices --max-index 5 --save frame.jpg
  ```
  Expect: device list prints; frame.jpg created when a camera is present.

## 6) Telemetry (optional)
- [ ] Install optional deps (where tested)
  ```bash
  pip install fastapi uvicorn
  ```
- [ ] Start server and open dashboard
  ```bash
  python tools/run_telemetry.py --host 127.0.0.1 --port 8765 --force
  # Visit http://127.0.0.1:8765 and verify version/status/events
  ```

## 7) Documentation
- [ ] `docs/INSTALL.md` A0–A4 flow aligns with SunFounder docs
- [ ] A4 mentions guided installer can launch either system
- [ ] README Doc Version is current and shows installer command

## 8) Post-release
- [ ] Create GitHub Release for `v2025.11.03` using `docs/releases/v2025.11.03.md`
- [ ] Verify tag and release visible; changelog reflects the release
- [ ] Announce/update any external references if applicable

Notes:
- Pi 3B: 32-bit OS recommended; 64-bit supported with `requirements-lite.txt`.
- Heavy features (face_recognition/dlib) are optional; lite backend available.
