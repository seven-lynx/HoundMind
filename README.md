# HoundMind — Advanced Behaviors and AI for SunFounder PiDog
> Author: 7Lynx · Doc Version: 2025.10.24

HoundMind is the umbrella project that provides two related but completely independent ways to run your PiDog:

- CanineCore: a modular behavior framework for composing and interactively running behaviors.
- PackMind: a standalone AI with its own orchestrator, services, and optional mapping/navigation stack.

Use either system. They don’t import or depend on each other.

Legacy modules for the old system are stored in the legacy folder, and the entire project has been forked at https://github.com/DrMikeKW/Pidog-New_Scripts/

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
├─ packmind.py                # PackMind launcher
├─ canine_core.py             # Alt CanineCore launcher
├─ canine_core/
│  ├─ core/                   # orchestrator, interfaces, services, state
│  ├─ behaviors/
│  ├─ config/
│  ├─ utils/
│  └─ control.py
├─ packmind/
│  ├─ orchestrator.py         # PackMind entry point
│  ├─ core/ behaviors/ services/
│  ├─ mapping/ nav/ localization/ runtime/ visualization/
│  ├─ packmind_config.py
│  └─ packmind_docs/
├─ docs/
├─ examples/
├─ tools/
├─ data/
├─ logs/
├─ legacy/
├─ CHANGELOG.md
├─ requirements.txt
├─ pyrightconfig.json
├─ LICENSE
└─ README.md

## Modules overview

This is a quick map of the major modules and what they do. Use it to jump into the parts you care about.

- Top-level launchers
	- `main.py`: Starts CanineCore’s orchestrator with your chosen config/preset.
	- `packmind.py`: Convenience wrapper to start PackMind’s AI orchestrator.
	- `canine_core.py`: Thin helper for launching CanineCore on some setups.

- CanineCore (`canine_core/`)
	- `core/orchestrator.py`: Async behavior loop, service lifecycle, watchdog, event bus.
	- `core/interfaces.py`: Shared data structures/types for behaviors and services.
	- `core/state.py`, `core/memory.py`, `core/emotions.py`: State model, short-term memory, emotion helpers.
	- `core/bus.py`: Lightweight pub/sub for internal events.
	- `core/watchdog.py`: Behavior watchdog (dwell cap and error thresholds).
	- `core/services/`: Modular service layer
		- `motion.py`: Walking/turning/head control abstractions
		- `sensors.py`, `sensors_facade.py`: Distance, ears, touch and safe facades
		- `scanning.py`, `scanning_coordinator.py`: Head sweep and scan coordination
		- `energy.py`, `emotions.py`: Energy accounting and emotion state
		- `imu.py`, `balance.py`: IMU readings and balance monitoring
		- `safety.py`: Safety supervisor and actions
		- `voice.py`, `audio_processing.py`: Speech playback/recognition hooks
		- `logging.py`, `telemetry.py`, `learning.py`, `hardware.py`, `battery.py`
	- `behaviors/`: Behavior modules (patrol, guard, play, rest, etc.)
	- `config/`: Python-based config and presets (Simple, Patrol, Interactive, Safety-first)
	- `control.py`: Interactive behavior menu/runner
	- `utils/`: Logging setup and misc helpers

- PackMind (`packmind/`)
	- `orchestrator.py`: Standalone AI orchestrator: behaviors, scanning, emotions, optional mapping/nav
	- `core/`: Dependency injection and runtime context
		- `container.py`: Service wiring from config
		- `context.py`, `types.py`, `registry.py`: AI context, shared types, service registry
	- `services/`: AI services
		- `energy_service.py`, `emotion_service.py`: Energy and emotions
		- `scanning_service.py`, `obstacle_service.py`: Head sweeps, obstacle analysis and avoidance
		- `safety_watchdog.py`, `health_monitor.py`: Liveness and health sampling
		- `face_recognition_service.py`: Face detection/recognition and person memory
		- `dynamic_balance_service.py`: IMU-driven balance analysis and correction triggers
		- `enhanced_audio_processing_service.py`: Sound source tracking and VAD
		- `sensor_service.py`, `calibration_service.py`, `voice_service.py`, `log_service.py`
	- `runtime/`:
		- `sensor_monitor.py`: Periodic sensor polling with error backoff
		- `scanning_coordinator.py`: Intelligent obstacle scanning loop
		- `voice_runtime.py`: Wake-word + command capture loop (configurable mic/timeouts/VAD)
	- `mapping/`, `nav/`, `localization/`, `visualization/`: House map, pathfinding (A*), sensor fusion, plotting
	- `behaviors/`: High-level PackMind behaviors (exploring, patrolling, interacting, etc.)
	- `packmind_config.py`: Tunable settings (SOUND_*, VOICE_*, SCAN_*, ENERGY_*, NAV_*, WATCHDOG_*, etc.)
	- `packmind_docs/`: Architecture and configuration guides
```

## How modules interact (at a glance)

High-level dataflow and control paths for each system.

### CanineCore interactions

```
main.py / canine_core/control.py
	→ core/orchestrator.py
			↔ behaviors/* (execute(context))
			↔ core/services/*
					- sensors.py → periodic reads (distance/ears/touch)
					- scanning_coordinator.py + scanning.py → head sweeps → distances
					- energy.py/emotions.py → update state from activity/sensors
					- motion.py → do_action/forward/turn/head_move
					- voice.py/audio_processing.py → speak / (optional ASR)
					- imu.py/balance.py → tilt/fall detection
					- safety.py → stop/crouch on faults; watchdog limits
					- logging.py/telemetry.py → logs/HUD updates
			↔ core/bus.py (internal events)
			↔ core/watchdog.py (dwell/error caps)
			← config/* presets (runtime toggles and thresholds)
Hardware
	←→ pidog (servos, sensors, LEDs, audio)
```

Key loop:
- Sensors → Orchestrator → Behavior decision → Motion/Head → Scanning as needed
- Energy/Emotions influence speeds/voices; Safety/Watchdog can interrupt

### PackMind interactions

```
packmind.py / packmind/orchestrator.py
	→ core/container.py wires services using packmind_config.py
	→ runtime/sensor_monitor.py → on_reading() → orchestrator
	→ runtime/scanning_coordinator.py → scanning_service.scan_three_way()
	→ runtime/voice_runtime.py → _process_voice_command() via voice_service
	↔ services/*
			- sensor_service.py → aggregates raw readings
			- energy_service.py → update energy; provides speed hints
			- emotion_service.py → compute emotional state
			- scanning_service.py → head sweeps; returns left/forward/right cm
			- obstacle_service.py → analyze scans; avoidance strategies
			- safety_watchdog.py → heartbeat + emergency stop/power_down
			- health_monitor.py → periodic health samples
			- face_recognition_service.py → detections → events/emotions
			- dynamic_balance_service.py → tilt/fall events → safety/emotions
			- enhanced_audio_processing_service.py → VAD/sound → attention
			- voice_service.py → speech playback/utilities
	↔ mapping/ (house_mapping), nav/ (PiDogPathfinder, NavigationController), localization/
			- SLAM/position feed → nav path/waypoints → orchestrator → motion
	↔ services/log_service.py and README logging hooks (patrol events)
	← packmind_config.py (SOUND_*, VOICE_*, SCAN_*, ENERGY_*, NAV_*, WATCHDOG_*, etc.)
Hardware
	←→ pidog (sensors/servos/camera/audio)
```

Key loop:
- SensorMonitor → Orchestrator: update Energy/Emotions; maybe trigger scans
- ScanningCoordinator → ScanningService → ObstacleService → avoidance/motion
- Optional: SLAM/Pathfinding → NavigationController → movement commands
- VoiceRuntime → VoiceService → Orchestrator command handling
- Watchdog/Health can interrupt to ensure safety

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
- PackMind architecture: `packmind/packmind_docs/ARCHITECTURE.md`
 - PackMind configuration: `docs/packmind_config_guide.md`
  

## Testing & Tools

- **Setup Tool**: `tools/setup_pidog.py` - Initial PiDog setup and calibration
- **PackMind Checkup (Pi)**: `tools/packmind_checkup.py` - Import + service smoke tests on the PiDog (no movement)
	- Use `--move` to include a small ScanningService head sweep (limited motion)
- **CanineCore Checkup (Pi)**: `tools/caninecore_checkup.py` - Import all CanineCore modules; optional minimal head sweep with `--move`
- **PiDog Hardware Check (Pi)**: `tools/pidog_hardware_check.py` - Direct hardware check (distance, IMU, ears, touch, audio, LED); add `--move` for motion/head sweep
- **Integration Test**: `tools/test_service_integration.py` - Validate AI services integration

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