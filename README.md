# HoundMind — Advanced Behaviors and AI for SunFounder PiDog

HoundMind is the umbrella project that provides two related but completely independent ways to run your PiDog:

- CanineCore: a modular behavior framework for composing and interactively running behaviors.
- PackMind: a standalone AI with its own orchestrator, services, and optional mapping/navigation stack.

Use either system. They don’t import or depend on each other.

Legacy modules for the old system are stored in Legacy, and the entire project has been forked at https://github.com/DrMikeKW/Pidog-New_Scripts/

## What's inside

- **CanineCore** (`canine_core/`): async orchestrator, services (motion, sensors, emotions, voice), and behavior modules.
- **PackMind** (`packmind/`): AI orchestrator plus subsystems for mapping (SLAM), navigation (A*), localization (sensor fusion), voice, scanning, obstacle handling, and **new AI services** (face recognition, dynamic balance, enhanced audio).
- **Docs** (`docs/`): programming guides, API reference, voice setup, and config guides.
- **Tools** (`tools/`): setup utilities and integration tests (formerly `scripts/`).
- **Examples** (`examples/`): runnable examples.
- **Legacy** (`legacy/`): archived test modules and examples (not actively maintained)

## Quick install and run on the Raspberry Pi 🧰

Requirements

- Raspberry Pi with PiDog assembled and powered
- Raspberry Pi OS (Bookworm or compatible), Python 3.9+
- Official `pidog` package (and related hardware libs) installed on the Pi

1) Clone the repo on the Pi

```bash
cd ~
git clone https://github.com/seven-lynx/HoundMind.git
cd HoundMind
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

### Core Features
- Voice commands with optional wake word (when enabled)
- Intelligent scanning and obstacle avoidance
- Behavior orchestration and state handling
- Emotional LED themes and reactive sounds
- Optional SLAM mapping, A* navigation, and sensor‑fusion localization (PackMind)

### 🆕 Advanced AI Services (PackMind)
- **Face Recognition**: Real-time facial detection with personality adaptation and relationship building
- **Dynamic Balance**: IMU-based balance monitoring with automatic tilt correction and fall prevention
- **Enhanced Audio Processing**: Multi-source sound tracking, voice activity detection, and intelligent noise filtering

## Project layout

```
HoundMind/
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
├─ tools/
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
- PackMind configuration: `packmind/packmind_docs/PackMind_Configuration_Guide.txt`
- Integration completion: `INTEGRATION_COMPLETE.md`

## Testing & Tools

- **Setup Tool**: `tools/setup_pidog.py` - Initial PiDog setup and calibration
- **PackMind Checkup (Pi)**: `tools/packmind_checkup.py` - Import + service smoke tests on the PiDog (no movement)
	- Use `--move` to include a small ScanningService head sweep (limited motion)
- **CanineCore Checkup (Pi)**: `tools/caninecore_checkup.py` - Import all CanineCore modules; optional minimal head sweep with `--move`
- **PiDog Hardware Check (Pi)**: `tools/pidog_hardware_check.py` - Direct hardware check (distance, IMU, ears, touch, audio, LED); add `--move` for motion/head sweep
- **Integration Test**: `tools/test_service_integration.py` - Validate AI services integration
- **Legacy Tools**: `legacy/ubuntu_install.py` - Ubuntu system setup utilities

Run PackMind checkup on the Pi:
```bash
python3 tools/packmind_checkup.py --scope import     # Import all PackMind modules
python3 tools/packmind_checkup.py --scope services   # Safe service init (no movement)
python3 tools/packmind_checkup.py --scope services --move  # Include ScanningService head sweep
```

Run CanineCore checkup on the Pi:
```bash
python3 tools/caninecore_checkup.py --scope import   # Import all CanineCore modules
python3 tools/caninecore_checkup.py --move           # Optional minimal head sweep
```

Run PiDog hardware check on the Pi:
```bash
python3 tools/pidog_hardware_check.py                # Sensors only (no movement)
python3 tools/pidog_hardware_check.py --move         # Include motion/head sweep
python3 tools/pidog_hardware_check.py --scope audio  # Only test audio
``` 

Run integration tests:
```bash
python tools/test_service_integration.py
```

## Troubleshooting

- If `pidog` imports fail on the Pi, install the official SunFounder libraries and verify servo calibration.
- For voice issues, confirm `portaudio19-dev` and `pyaudio` are installed and a default input device is set.
- On desktops without hardware, expect safe no‑ops for hardware calls.

## License

See `LICENSE` for details.

-

Built to help you teach, learn, and explore with PiDog.