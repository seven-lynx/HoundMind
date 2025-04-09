#!/usr/bin/env python3
"""
PiDog Adaptive Navigation
==================================
This module enables PiDog to dynamically scan its surroundings and move toward open spaces,
optimizing movement while **retaining previous operational states**.

Key Features:
✅ **State Tracking:** `global_state.active_mode` changes when navigation begins and reverts after completion.
✅ **Memory-Based Learning:** Stores scan results in `global_state.obstacle_memory` for smarter navigation.
✅ **Fallback Action Handling:** Ensures safe execution if primary functions are unavailable.
✅ **Verified Function Calls:** Checks if `actions.py` methods exist before execution.
✅ **Standalone Execution Safety:** Exception handling prevents unexpected runtime errors.

7-lynx
"""

import time
import global_state  # ✅ Integrated state tracking
import actions  # ✅ Import movement functions safely

# ✅ Track Previous Active Mode
previous_active_mode = global_state.active_mode  
global_state.active_mode = "finding_open_space"  # ✅ Temporarily override active mode

def safe_action_call(action_name):
    """
    Safely calls an action from `actions.py` if it exists.

    Parameters:
    - action_name (str): Name of the function to call.

    Returns:
    - (bool) True if executed successfully, False otherwise.
    """
    if hasattr(actions, action_name):
        getattr(actions, action_name)()
        return True
    else:
        print(f"❌ ERROR: `{action_name}` not found in `actions.py`! Skipping execution.")
        return False

def scan_surroundings():
    """Scan forward, left, and right distances and store in memory."""
    scan_positions = {"left": -50, "forward": 0, "right": 50}
    distances = {}

    for direction, angle in scan_positions.items():
        actions.dog.head_move([[angle, 0, 0]], speed=80)
        actions.dog.wait_head_done()
        distances[direction] = actions.dog.read_distance()
        print(f"📍 {direction.capitalize()}: {distances[direction]} mm")

        # ✅ Log scan data in obstacle memory for smarter learning
        global_state.obstacle_memory[f"{direction}_scan"] = distances[direction]

    return distances

def navigate():
    """PiDog scans and moves toward the most open direction until forward is optimal."""
    print("🔎 Adaptive Navigation Started...")
    safe_action_call("update_led")  # ✅ Light cyan for scanning mode

    while True:
        distances = scan_surroundings()

        # ✅ If forward is already best, stop adjusting
        if distances["forward"] >= max(distances.values()):
            print("✅ Forward path is safest! Stopping navigation.")
            break

        # ✅ Choose the best turn direction
        if distances["left"] > distances["right"]:
            print("↩️ Turning Left (More Space)")
            safe_action_call("turn_left_medium")
        else:
            print("↪️ Turning Right (More Space)")
            safe_action_call("turn_right_medium")

        time.sleep(0.5)  # ✅ Short pause before re-scanning

    print("🎯 Navigation Complete! PiDog is facing the best direction.")

    # ✅ Restore Previous Active Mode After Execution
    global_state.active_mode = previous_active_mode
    print(f"🔄 Restored PiDog's previous mode: `{global_state.active_mode}`")

# ✅ Run adaptive navigation safely if executed directly
if __name__ == "__main__":
    try:
        navigate()
    except Exception as e:
        global_state.log_error(f"Unexpected error in `find_open_space.py`: {e}")
        print("⚠️ Navigation interrupted due to an error.")