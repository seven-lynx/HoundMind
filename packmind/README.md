# PackMind: Standalone PiDog AI 🤖

PackMind is a fully featured, standalone AI for PiDog. It contains its own orchestrator, services, behaviors, and subsystems for mapping, navigation, localization, and visualization.

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
```

## 📚 Documentation

- PackMind docs: `packmind/packmind_docs/`
    - `ARCHITECTURE.md`
    - `PackMind_Configuration_Guide.txt`
    - `intelligent_obstacle_avoidance_guide.md`
- Voice setup: `../docs/voice_setup_instructions.md`

For general PiDog programming resources, see `../docs/`.

## 🔗 vs. CanineCore (for clarity)

| PackMind (this) | CanineCore |
|---|---|
| ✅ Standalone AI | 🔧 Composable behavior framework |
| ✅ Self-contained orchestrator | 🔧 Uses behaviors + services |
| ✅ Quick demos, end-to-end | 🔧 Long-term customization |
| 🚫 No dependency on CanineCore | 🚫 No dependency on PackMind |

---

Want a framework to build your own behaviors? See `../canine_core/` 🔧
