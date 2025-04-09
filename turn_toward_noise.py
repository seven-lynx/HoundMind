#!/usr/bin/env python3
"""
PiDog Sound-Based Interaction (Optimized)
==================================
This module allows PiDog to detect sounds and adjust its direction dynamically,
enhancing responsiveness to its environment.

Key Features:
✅ **State Tracking:** `global_state.active_mode` changes when reacting to noise and **reverts after completion**.
✅ **Thread-Safe Execution:** Ensures `exit_flag` cleanly terminates sound listener when needed.
✅ **Error Tracking:** Logs failures in `global_state.error_log` for debugging.
✅ **Function Verification:** Checks if `actions.py` methods exist before execution.
✅ **Real-Time Sound Response:** PiDog listens for sounds and adjusts movement accordingly.


7-lynx
"""

import time
import threading
import global_state  # ✅ Integrated state tracking
import actions  # ✅ Import centralized action execution
from pidog import Pidog
from pidog.b9_rgb import RGB
from pidog.sound_sensor import SoundSensor

# ✅ Initialize PiDog, RGB, and sound sensor
dog = Pidog()
rgb = RGB(dog)
sound_sensor = SoundSensor(dog)

# ✅ Track Previous Active Mode Before Switching
previous_active_mode = global_state.active_mode  
global_state.active_mode = "reacting_to_noise"  # ✅ Temporarily override active mode

exit_flag = False  # ✅ Allows controlled exit when needed

def detect_sound():
    """Continuously listens for sounds and turns PiDog toward the source."""
    while not exit_flag:
        if sound_sensor.isdetected():
            direction = sound_sensor.read()
            print(f"🔊 Sound detected! Adjusting direction {direction}°")
            turn_toward_noise(direction)
        time.sleep(0.5)  # ✅ Prevent unnecessary CPU usage
    print("🛑 Sound listener thread safely exited.")

def turn_toward_noise(direction):
    """PiDog tilts head and turns body toward the detected noise."""
    rgb.set_color((255, 165, 0))  # ✅ Alert color (orange)
    rgb.flash(2)

    dog.head_move([[direction, 0, 0]], speed=80)
    dog.wait_head_done()

    if abs(direction) > 30:  # ✅ Turn body only for loud noises
        turn_direction = "right" if direction > 0 else "left"

        if hasattr(actions, f"turn_{turn_direction}_medium"):  # ✅ Ensure function exists
            print(f"🎯 Turning body toward noise ({direction}°)...")
            getattr(actions, f"turn_{turn_direction}_medium")()
        else:
            global_state.error_log.append({"timestamp": time.time(), "error": f"Missing `{turn_direction}_medium` in `actions.py`"})
            print(f"❌ Missing `{turn_direction}_medium` in `actions.py`. Skipping turn.")

    rgb.set_color((255, 255, 255))  # ✅ Reset LED after reaction

# ✅ Restore Previous Active Mode After Execution
global_state.active_mode = previous_active_mode
print(f"🔄 Restored PiDog's previous mode: `{global_state.active_mode}`")

# ✅ Allow execution safely if called directly
if __name__ == "__main__":
    try:
        detect_sound()
    except Exception as e:
        global_state.log_error(f"Unexpected error in `turn_toward_noise.py`: {e}")
        print("⚠️ Sound detection interrupted due to an error."