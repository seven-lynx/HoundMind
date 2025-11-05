
# HoundMind — Advanced Behaviors and AI for SunFounder PiDog
> Author: 7Lynx · Doc Version: 2025.11.03


HoundMind is a next-generation AI and behavior framework for the SunFounder PiDog, featuring:

- **CanineCore**: Modular async orchestrator and behavior system for composing, running, and extending behaviors and services.
- **PackMind**: Standalone AI orchestrator with advanced mapping, navigation, sensor fusion, and intelligent services.

Both systems are independent—choose the one that fits your needs. All legacy mapping/navigation logic has been fully removed and replaced with a modern, sensor-fusion-based HomeMap system. Legacy modules are archived in the `legacy/` folder.


## What's inside

- **CanineCore** (`canine_core/`): Async orchestrator, modular services (motion, sensors, emotions, voice), and composable behavior modules.
- **PackMind** (`packmind/`): AI orchestrator with advanced mapping (HomeMap), navigation (A*), sensor fusion, localization, face recognition, dynamic balance, enhanced audio, and more.
- **Docs** (`docs/`): Programming guides, API reference, config guides, and architecture docs. See [`docs/CANINE_CORE_PACKMIND_FEATURE_MATRIX.md`](docs/CANINE_CORE_PACKMIND_FEATURE_MATRIX.md) for a side-by-side capability matrix.
- **Tools** (`tools/`): Setup utilities and integration tests.
- **Examples** (`examples/`): Runnable code examples.
- **Legacy** (`legacy/`): Archived modules (pre-2025, not maintained).


## Install and run

New to the project? Start with the step‑by‑step install guide:

- See `docs/INSTALL.md` for Raspberry Pi and Desktop (simulation) paths.
- On the Pi, there’s a guided installer that can install vendor modules, set up audio, and install HoundMind deps, and even launch either system:
	```bash
	python3 scripts/pidog_install.py
	```

Guided installer quick start (Pi):
- 1) Install vendor modules (Robot HAT 2.5.x, Vilib, PiDog)
- 2) I2S audio setup (reboot when prompted)
- 3) Run vendor wake‑up demo (checks servos/sound)
- 5) Verify imports and I2C devices
- 6) Install HoundMind deps (Pi 4/5 full) or 7) (Pi 3B lite)
- 8) Launch CanineCore (main) · 9) CanineCore control · 10) PackMind (optional preset)

Tip: Do OS imaging (A0) first; the installer covers A1 → A4 from `docs/INSTALL.md` and is safe to run multiple times.

### Before you start (Pi): OS imaging checklist

- Use Raspberry Pi Imager to write Raspberry Pi OS (Bookworm) to the microSD
	- Pi 4/5: 64‑bit OS; Pi 3B: 32‑bit OS recommended (64‑bit supported with more manual dependency work)
	- In Advanced options: set hostname, enable SSH, add Wi‑Fi, set locale/timezone
- First boot on the Pi → update and reboot:
	```bash
	sudo apt update && sudo apt upgrade -y
	sudo reboot
	```
- Enable required interfaces:
	```bash
	sudo raspi-config
	# Interface Options → I2C → Enable (required); Camera → Enable (optional)
	```
- Verify I2C exists and (optionally) probe:
	```bash
	ls -l /dev/i2c-1
	sudo apt install -y i2c-tools
	i2cdetect -y 1
	```
- Full steps: see `docs/INSTALL.md#A0-install-raspberry-pi-os-one-time-on-the-microsd`

## Quick install and run on the Raspberry Pi 🧰

If you want one menu that does it all, use the guided installer (recommended):

```bash
cd ~/HoundMind
python3 scripts/pidog_install.py
```

Manual installs (summary) — see `docs/INSTALL.md` for full steps:

- Pi 4/5 (full features):
	```bash
	sudo apt update && sudo apt install -y portaudio19-dev python3-dev cmake build-essential libopenblas-dev liblapack-dev python3-venv
	cd ~/HoundMind && python3 -m venv .venv && . .venv/bin/activate && python -m pip install --upgrade pip
	pip install -r requirements.txt
	```

- Pi 3B (lite path, avoids source builds on py3.13/armv7l):
	```bash
	sudo apt update && sudo apt install -y \
		portaudio19-dev python3-dev python3-venv \
		python3-numpy python3-scipy python3-matplotlib python3-opencv python3-pil \
		libopenblas-dev liblapack-dev
	cd ~/HoundMind && python3 -m venv .venv --system-site-packages && . .venv/bin/activate && python -m pip install --upgrade pip
	pip install -r requirements-lite.txt
	```

Notes
- On Pi 3B, heavy packages (numpy/scipy/matplotlib/opencv/pillow) come from apt; the venv uses `--system-site-packages` so Python can see them. This avoids long/fragile source builds on Python 3.13/ARMv7.
- Voice: install PortAudio headers via apt; then `pip install SpeechRecognition pyaudio` (or `sudo apt install python3-pyaudio`).
- Face recognition: on Pi 4/5 you can try `face_recognition`; on Pi 3B use the lite backend (OpenCV Haar + optional LBPH). See `docs/requirements.md`.

Desktop (simulation) quick start

- Use the desktop requirements and enable the simulator:

```powershell
pip install -r requirements-desktop.txt
$env:HOUNDMIND_SIM = "1"
python packmind/orchestrator.py
```

Pi 3B: Lite face backend (no dlib)

If you want face detection (and optional simple identity) without `dlib` on a Pi 3B, use the lite backend:

```python
# packmind/packmind_config.py
class PiDogConfig:
	ENABLE_FACE_RECOGNITION = True
	FACE_BACKEND = "lite"  # OpenCV Haar + optional LBPH (opencv-contrib)
```

- Detection-only works with plain `opencv-python`.
- For identity (LBPH), install `opencv-contrib-python`.
- Train from images: place JPGs under `data/faces_lite/<name>/*.jpg` and run:

```powershell
python scripts/train_faces_lite.py --preset pi3
```

Smoke test the lite backend (camera required):

```powershell
python tools/lite_face_smoke_test.py --preset pi3 --duration 30
```

See `docs/face_recognition_setup.md` for more.


3) Run one of the systems

**PackMind (standalone AI, with advanced mapping/navigation):**

```bash
python3 packmind/orchestrator.py
# or
python3 packmind.py
# or
python -m packmind
```

**CanineCore (modular behaviors):**

```bash
python3 main.py                # Orchestrator default
python3 canine_core/control.py # Interactive behavior menu
```

Tip: On a development PC without hardware, many hardware services fallback to safe no-ops. Camera/audio/servos still require proper setup when you move to the Pi.

Platform quick picks:
- Desktop (no hardware): set `HOUNDMIND_SIM=1` and run.
- Raspberry Pi 3B: use the `pi3` preset (auto-selected on ARMv7) or explicitly: `PACKMIND_CONFIG=pi3`.
- Raspberry Pi 4/5: use `advanced` or `indoor` depending on your use case.
See `docs/platform_guide.md` for details.


## Which should I choose?

- **PackMind**: Full-featured AI demo with advanced mapping (HomeMap), navigation, sensor fusion, and intelligent services. Ideal for autonomous exploration, navigation, and advanced behaviors.
- **CanineCore**: Clean, composable framework for building your own behaviors and services. Great for custom projects and interactive control.

## Features at a glance


### Core Features
- Voice commands with optional wake word (when enabled)
- Intelligent scanning and obstacle avoidance
- Behavior orchestration and state handling
- Emotional LED themes and reactive sounds
- **Modern HomeMap mapping/navigation** (PackMind):
	- Openings and safe_paths for robust navigation
	- Bayesian occupancy grid with dynamic obstacle fading
	- Visual anchors and semantic map labels
	- Sensor fusion (camera, IMU, distance, touch, sound)
	- Advanced map visualization and export
- A* navigation and sensor-fusion localization

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

This is a quick map of the major modules and what they do. All mapping/navigation logic is now based on the new HomeMap system—no legacy code remains.

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
		- `mapping/`, `nav/`, `localization/`, `visualization/`: 
			- `mapping/home_mapping.py`: HomeMap class (openings, safe_paths, anchors, semantic labels, sensor fusion)
			- `nav/pathfinding.py`: A* pathfinding using HomeMap
			- `localization/`: Sensor-fusion localization
			- `visualization/map_visualization.py`: Advanced map visualization and export
	- `behaviors/`: High-level PackMind behaviors (exploring, patrolling, interacting, etc.)
	- `packmind_config.py`: Tunable settings (SOUND_*, VOICE_*, SCAN_*, ENERGY_*, NAV_*, WATCHDOG_*, etc.)
	- `packmind_docs/`: Architecture and configuration guides
```


## How modules interact (at a glance)

High-level dataflow and control paths for each system. All navigation and mapping now use HomeMap and advanced sensor fusion.

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
    ↔ mapping/ (home_mapping), nav/ (A* pathfinding), localization/
	    - HomeMap (openings, safe_paths, anchors, semantic labels, sensor fusion)
	    - Map queries and updates via HomeMap API
	    - Pathfinding and navigation use HomeMap exclusively
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

### Desktop simulation mode (no hardware required)

You can force a lightweight simulation for the `pidog` library so code runs on a desktop without any hardware:

- Set an environment variable before running:
	- PowerShell (Windows): `$env:HOUNDMIND_SIM = "1"; python packmind/orchestrator.py`
	- Bash (Linux/macOS): `HOUNDMIND_SIM=1 python3 packmind/orchestrator.py`
- When enabled, `from pidog import Pidog` will resolve to a simulated class that:
	- Accepts all basic motion calls (`do_action`, `head_move`, `body_stop`, `wait_all_done`)
	- Provides plausible sensor reads (`ultrasonic.read_distance()`, `dual_touch.read()`, `ears.isdetected()/read()`)
	- Exposes IMU-like attributes (`accData`, `gyroData`) with stable values and optional noise
	- Is safe: all motion is no-op and won’t affect hardware

Tip: You can also enable small randomization with `HOUNDMIND_SIM_RANDOM=1`.

### Hardware vs Simulator imports: `pidog` vs `pidog_sim`

- `from pidog import Pidog` (default):

	- On the robot (with the official library installed), this uses the real hardware library automatically.
	- On desktops or when the real library isn’t present, it safely falls back to the built‑in simulator.
	- You can still force simulation anywhere by setting `HOUNDMIND_SIM=1`.

- `from pidog_sim import Pidog` (explicit simulator):

	- Always uses the simulator, regardless of what’s installed on the system.
	- Helpful for examples/tests that should never touch hardware.

Under the hood, `pidog` is a drop‑in shim that delegates to the real library on the Pi and simulates elsewhere. `pidog_sim` is a tiny alias that forces sim mode for clarity.


## Documentation

- Programming Guide: `docs/PIDOG_PROGRAMMING_GUIDE.md`
- Quick Start Programming: `docs/QUICK_START_PROGRAMMING.md`
- API Reference: `docs/api_reference.md`
- Voice Setup: `docs/voice_setup_instructions.md`
- CanineCore configuration: `docs/canine_core_config_guide.md`
- PackMind architecture: `packmind/packmind_docs/ARCHITECTURE.md`
- PackMind configuration: `docs/packmind_config_guide.md`
- **Mapping & Navigation**: See `packmind/mapping/home_mapping.py` and `packmind/packmind_docs/intelligent_obstacle_avoidance_guide.md` for advanced HomeMap usage and API details.

### Telemetry dashboard (optional)

An experimental P1 telemetry dashboard is available for basic status and event streaming.

- Quickstart: `docs/telemetry_quickstart.md`
- Start with config defaults:

```bash
python tools/run_telemetry.py
```

- Override host/port or force start even if disabled:

```bash
python tools/run_telemetry.py --host 0.0.0.0 --port 8765
python tools/run_telemetry.py --force
```

## Testing & Tools

- **Setup Tool**: `tools/setup_pidog.py` - Initial PiDog setup and calibration
- **PackMind Checkup (Pi)**: `tools/packmind_checkup.py` - Import + service smoke tests on the PiDog (no movement)
	- Use `--move` to include a small ScanningService head sweep (limited motion)
- **CanineCore Checkup (Pi)**: `tools/caninecore_checkup.py` - Import all CanineCore modules; optional minimal head sweep with `--move`
- **PiDog Hardware Check (Pi)**: `tools/pidog_hardware_check.py` - Direct hardware check (distance, IMU, ears, touch, audio, LED); add `--move` for motion/head sweep
- **Integration Test**: `tools/test_service_integration.py` - Validate AI services integration
- **Audio Device Lister**: `tools/list_audio_devices.py` - Enumerate input/microphone devices and indexes (useful for setting `VOICE_MIC_INDEX`)
	- Windows PowerShell:
		```powershell
		python tools/list_audio_devices.py
		```
	- Raspberry Pi:
		```bash
		python3 tools/list_audio_devices.py
		```
- **Camera Check**: `tools/camera_check.py` - Diagnose camera access, print properties, and optionally save a frame
	- List devices and try index 0:
		```powershell
		python tools/camera_check.py --list-devices --max-index 10
		```
	- Windows tip (try DirectShow backend):
		```powershell
		python tools/camera_check.py --backend dshow --index 0 --save frame.jpg
		```
	- Linux/Pi tip (V4L2 is typical; try a different index):
		```bash
		python3 tools/camera_check.py --index 0 --save frame.jpg
		```

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

Below are common issues, how they show up, why they happen, and how to fix them.

### Voice (ASR) install and device selection

Symptoms
- `ImportError: No module named 'pyaudio'`
- `OSError: PortAudio library not found`
- `ALSA: No default input device` or speech not detected

Fix (Raspberry Pi)
```bash
sudo apt update && sudo apt install -y portaudio19-dev python3-dev
python3 -m pip install SpeechRecognition pyaudio
# If building PyAudio fails on your Pi OS:
sudo apt install -y python3-pyaudio
python3 -m pip install SpeechRecognition
```

Fix (Windows)
```powershell
pip install SpeechRecognition pyaudio
# If PyAudio wheel fails to install:
pip install pipwin
pipwin install pyaudio
```

Select the right mic
- Set `VOICE_MIC_INDEX` in `packmind/packmind_config.py` (default 0). If you have multiple devices, try 1, 2, ... until recognition responds.
- Tip: Start PackMind and watch the logs; it will state the mic index used.

### Camera (OpenCV) not opening

Symptoms
- `cv2.VideoCapture(0)` fails, or frames are empty

Fix
- Ensure the camera is enabled in OS settings and connected.
- Try a different device index: set env `CAM_INDEX=1` (or 2) before running.
- On Pi (Bookworm/libcamera), verify the camera works with a basic test app. If OpenCV access keeps failing, consider using USB webcams or ensuring V4L compatibility.
 - Use the camera diagnostic tool to probe indexes/backends and save a test frame:
 	```powershell
 	python tools/camera_check.py --list-devices --max-index 10
 	python tools/camera_check.py --backend dshow --index 0 --save frame.jpg  # Windows tip
 	```

### `pidog` import confusion or forced sim

Symptoms
- `ModuleNotFoundError: No module named 'pidog'` or unexpected simulator/hardware behavior

Fix
- On the robot, use the default shim: `from pidog import Pidog` (uses real hardware if installed, else sim).
- To always simulate (e.g., docs/tests): `from pidog_sim import Pidog`.
- To force simulation for a run:
	- PowerShell: `$env:HOUNDMIND_SIM = "1"; python -m packmind`
	- Bash: `HOUNDMIND_SIM=1 python3 -m packmind`

### `canine_core` / `packmind` not found when running tools

Symptoms
- `ModuleNotFoundError: canine_core` or `packmind` when executing scripts from `tools/`

Fix
- Run from the repository root. The tools include a small `sys.path` bootstrap, so running from `HoundMind/` should just work:
```bash
python3 tools/packmind_checkup.py --scope services
```

### Face recognition heavy on Pi 3B

Symptoms
- Slow installs (dlib build), high CPU, delayed recognition

Fix
- Use the lite backend:
	- In `packmind/packmind_config.py`: `FACE_BACKEND = "lite"` (keep `ENABLE_FACE_RECOGNITION = True`).
	- Detection-only works with `opencv-python`; for identity (LBPH), install `opencv-contrib-python`.
- Prefer `requirements-lite.txt` on Pi 3B.

### Version conflicts (NumPy/OpenCV) on ARM

Symptoms
- `ImportError: version mismatch`, `illegal instruction`, or crashes on import

Fix
- On Pi, prefer wheels from piwheels (default on Raspberry Pi OS). If you upgraded elsewhere, try:
```bash
python3 -m pip uninstall -y numpy opencv-python
python3 -m pip install --no-cache-dir numpy opencv-python
```

### Telemetry server binding / port in use

Symptoms
- `Address already in use` or cannot connect from another device

Fix
```powershell
python tools/run_telemetry.py --host 0.0.0.0 --port 8765  # bind to all interfaces
```
- If a firewall blocks access, allow the port or try a different one with `--port`.

### Watchdog timeouts under load

Symptoms
- Logs show `Watchdog timeout detected - executing safety action`

Fix
- Increase `WATCHDOG_TIMEOUT_S` slightly in `packmind/packmind_config.py` for Pi 3B.
- Let HealthMonitor degrade scan rate under load (already enabled). You can tame scanning by raising `OBSTACLE_SCAN_INTERVAL`.

### ALSA/audio permissions or device issues (Pi)

Symptoms
- Microphone not detected or permission errors

Fix
- Ensure your user is in the appropriate audio groups (often handled by the OS). Reboot after adding audio packages. If issues persist, try a USB microphone.

### General checks

Run safe checkups on the Pi:
```bash
python3 tools/packmind_checkup.py --scope services
python3 tools/caninecore_checkup.py --scope import
python3 tools/pidog_hardware_check.py                # add --move for a small head sweep
```

## License

See `LICENSE` for details.


---

## Modern Mapping & Navigation (PackMind)

All mapping and navigation in PackMind is now powered by the HomeMap system:

- **Openings**: Automatically detected and user-registered doorways, passages, and exits.
- **Safe Paths**: Dynamically updated, sensor-fused paths through the environment, avoiding obstacles and hazards.
- **Anchors**: Visual or semantic map anchors for robust localization and behavior triggers.
- **Semantic Labels**: User- or AI-assigned labels for map regions (e.g., "kitchen", "charging station").
- **Sensor Fusion**: Combines camera, IMU, distance, touch, and sound for robust mapping and navigation.
- **Dynamic Obstacle Fading**: Temporary obstacles fade over time for adaptive path planning.
- **Advanced Visualization**: Export and visualize maps with all features, anchors, and safe paths.

See the API reference and mapping guide for usage patterns and advanced queries.

---

Built to help you teach, learn, and explore with PiDog.

## Roadmap / Future work

- Desktop PiDog simulation shim (no-op motion, plausible sensors)
	- Drop-in replacement for `pidog.Pidog` to run on Windows/macOS/Linux
	- Tiers: 0) no-op fixed values; 1) randomized noisy signals; 2) seeded deterministic; 3) optional ROS2/Gazebo later
	- Opt-in via environment variable (e.g., `HOUNDMIND_SIM=1`) or config preset; keeps PackMind/CanineCore code unchanged
- Rich calibration UX
	- Voice-guided calibration flow; on-device prompts; store results per surface profile
- Balance corrections (hardware-aware)
	- Minimal safe leg/pose adjustments for roll/pitch with cooldowns
- Navigation & mapping enhancements
	- Goal-directed exploration, room labeling, multi-session map merge, map export/import UI
- Testing and CI
	- Simulation-based unit tests for services and orchestrators; GitHub Actions workflow
- Telemetry and dashboards
	- Optional local web dashboard for status, logs, map summary, and live scan data
- Packaging & releases
	- Versioned GitHub Releases, optional pip extras for advanced services
