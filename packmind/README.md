# PackMind: Standalone PiDog AI 🤖

PackMind is a fully featured, standalone AI for PiDog. It contains its own orchestrator, services, behaviors, and subsystems for mapping, navigation, localization, visualization, and **advanced AI services** for face recognition, dynamic balance, and enhanced audio processing.

Independence: PackMind and CanineCore are related but distinct projects. PackMind does not import or depend on CanineCore.

## 🚀 Run the AI Orchestrator

```powershell
python packmind/orchestrator.py
```

Configure behavior and features via `packmind/packmind_config.py` (presets available). The orchestrator enables features like voice, SLAM, sensor fusion, and autonomous navigation based on your config and installed dependencies.

## 📦 Subpackages (library modules)

- 🗺️ Mapping: `packmind/mapping/house_mapping.py`
    - SLAM-based house map, rooms, and landmarks
    - `from packmind.mapping.house_mapping import PiDogSLAM, CellType`

- 🎯 Navigation: `packmind/nav/pathfinding.py`
    - A* pathfinding and high-level navigation
    - `from packmind.nav.pathfinding import PiDogPathfinder, NavigationController`

- 🔄 Localization: `packmind/localization/sensor_fusion_localization.py`
    - IMU + ultrasonic sensor-fusion localization
    - `from packmind.localization.sensor_fusion_localization import SensorFusionLocalizer`

- 📊 Visualization: `packmind/visualization/map_visualization.py`
    - ASCII map printing and export tools
    - `from packmind.visualization.map_visualization import MapVisualizer`

- 🔍 **Face Recognition**: `packmind/services/face_recognition_service.py`
    - Real-time facial detection with personality adaptation
    - `from packmind.services.face_recognition_service import FaceRecognitionService`

- ⚖️ **Dynamic Balance**: `packmind/services/dynamic_balance_service.py`
    - IMU-based balance monitoring and tilt correction
    - `from packmind.services.dynamic_balance_service import DynamicBalanceService`

- 🔊 **Enhanced Audio**: `packmind/services/enhanced_audio_processing_service.py`
    - Multi-source sound tracking and voice activity detection
    - `from packmind.services.enhanced_audio_processing_service import EnhancedAudioProcessingService`

- 🧭 **Calibration**: `packmind/services/calibration_service.py`
    - Unified calibration routines (wall-follow, corner-seek, landmark-align)
    - Orchestrator delegates runtime calibration to this service
    - `from packmind.services.calibration_service import CalibrationService`

Note: Older top-level files like `house_mapping.py` or `pathfinding.py` were moved into these folders. Update imports accordingly.

## ⚙️ Configuration

Edit `packmind/packmind_config.py` and choose a preset or customize values. Example:

```python
class PiDogConfig:
        ENABLE_VOICE_COMMANDS = True
        ENABLE_SLAM_MAPPING = True
        ENABLE_SENSOR_FUSION = True
        ENABLE_EMOTIONAL_SYSTEM = True
        ENABLE_AUTONOMOUS_NAVIGATION = False
        # New AI Services
        ENABLE_FACE_RECOGNITION = True
        ENABLE_DYNAMIC_BALANCE = True
        ENABLE_ENHANCED_AUDIO = True
    # Calibration
    # (No toggle required; orchestrator delegates to CalibrationService when SLAM is enabled)
```

## 📚 Documentation

- PackMind docs: `packmind/packmind_docs/`
    - `ARCHITECTURE.md`
    - `../../docs/packmind_config_guide.md`
    - `intelligent_obstacle_avoidance_guide.md`
- Voice setup: `../docs/voice_setup_instructions.md`

### 🔧 Calibration quickstart

Voice commands (when SLAM is enabled):

- Say "PiDog calibrate" → wall-follow calibration via CalibrationService
- Say "PiDog find corner" → corner-seek calibration via CalibrationService

Programmatic use:

```python
from packmind.services.calibration_service import CalibrationService

cal = CalibrationService(slam_system=home_map, scanning_service=scanner, dog=pidog, logger=logger)
ok = cal.calibrate("wall_follow")  # or "corner_seek", "landmark_align"
```

For general PiDog programming resources, see `../docs/`.

## 🖥️ Desktop simulation mode

PackMind can run on a desktop without hardware using a built-in simulation shim:

- Set `HOUNDMIND_SIM=1` to force simulation for `from pidog import Pidog`.
- The simulator provides no-op motion and plausible sensor values so services like scanning and energy/emotion updates run.
- Optional `HOUNDMIND_SIM_RANDOM=1` adds light noise to IMU/ultrasonic data for testing.

Examples (PowerShell):

```powershell
$env:HOUNDMIND_SIM = "1"; python packmind/orchestrator.py
```

## 🧩 Face recognition on Raspberry Pi

There are two backends:

- `default`: `face_recognition` (dlib) — heavier, higher accuracy
- `lite`: OpenCV Haar + optional LBPH — no dlib, Pi 3B friendly

On Pi 4/5, the default backend works well via piwheels. On Pi 3B, use the lite backend to avoid building dlib:

```python
# packmind/packmind_config.py
class PiDogConfig:
    ENABLE_FACE_RECOGNITION = True
    FACE_BACKEND = "lite"  # Haar + optional LBPH (opencv-contrib)
```

- Detection-only: works with `opencv-python` (no contrib).
- Identity (LBPH): install `opencv-contrib-python` and train images under `data/faces_lite/<name>/*.jpg`.
- Train model: `python scripts/train_faces_lite.py --preset pi3`
- Smoke test: `python tools/lite_face_smoke_test.py --preset pi3 --duration 30`

See `docs/face_recognition_setup.md` for full guidance and troubleshooting.

## � Feature gates at a glance

PackMind features are toggled via `packmind/packmind_config.py` presets or custom values:

- Voice commands: `ENABLE_VOICE_COMMANDS`
- SLAM mapping: `ENABLE_SLAM_MAPPING`
- Sensor fusion: `ENABLE_SENSOR_FUSION`
- Intelligent scanning: `ENABLE_INTELLIGENT_SCANNING`
- Emotional system: `ENABLE_EMOTIONAL_SYSTEM`
- Learning: `ENABLE_LEARNING_SYSTEM`
- Patrol logging: `ENABLE_PATROL_LOGGING`
- Autonomous navigation: `ENABLE_AUTONOMOUS_NAVIGATION`

Logging can be tuned via `LOG_LEVEL`, `LOG_FILE_MAX_MB`, and `LOG_FILE_BACKUPS`.

## �🔗 vs. CanineCore (for clarity)

| PackMind (this) | CanineCore |
|---|---|
| ✅ Standalone AI | 🔧 Composable behavior framework |
| ✅ Self-contained orchestrator | 🔧 Uses behaviors + services |
| ✅ Quick demos, end-to-end | 🔧 Long-term customization |
| 🚫 No dependency on CanineCore | 🚫 No dependency on PackMind |

---

Want a framework to build your own behaviors? See `../canine_core/` 🔧

## Future work

- Desktop simulation shim for PiDog
    - Drop-in class compatible with `pidog.Pidog` (no-op motion; plausible sensor readings)
    - Enable with `HOUNDMIND_SIM=1` or a config preset; supports deterministic seeds for tests
    - Later: optional ROS2/Gazebo or Webots backends for physics
- Calibration UX
    - Voice-guided flow; per-surface profiles; saved calibration snapshots
- Balance corrections
    - Minimal safe corrective motions when IMU detects tilt (cooldown; guardrails)
- Developer tooling
    - Service smoke tests, simulator-backed integration tests, CI workflow
- UI & telemetry
    - Optional local dashboard: logs, map preview, service health, scan charts
