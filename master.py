#!/usr/bin/env python3
import random
import time
import threading
import importlib

# ✅ Define Available Modules
module_names = {
    "patrol": "PatrolMode",
    "smart_patrol": "SmartPatrolMode",
    "smarter_patrol": "SmarterPatrolMode",
    "voice_patrol": "VoicePatrolMode"
}

def load_module(module_name):
    """Dynamically load a module and handle errors."""
    try:
        module = importlib.import_module(module_name)
        return getattr(module, "start_behavior")  # ✅ Ensure it has a start function
    except ModuleNotFoundError:
        print(f"❌ Module {module_name} not found! Skipping.")
        return None
    except AttributeError:
        print(f"⚠️ Module {module_name} does not have 'start_behavior'. Check implementation.")
        return None

def run_module_for_time(module_name, duration):
    """Run a module for a set duration in a separate thread."""
    behavior_function = load_module(module_name)
    if not behavior_function:
        return  # ✅ Exit if module couldn't be loaded
    
    thread = threading.Thread(target=behavior_function, daemon=True)
    thread.start()
    
    time.sleep(duration)  # ✅ Let the module run for `duration` seconds
    print(f"⏳ {module_name} completed. Returning to master script.")

if __name__ == "__main__":
    while True:
        selected_module = random.choice(list(module_names.keys()))  # ✅ Select a random module
        run_module_for_time(selected_module, duration=10)  # ✅ Run module for 10 seconds