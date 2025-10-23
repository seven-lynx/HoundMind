#!/usr/bin/env python3
"""
PiDog Master Control Script
==================================
This script serves as the central controller for PiDog’s behavior system, managing 
module execution and state-based transitions.

Key Features:
✅ Dynamically loads and executes behavior modules.
✅ Allows manual module selection with keyboard interruption (`spacebar`).
✅ Implements a shuffled queue for random module selection (to ensure variety).
✅ Tracks active threads and prevents thread accumulation.
✅ Logs errors with detailed traceback for debugging.
✅ Compatible with `global_state.py` for PiDog’s state-aware execution.

7-lynx
"""

import time
import threading
import importlib
import keyboard
import traceback
import random
import global_state  # ✅ Integrated state tracking

# ✅ Define Available Modules
module_names = {
    "patrol": "PatrolMode",
    "smart_patrol": "SmartPatrolMode",
    "smarter_patrol": "SmarterPatrolMode",
    "voice_patrol": "VoicePatrolMode",
    "voice_control": "WhisperVoiceControl",
    "idle_behavior": "IdleBehavior",  # ✅ Added new modules
    "emotion": "EmotionHandler",
    "find_open_space": "FindOpenSpace",
    "mic_test": "MicTest",
    "turn_toward_noise": "TurnTowardNoise",
    "reactions": "Reactions",
    "actions": "ActionsHandler",
}

# ✅ Track Active Threads
active_threads = []

def load_module(module_name):
    """
    Dynamically load a module and handle errors.

    Parameters:
    - module_name (str): The name of the module to load.

    Returns:
    - (function) The module's `start_behavior` function, or None if loading fails.
    """
    try:
        module = importlib.import_module(module_name)
        return getattr(module, "start_behavior")
    except ModuleNotFoundError:
        print(f"❌ ERROR: Module '{module_name}' not found! Skipping.")
    except AttributeError:
        print(f"⚠️ WARNING: '{module_name}' does not have 'start_behavior'. Check implementation.")
    except Exception as e:
        print(f"⚠️ Unexpected error while loading '{module_name}': {e}")
        traceback.print_exc()
    return None

def run_module_for_time(module_name, duration):
    """
    Run a module for a set duration in a separate thread.

    Parameters:
    - module_name (str): The module to execute.
    - duration (int): Time in seconds before switching modules.
    """
    behavior_function = load_module(module_name)
    if not behavior_function:
        return

    # ✅ Track and manage active threads
    thread = threading.Thread(target=behavior_function, daemon=True)
    active_threads.append(thread)
    thread.start()

    start_time = time.time()
    while time.time() - start_time < duration:
        if keyboard.is_pressed('space'):  # ✅ Interrupt with spacebar
            print("\n🔴 INTERRUPTED! Select a new module.")
            thread.join()  # ✅ Graceful shutdown before switching
            active_threads.remove(thread)
            select_module_manually()
            return
        time.sleep(0.1)

    print(f"⏳ {module_name} completed.")
    active_threads.remove(thread)

def select_module_manually():
    """
    Displays a numbered list of available modules and allows user selection with timeout.

    If no selection is made within 30 seconds, auto-selection resumes.
    """
    print("\n🚀 Available Modules:")
    module_list = list(module_names.keys())

    for i, module in enumerate(module_list, 1):
        print(f"{i}. {module}")

    print(f"{len(module_list) + 1}. Resume Random Module Selection")

    start_time = time.time()
    while time.time() - start_time < 30:  # ✅ Timeout after 30 seconds
        try:
            choice = input("\n🔢 Enter module number to run (or wait to resume auto-selection): ")
            if not choice:
                continue  # ✅ Ignore empty input

            choice = int(choice)
            if 1 <= choice <= len(module_list):
                run_module_for_time(module_list[choice - 1], duration=10)
                return
            elif choice == len(module_list) + 1:
                print("\n🔄 Resuming automatic module selection...")
                return
            else:
                print("❌ Invalid selection. Try again.")
        except ValueError:
            print("⚠️ Please enter a valid number.")

    print("\n⏳ Timeout reached. Resuming automatic module selection...")

# ✅ Implement a Shuffled Queue for Module Selection
def shuffled_module_queue():
    """
    Generates a shuffled queue of modules to ensure variety.

    Returns:
    - (list) A shuffled list of module names.
    """
    module_list = list(module_names.keys())
    random.shuffle(module_list)
    return module_list

if __name__ == "__main__":
    module_queue = shuffled_module_queue()  # ✅ Ensures non-repetitive selection

    while True:
        if not module_queue:  # ✅ Re-shuffle when queue is empty
            module_queue = shuffled_module_queue()

        selected_module = module_queue.pop(0)  # ✅ Select from queue
        run_module_for_time(selected_module, duration=10)
