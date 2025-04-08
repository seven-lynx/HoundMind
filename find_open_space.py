#!/usr/bin/env python3
import time
from action import turn_left_medium, turn_right_medium, update_led, dog

def scan_surroundings():
    """Scan forward, left, and right distances."""
    scan_positions = {"left": -50, "forward": 0, "right": 50}
    distances = {}

    for direction, angle in scan_positions.items():
        dog.head_move([[angle, 0, 0]], speed=80)
        dog.wait_head_done()
        distances[direction] = dog.read_distance()
        print(f"📍 {direction.capitalize()}: {distances[direction]} mm")

    return distances

def navigate():
    """PiDog scans and moves toward the most open direction until forward is best."""
    print("🔎 Adaptive Navigation Started...")
    update_led((0, 255, 255), None)  # ✅ Light cyan for scanning mode

    while True:
        distances = scan_surroundings()

        # ✅ If forward has the longest distance, stop adjusting
        if distances["forward"] >= distances["left"] and distances["forward"] >= distances["right"]:
            print("✅ Forward path is now safest! Stopping navigation.")
            break

        # ✅ Choose the best turn direction
        if distances["left"] > distances["right"]:
            print("↩️ Turning Left (More Space)")
            turn_left_medium()
        else:
            print("↪️ Turning Right (More Space)")
            turn_right_medium()

        time.sleep(0.5)  # ✅ Short pause before re-scanning

    print("🎯 Navigation Complete! PiDog is facing the best direction.")

# ✅ Run adaptive navigation if executed directly
if __name__ == "__main__":
    navigate()