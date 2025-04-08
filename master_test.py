#!/usr/bin/env python3
import time
import threading
import importlib
import keyboard  # ✅ Added keyboard input for interruptions

# ✅ Define Available Modules
module_names = {
    "patrol": "PatrolMode",
    "smart_patrol": "SmartPatrolMode",
    "smarter_patrol": "SmarterPatrolMode",
    "voice_patrol": "VoicePatrolMode",
    "voice_control": "WhisperVoiceControl",  # ✅ Added voice control module
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

    start_time = time.time()
    while time.time() - start_time < duration:
        if keyboard.is_pressed('space'):  # ✅ Interrupt current execution with spacebar
            print("\n🔴 INTERRUPTED! Select a new module.")
            thread.join()  # ✅ Gracefully stop current thread before switching
            select_module_manually()
            return
        time.sleep(0.1)

    print(f"⏳ {module_name} completed. Returning to master script.")

def select_module_manually():
    """Displays a numbered list of available modules and allows user selection."""
    print("\n🚀 Available Modules:")
    module_list = list(module_names.keys())
    for i, module in enumerate(module_list, 1):
        print(f"{i}. {module}")

    print(f"{len(module_list) + 1}. Resume Random Module Selection")  # ✅ Added option for resuming random selection

    while True:
        try:
            choice = int(input("\n🔢 Enter module number to run: "))
            if 1 <= choice <= len(module_list):
                run_module_for_time(module_list[choice - 1], duration=10)
                return
            elif choice == len(module_list) + 1:  # ✅ Resume random selection
                print("\n🔄 Resuming automatic module selection...")
                return
            else:
                print("❌ Invalid selection. Try again.")
        except ValueError:
            print("⚠️ Please enter a valid number.")

if __name__ == "__main__":
    while True:
        selected_module = random.choice(list(module_names.keys()))  # ✅ Default: Randomly choose a module
        run_module_for_time(selected_module, duration=10)  # ✅ Run module for 10 seconds