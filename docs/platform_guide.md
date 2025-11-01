# Platform guide: recommended presets and features

This guide helps you choose the right configuration for your device and avoid heavy dependencies on lower‑power boards.

## Quick picks

- Desktop (no hardware):
  - Preset: simulation via `HOUNDMIND_SIM=1` (any preset works for exploration)
  - Notes: motion is no‑op; sensors are simulated; great for dev and CI.

- Raspberry Pi 3B:
  - Preset: `PACKMIND_CONFIG=pi3` (auto‑selected on ARMv7)
  - Features: SLAM mapping enabled; sensor fusion disabled by default; face recognition and enhanced audio disabled; conservative scan/motion cadence; dynamic balance at lower rate.
  - Install: `pip3 install -r requirements-lite.txt`

- Raspberry Pi 4/5:
  - Preset: `advanced` or `indoor` depending on use
  - Features: Full features typically work; face recognition depends on `dlib` wheels via piwheels.
  - If pip starts compiling `dlib`: see `docs/face_recognition_setup.md`.

## How to select a preset

You can set a preset via environment variable, or rely on auto‑selection:

```bash
# Pick a preset explicitly (Raspberry Pi)
PACKMIND_CONFIG=pi3 python3 packmind/orchestrator.py

# Or use the HoundMind profile alias
HOUNDMIND_PROFILE=pi3 python3 packmind/orchestrator.py

# Desktop simulation
HOUNDMIND_SIM=1 python3 packmind/orchestrator.py
```

On Pi 3B (ARMv7), the orchestrator will auto‑select `pi3` if no preset was provided.

## Feature guidance by platform

- Face recognition (face_recognition/dlib)
  - Pi 3B: disable by default (heavy); use `requirements-lite.txt`.
  - Pi 4/5: usually fine with piwheels; see setup doc.
- Enhanced audio processing (SciPy/FFT heavy)
  - Pi 3B: disabled by default; basic audio/voice still available.
  - Pi 4/5: enable for multi‑source tracking and VAD.
- Sensor fusion localization
  - Pi 3B: disabled by default to save CPU; mapping still works.
  - Pi 4/5: enable for best navigation experience.
- Scanning/movement cadence
  - Pi 3B: fewer samples and smaller sweeps; slightly slower motion for stability.
  - Pi 4/5: higher cadence is fine.

For more details on config flags, see `docs/packmind_config_guide.md`.
