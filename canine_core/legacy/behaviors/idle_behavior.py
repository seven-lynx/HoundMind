#!/usr/bin/env python3
"""
PiDog Idle Behavior (Optimized)
==================================
This module manages PiDog’s **idle animations**, ensuring that it responds to environmental stimuli and acts independently.

Key Features:
✅ **State Tracking:** `global_state.active_mode` changes when idle mode begins and **reverts after completion**.
✅ **Behavior Logging:** Tracks executed idle actions in `global_state.interaction_history`.
✅ **Thread-Safe Execution:** Ensures `exit_flag` cleanly terminates sound listener when exiting idle mode.
✅ **Error Tracking:** Logs failures in `global_state.error_log` for debugging.
✅ **Sound-Based Interaction:** PiDog listens for sounds and adjusts its reaction dynamically.

7-lynx
"""

import time
import threading
import random
import global_state  # ✅ Integrated state tracking
from pidog import Pidog
from pidog.b9_rgb import RGB
from pidog.sound_sensor import SoundSensor
import actions  # ✅ Import centralized action execution

# ✅ Initialize PiDog, RGB, and sound sensor
dog = Pidog()
rgb = RGB(dog)
sound_sensor = SoundSensor(dog)

# ✅ Track Previous Active Mode Before Switching to Idle
previous_active_mode = global_state.active_mode  
global_state.active_mode = "idle"  # ✅ Temporarily override active mode

exit_flag = False  # ✅ Allows controlled exit when needed

# ✅ Fixed rotation list from `actions.py`
idle_actions = [actions.snooze, actions.lay_down, actions.bark, actions.wag_tail, actions.jump_and_wag, 
                actions.jump, actions.sit, actions.scratch_ear, actions.push_up, actions.tilting_head]

def listen_for_sound():
    """Continuously listen for incoming sounds and react based on direction."""
    while not exit_flag:
        if sound_sensor.isdetected():
            direction = sound_sensor.read()
            print(f"🔊 Sound detected! Adjusting direction {direction}°")
            react_to_sound(direction)
        time.sleep(0.5)  # ✅ Prevent unnecessary CPU usage
    print("🛑 Sound listener thread safely exited.")

def react_to_sound(direction):
    """PiDog reacts by barking and turning toward sound."""
    rgb.set_color((255, 0, 0))  # ✅ Red flash effect for alertness
    rgb.flash(2)

    dog.head_move([[direction, 0, 0]], speed=80)
    dog.wait_head_done()

    if abs(direction) > 30:  # ✅ Bark if the sound is loud
        print("🔊 Loud sound detected—PiDog is barking!")
        actions.bark()
        time.sleep(0.5)

    turn_direction = "right" if direction > 0 else "left"
    
    if hasattr(actions, f"turn_{turn_direction}_medium"):  # ✅ Ensure function exists
        getattr(actions, f"turn_{turn_direction}_medium")()  # ✅ Dynamic function call
    else:
        print(f"❌ Missing `{turn_direction}_medium` in `actions.py`. Skipping turn.")

    rgb.set_color((255, 255, 255))  # ✅ Reset LED after reaction

def execute_idle_action(action):
    """Safely execute an idle action, retrying with a random action if not found."""
    try:
        action()  # ✅ Attempt to execute action
        global_state.interaction_history.append({"timestamp": time.time(), "action": action.__name__})  # ✅ Log action execution
    except Exception as e:
        global_state.error_log.append({"timestamp": time.time(), "error": f"Failed to execute {action.__name__}: {e}"})  # ✅ Log error
        print(f"❌ Error executing {action.__name__}: {e}")

        new_action = random.choice(idle_actions)
        print(f"🔄 Choosing a new action: {new_action.__name__}")
        new_action()  # ✅ Retry with a different action

def start_behavior():
    """PiDog cycles through idle behaviors dynamically, while listening for sounds."""
    print("🐶 PiDog is entering idle mode...")
    threading.Thread(target=listen_for_sound, daemon=True).start()  # ✅ Start sound listener

    while not exit_flag:
        action = random.choice(idle_actions)
        execute_idle_action(action)  # ✅ Check and execute behavior safely
        time.sleep(random.randint(3, 6))

    print("🔴 Exiting Idle Mode...")

    global_state.active_mode = previous_active_mode  # ✅ Restore previous active mode
    print(f"🔄 Restored PiDog's previous mode: `{global_state.active_mode}`")

    rgb.set_color((255, 255, 255))  # ✅ Reset LED before shutdown
    dog.close()

# ✅ Allow execution via `master.py`
if __name__ == "__main__":
    try:
        start_behavior()
    except Exception as e:
        global_state.log_error(f"Unexpected error in `idle_behavior.py`: {e}")
        print("⚠️ Idle mode interrupted due to an error.")