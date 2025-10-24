# Pidog: Advanced Behaviors and AI for SunFounder PiDog 🐶

This repository provides two related but completely independent ways to run your PiDog:

- CanineCore: a modular behavior framework for composing and interactively running behaviors.
- PackMind: a standalone AI with its own orchestrator, services, and optional mapping/navigation stack.

Use either system. They don’t import or depend on each other.

Legacy modules for the old system are stored in Legacy, and the entire project has been forked at https://github.com/DrMikeKW/Pidog-New_Scripts/

## What’s inside

- CanineCore (`canine_core/`): async orchestrator, services (motion, sensors, emotions, voice), and behavior modules.
- PackMind (`packmind/`): AI orchestrator plus subsystems for mapping (SLAM), navigation (A*), localization (sensor fusion), voice, scanning, and obstacle handling.
- Docs (`docs/`): programming guides, API reference, voice setup, and config guides.
- Examples (`examples/`): runnable examples.
- Legacy (`legacy/`): archived test modules and examples (not actively maintained)

## Quick install and run on the Raspberry Pi 🧰

Requirements

- Raspberry Pi with PiDog assembled and powered
- Raspberry Pi OS (Bookworm or compatible), Python 3.9+
- Official `pidog` package (and related hardware libs) installed on the Pi

1) Clone the repo on the Pi

```bash
cd ~
git clone https://github.com/seven-lynx/Pidog.git
cd Pidog
```

2) Install Python dependencies

```bash
pip3 install -r requirements.txt
```

Optional: enable voice features

```bash
sudo apt update && sudo apt install -y portaudio19-dev python3-pyaudio
pip3 install speech_recognition pyaudio
```

3) Run one of the systems

PackMind (standalone AI)

```bash
python3 packmind/orchestrator.py
# or
python3 packmind.py
```

CanineCore (modular behaviors)

```bash
python3 main.py                # Orchestrator default
python3 canine_core/control.py # Interactive behavior menu
```

Tip: On a development PC without hardware, many hardware services fallback to safe no-ops. Camera/audio/servos still require proper setup when you move to the Pi.

## Which should I choose?

- PackMind: batteries‑included AI demo that coordinates sensing, emotions, scanning, and optional mapping/navigation.
- CanineCore: clean, composable framework to mix and match behaviors and services; ideal for building your own modules.

## Features at a glance

- Voice commands with optional wake word (when enabled)
- Intelligent scanning and obstacle avoidance
- Behavior orchestration and state handling
- Emotional LED themes and reactive sounds
- Optional SLAM mapping, A* navigation, and sensor‑fusion localization (PackMind)

## Project layout

```
Pidog/
├─ main.py                    # CanineCore entry point
├─ canine_core/
│  ├─ behaviors/
│  ├─ core/                   # orchestrator, interfaces, services, state
│  └─ config/
├─ packmind/
│  ├─ orchestrator.py         # PackMind entry point
│  ├─ behaviors/ core/ services/
│  ├─ mapping/ nav/ localization/ visualization/
│  └─ packmind_config.py
├─ docs/
├─ examples/
├─ scripts/
└─ legacy/
```

## Developer quick start (desktop) 💻

On Windows (PowerShell) or macOS/Linux, you can explore without hardware:

```powershell
pip install -r requirements.txt
python main.py                  # CanineCore
python packmind/orchestrator.py # PackMind
```

Note: Hardware‑dependent features won’t function fully without PiDog.

## Documentation

- Programming Guide: `docs/PIDOG_PROGRAMMING_GUIDE.md`
- Quick Start Programming: `docs/QUICK_START_PROGRAMMING.md`
- API Reference: `docs/api_reference.md`
- Voice Setup: `docs/voice_setup_instructions.md`
- CanineCore configuration: `docs/canine_core_config_guide.md`
- PackMind architecture: `packmind/ARCHITECTURE.md`

## Troubleshooting

- If `pidog` imports fail on the Pi, install the official SunFounder libraries and verify servo calibration.
- For voice issues, confirm `portaudio19-dev` and `pyaudio` are installed and a default input device is set.
- On desktops without hardware, expect safe no‑ops for hardware calls.

## License

See `LICENSE` for details.

-

Built to help you teach, learn, and explore with PiDog.