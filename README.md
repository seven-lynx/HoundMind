# PiDog Enhanced Functionality Project 🚀🐶

A comprehensive robotics project expanding the capabilities of the Sunfounder PiDog through **two distinct systems**: standalone AI programs and a modular framework.

## 🎯 **Two Systems, Two Approaches**

### 🤖 **PackMind AI Systems** (`packmind/`)
**Complete, ready-to-run AI programs** - Just run and go!

### 🔧 **Modular System** (`modular_system/`)
**Composable framework** - Build your own PiDog personality!
- **Purpose:** Custom behaviors, long-term projects, extensibility  
- **Usage:** `python main.py`
- **Features:** Mix/match modules, hot-swapping, learning system

## 📁 **Project Structure**

```
Pidog/
├── 📄 main.py                    # Entry point for MODULAR system
├── 📄 README.md                  # This file
├── 📄 requirements.txt           # Dependencies
├── 🤖 packmind/                  # Complete AI programs (ready-to-run)
│   ├── 🧠 advanced_pidog_ai.py  # Complete AI with all features
│   ├── 🗺️ house_mapping.py      # SLAM mapping system
│   ├── 🎯 pathfinding.py        # Advanced pathfinding
│   ├── 📊 map_visualization.py   # Real-time mapping display
│   ├── 🔄 sensor_fusion_localization.py # Multi-sensor fusion
│   ├── ⚙️ pidog_config.py       # Config for standalone AIs
│   ├── 📚 *.md, *.txt           # Standalone AI documentation
│   └── 📖 README.md             # Standalone AI guide
├── 🔧 modular_system/            # Composable framework
│   ├── 🧠 core/                 # Core system management
│   │   ├── master.py            # Module orchestration  
│   │   ├── global_state.py      # State management
│   │   ├── memory.py            # Learning system
│   │   └── emotions.py          # Emotional intelligence
│   ├── 🎭 behaviors/            # Behavior modules
│   │   ├── smart_patrol.py      # Intelligent patrol
│   │   ├── voice_patrol.py      # Voice-controlled movement
│   │   ├── guard_mode.py        # Security monitoring
│   │   └── ...                 # Other behaviors
│   ├── 🛠️ utils/                # Utility functions
│   └── 📖 README.md             # Modular system guide  
├── 🧪 tests/                    # Test files for both systems
├── ⚙️ config/                   # Shared configuration
├── 📚 docs/                     # All documentation
├── 💡 examples/                 # Example usage scripts
└── 🔧 scripts/                  # Setup and installation
```

## 🚀 **Which System Should I Use?**

### 🤖 **Choose Standalone AIs If You Want:**
- ✅ **Quick demos** - Show off PiDog capabilities immediately
- ✅ **Complete solutions** - Everything included, no assembly required  
- ✅ **Learning/studying** - Understand complete AI implementations
- ✅ **Testing features** - Try specific AI capabilities
- ✅ **Presentations** - Reliable, impressive demonstrations

### 🔧 **Choose Modular System If You Want:**
- ✅ **Custom behaviors** - Build your own unique PiDog personality
- ✅ **Long-term projects** - Develop and refine over time
- ✅ **Mix and match** - Combine different behaviors creatively
- ✅ **Learning system** - PiDog that adapts and remembers
- ✅ **Extensibility** - Add your own modules and features

## 🚀 **Quick Start**

### **Option A: Standalone AI (Instant Results)**
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure (edit packmind/packmind_config.py if needed)

# 3. Run any complete AI system
python packmind/advanced_pidog_ai.py
python packmind/house_mapping.py  
python packmind/pathfinding.py
```

### **Option B: Modular System (Customizable)**
```bash
# 1. Install dependencies  
pip install -r requirements.txt

# 2. Configure (edit canine_core/config/canine_config.py if needed)

# 3. Choose interactively or run the orchestrator
python main.py               # Auto (orchestrator default)
python canine_core/control.py  # Interactive control menu
python main.py
```

## 🔧 Key Features

- **🎙️ Voice Control**: Wake word activation and natural language commands
- **🗺️ SLAM Mapping**: Advanced house mapping and localization  
- **🛡️ Guard Mode**: Motion detection and security patrol
- **🧠 AI Behaviors**: Intelligent pathfinding and obstacle avoidance
- **💭 Memory System**: Learning from interactions and experiences
- **😊 Emotional AI**: Dynamic LED emotions and behavioral responses

## 📚 Module Overview

### Core Modules (`src/core/`)
- **master.py**: Main control system and module management
- **global_state.py**: Centralized state tracking across modules
- **memory.py**: Short-term and long-term memory with persistence
- **emotions.py**: Emotional intelligence and LED expression system

### Behavior Modules (`src/behaviors/`)
- **smart_patrol.py**: Intelligent autonomous patrol with obstacle avoidance
- **voice_patrol.py**: Voice-controlled patrol and navigation
- **guard_mode.py**: Security monitoring and motion detection
- **idle_behavior.py**: Engaging idle state behaviors

### AI Modules (`src/ai/`)
- **sensor_fusion_localization.py**: Multi-sensor localization system
- **pathfinding.py**: A* pathfinding with dynamic obstacle avoidance
- **house_mapping.py**: SLAM-based house mapping and room detection
- **advanced_pidog_ai.py**: High-level AI decision making

## 🧪 Testing

Run individual behavior tests:
```bash
python tests/voice_command_test.py
python tests/smart_patrol_test.py
python tests/master_test.py
```

## 📖 Documentation

Comprehensive guides available in the `docs/` directory:
- Programming Guide (`PIDOG_PROGRAMMING_GUIDE.md`)
- Quick Start Guide (`QUICK_START_PROGRAMMING.md`) 
- Configuration Guide (`PiDog_Configuration_Guide.txt`)
- Voice Setup Instructions (`voice_setup_instructions.md`)

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the terms found in the `LICENSE` file.

## 👨‍💻 Author

**seven-lynx** - *Initial work and ongoing development*

---

*Transforming PiDog into an intelligent, autonomous robotic companion! 🐕‍🦺*