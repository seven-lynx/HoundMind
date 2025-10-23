# PiDog Standalone AI Systems 🤖

This directory contains **complete, self-contained AI systems** for PiDog. Each file is a standalone program that provides full AI functionality without dependencies on the modular system.

## 🎯 **What Are Standalone AIs?**

These are **complete, ready-to-run AI programs** that include:
- All necessary imports and dependencies
- Built-in configuration systems  
- Complete behavior implementations
- Full sensor integration
- Independent state management

**Key Difference:** Unlike the modular system, these don't require external modules - each is a complete AI solution.

## 🚀 **Available Standalone AIs**

### 🧠 `advanced_pidog_ai.py`
**Complete AI-powered PiDog with advanced behaviors**
- Multi-sensor integration and decision making
- Emotional LED responses and learning patterns
- Sound-reactive head tracking
- Advanced movement coordination
- Energy management system

**Run:** `python advanced_pidog_ai.py`

### 🗺️ `house_mapping.py` 
**SLAM-based house mapping system**
- Real-time house mapping and room detection
- Persistent map storage and retrieval
- Autonomous exploration algorithms
- Obstacle detection and mapping

**Run:** `python house_mapping.py`

### 🎯 `pathfinding.py`
**Advanced pathfinding and navigation**
- A* pathfinding with dynamic obstacles
- Real-time path optimization
- Multi-goal navigation planning
- Obstacle memory and avoidance

**Run:** `python pathfinding.py`

### 📊 `map_visualization.py`
**Real-time map visualization system**
- Live mapping display and analysis
- Path visualization and tracking  
- Obstacle detection visualization
- Performance metrics dashboard

**Run:** `python map_visualization.py`

### 🔄 `sensor_fusion_localization.py`
**Advanced sensor fusion and localization**
- Multi-sensor data fusion (IMU, distance, vision)
- Kalman filtering for position estimation
- Dynamic localization and tracking
- Surface type detection and adaptation

**Run:** `python sensor_fusion_localization.py`

## ⚙️ **Configuration**

### `packmind_config.py`
**Centralized configuration for ALL standalone AIs**
```python
class PiDogConfig:
    # Enable/disable major systems
    ENABLE_VOICE_COMMANDS = True
    ENABLE_SLAM_MAPPING = True
    ENABLE_EMOTIONAL_SYSTEM = True
    
    # Sensor thresholds
    OBSTACLE_IMMEDIATE_THREAT = 20.0
    OBSTACLE_SAFE_DISTANCE = 40.0
    
    # Movement parameters
    TURN_STEPS_NORMAL = 2
    WALK_STEPS_NORMAL = 2
```

## 📚 **Documentation**

- **`PiDog_Configuration_Guide.txt`** - Detailed configuration options
- **`api_reference_enhanced.md`** - Complete API reference  
- **`intelligent_obstacle_avoidance_guide.md`** - Obstacle avoidance guide
- **`voice_setup_instructions.md`** - Voice control setup

## 🔗 **vs. Modular System**

| **Standalone AIs** | **Modular System** |
|-------------------|------------------|
| ✅ Complete programs | 🔧 Composable modules |
| ✅ Self-contained | 🔧 Requires integration |
| ✅ Ready to run | 🔧 Build your own system |
| ✅ All features included | 🔧 Mix and match features |
| ✅ Quick demos | 🔧 Long-term projects |

## 🚦 **Quick Start**

1. **Choose your AI system** based on what you want to demonstrate
2. **Configure** by editing `packmind_config.py` 
3. **Run directly** - no additional setup required!

```bash
# Example: Run the complete advanced AI
python advanced_pidog_ai.py

# Example: Run mapping system  
python house_mapping.py
```

## 💡 **When to Use Standalone AIs**

- **Demos and presentations** - Show complete AI functionality quickly
- **Testing new features** - Prototype without breaking modular system
- **Learning PiDog AI** - Study complete implementations  
- **Quick experiments** - Test ideas rapidly
- **Backup systems** - Reliable fallback implementations

---

*For the composable, modular PiDog system, see `../modular_system/`* 🔧