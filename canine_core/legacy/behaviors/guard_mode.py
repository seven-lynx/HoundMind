#!/usr/bin/env python3
"""
PiDog Guard Mode (Optimized)
==================================
This module enables PiDog to monitor its surroundings for movement and react accordingly.

Key Features:
✅ **State Tracking:** `global_state.active_mode` changes when guard mode begins and **reverts after completion**.
✅ **Movement Logging:** Records detected movement events in `global_state.interaction_history`.
✅ **Error Handling:** Logs sensor failures in `global_state.error_log` for debugging.
✅ **Ultrasonic-Based Detection:** Uses distance sensors to trigger responses.

7-lynx
"""

import time
import global_state  # ✅ Integrated state tracking
from pidog import Pidog

# ✅ Initialize PiDog
dog = Pidog()
global_state.active_mode = "guard_mode"  # ✅ Track guard mode state

dog.do_action("stand", speed=80)  # ✅ Set Guard Mode position
dog.wait_all_done()
time.sleep(0.5)

def detect_movement():
    """Detect movement using ultrasonic sensor."""
    try:
        distance = dog.read_distance()
        print(f"Monitoring area... Distance: {distance} cm")

        if distance < 100:  # ✅ If movement is detected
            global_state.interaction_history.append({"timestamp": time.time(), "event": "movement_detected"})
            return True
        
    except Exception as e:
        global_state.error_log.append({"timestamp": time.time(), "error": f"Sensor failure: {e}"})
        print("❌ Error reading distance sensor!")

    return False  # ✅ No movement detected

def guard_mode():
    """Monitor surroundings and react to movement."""
    print("🚨 Entering Guard Mode...")

    try:
        while True:
            if detect_movement():
                print("Movement detected! Activating response...")
                dog.do_action("bark", speed=100)  # ✅ Alert sound
                dog.wait_all_done()
                time.sleep(0.5)

                dog.do_action("turn_left", step_count=5, speed=80)  # ✅ Look around
                dog.wait_all_done()
                time.sleep(0.5)

            else:
                print("No movement detected. Remaining in Guard Mode.")
                time.sleep(1)  # ✅ Pause between scans
    
    except KeyboardInterrupt:
        print("🚪 Exiting Guard Mode...")
        global_state.active_mode = "idle"  # ✅ Reset state before shutdown
        dog.do_action("stand", speed=50)  # ✅ Stop movement safely
        dog.wait_all_done()
        dog.close()  # ✅ Shut down PiDog properly

# ✅ Start Guard Mode
guard_mode()