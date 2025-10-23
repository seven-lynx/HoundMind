# PiDog Modular System 🔧

This directory contains the **modular, composable PiDog system** where you can mix and match behaviors, create custom combinations, and build your own PiDog personality.

## 🎯 **What is the Modular System?**

This is a **flexible framework** that allows you to:
- **Mix and match** different behaviors
- **Create custom combinations** of AI features
- **Build your own** PiDog personality 
- **Extend functionality** by adding new modules
- **Hot-swap behaviors** during runtime

**Key Difference:** Unlike standalone AIs, this system is designed for **customization and extension**.

## 📁 **System Architecture**

```
modular_system/
├── 🧠 core/           # Core system management
│   ├── master.py      # Module orchestration and control
│   ├── global_state.py # Centralized state management  
│   ├── memory.py      # Learning and memory system
│   ├── emotions.py    # Emotional intelligence
│   └── state_functions.py # State transitions
├── 🎭 behaviors/      # Individual behavior modules
│   ├── smart_patrol.py # Intelligent patrol behavior
│   ├── voice_patrol.py # Voice-controlled movement
│   ├── guard_mode.py  # Security and monitoring  
│   ├── idle_behavior.py # Engaging idle activities
│   ├── actions.py     # Action primitives
│   └── reactions.py   # Reactive behaviors
└── 🛠️ utils/          # Utility functions
    ├── turn_toward_noise.py # Audio response
    └── function_list.py # Function references
```

## 🔄 **How It Works**

### 1. **Master Controller** (`core/master.py`)
- Dynamically loads and switches between behavior modules
- Manages execution timing and transitions
- Handles user interrupts and manual control
- Prevents module conflicts and memory leaks

### 2. **Global State** (`core/global_state.py`)  
- Tracks active behaviors across all modules
- Maintains consistent state between switches
- Provides inter-module communication
- Stores persistent settings and preferences

### 3. **Memory System** (`core/memory.py`)
- **Short-term memory** for recent interactions
- **Long-term memory** with persistent storage  
- **Learning patterns** from user behavior
- **Automatic cleanup** of old memories

### 4. **Behavior Modules** (`behaviors/`)
- **Independent implementations** of specific behaviors
- **Standard interface** for easy integration
- **Hot-swappable** during runtime
- **Configurable parameters** for customization

## 🚀 **Running the Modular System**

### **Entry Point:** Use the main launcher
```bash
# From project root
python main.py
```

### **Direct Module Control:**
```bash  
# Run master controller directly
cd modular_system/core
python master.py
```

## 🎮 **Interactive Control**

The modular system provides **real-time control**:

- **Automatic Mode** - Cycles through behaviors intelligently
- **Manual Selection** - Press interruption key to choose behaviors
- **Dynamic Switching** - Change behaviors without restarting
- **State Persistence** - Maintains context between switches

## 🧩 **Available Modules**

### **Core Behaviors:**
- `smart_patrol` - Intelligent autonomous patrol
- `voice_patrol` - Voice-controlled navigation  
- `guard_mode` - Security monitoring and alerts
- `idle_behavior` - Engaging idle state activities

### **Interaction Modules:**
- `whisper_voice_control` - Advanced voice recognition
- `actions` - Basic movement and action primitives
- `reactions` - Environmental response behaviors
- `maintenance` - System health and diagnostics

## ⚙️ **Configuration**

The modular system uses **distributed configuration**:

### **Global Config** (`../config/canine_config.py`)
- System-wide settings
- Hardware parameters  
- Safety thresholds

### **Module-Specific Config**
Each module can have its own configuration within the file.

## 🔧 **Customization & Extension**

### **Adding New Behaviors:**
1. Create new module in `behaviors/`
2. Implement `start_behavior()` function
3. Add to module registry in `master.py`
4. Test with existing system

### **Custom Combinations:**
```python
# Example: Custom behavior sequence
def custom_patrol():
    run_module("smart_patrol", 30)  # 30 seconds
    run_module("guard_mode", 60)    # 1 minute  
    run_module("voice_patrol", 45)  # 45 seconds
```

## 🔗 **vs. Standalone AIs**

| **Modular System** | **Standalone AIs** |
|------------------|--------------------|
| 🔧 Mix and match behaviors | ✅ Complete programs |
| 🔧 Highly customizable | ✅ Ready-to-run |
| 🔧 Extensible framework | ✅ Self-contained |
| 🔧 Learning and memory | ✅ Quick demos |
| 🔧 Long-term projects | ✅ Immediate results |

## 💡 **When to Use Modular System**

- **Custom PiDog personalities** - Build unique behavior combinations
- **Long-term projects** - Develop and refine over time  
- **Learning and experimentation** - Try different module combinations
- **Production use** - Robust, maintainable system architecture
- **Team development** - Multiple people working on different modules

## 🧪 **Development Workflow**

1. **Start with existing modules** - Learn the system
2. **Customize parameters** - Tune behavior to your needs
3. **Create custom sequences** - Combine modules uniquely  
4. **Develop new modules** - Add your own behaviors
5. **Share and iterate** - Build on community contributions

---

*For ready-to-run complete AI systems, see `../packmind/`* 🤖