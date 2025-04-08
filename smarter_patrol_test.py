#!/usr/bin/env python3
import time
import threading
import keyboard
from pidog import Pidog
from action import find_open_space  # ✅ Import adaptive navigation

# ✅ Define global variables
dog = Pidog()
position = {"x": 0, "y": 0, "direction": 0}  # ✅ Expanded mapping includes direction
obstacle_map = {}  # ✅ Stores past obstacles with memory decay
obstacle_count = 0  # ✅ Track consecutive obstacle encounters

# ✅ Define speed profiles
speed_profiles = {
    "walking": {"walk_speed": 80, "turn_speed": 120},
    "trotting": {"walk_speed": 120, "turn_speed": 200},
    "running": {"walk_speed": 200, "turn_speed": 220}
}

current_profile = "trotting"
current_speed = speed_profiles[current_profile]

def update_position(direction):
    """Track PiDog’s position and directional facing in the mapped space."""
    step_size = 1

    if direction == "forward":
        position["y"] += step_size
        position["direction"] = 0
    elif direction == "backward":
        position["y"] -= step_size
        position["direction"] = 180
    elif direction == "left":
        position["x"] -= step_size
        position["direction"] = -90
    elif direction == "right":
        position["x"] += step_size
        position["direction"] = 90

    print(f"📍 Updated Position: {position}")

def scan_surroundings():
    """Scan forward, left, and right while recording previous scan data."""
    distances = {
        "left": dog.read_distance_at(-50),
        "forward": dog.read_distance_at(0),
        "right": dog.read_distance_at(50)
    }
    print(f"🔎 Scanned Distances: {distances}")
    return distances

def decay_obstacle_memory():
    """Reduces memory weight of old obstacles over time."""
    decay_rate = 0.2  # ✅ Adjust obstacle weight over time
    for key in list(obstacle_map.keys()):
        obstacle_map[key] -= decay_rate
        if obstacle_map[key] <= 0:
            del obstacle_map[key]  # ✅ Remove fully decayed obstacles
    print(f"📌 Decayed Obstacle Map: {obstacle_map}")

def detect_obstacle():
    """Detect obstacles, track memory decay, and intelligently adjust movement."""
    global obstacle_count
    distances = scan_surroundings()
    
    current_position = (position["x"], position["y"])

    # ✅ Apply memory decay to obstacles
    decay_obstacle_memory()

    # ✅ Store detected obstacles with memory tracking
    if distances["forward"] < 80:
        obstacle_map[current_position] = obstacle_map.get(current_position, 0) + 1
        obstacle_count += 1
        print(f"📌 Updated Obstacle Memory: {obstacle_map}")

    # ✅ Switch to open space search if **too many consecutive obstacles**
    if obstacle_count >= 3:
        print("🚨 Too many obstacles encountered! Switching to open space search...")
        find_open_space()
        obstacle_count = 0  # ✅ Reset counter
        return True

    # ✅ Use past scans to predict safest turn direction
    past_obstacles = {k: v for k, v in obstacle_map.items() if v > 1}  # ✅ Prioritize frequently blocked areas
    if past_obstacles:
        print("🧠 Using past obstacle data for turn prediction.")
        direction = "left" if distances["left"] > distances["right"] else "right"
        if (position["x"] - 1, position["y"]) in past_obstacles:
            direction = "right"
        elif (position["x"] + 1, position["y"]) in past_obstacles:
            direction = "left"
        turn_with_head(direction)
        return True

    # ✅ Preemptive turning if obstacle is **close but not blocking**
    if distances["forward"] < 80 and distances["forward"] > 40:
        print("⚠️ Obstacle detected ahead, but still maneuverable.")
        direction = "left" if distances["left"] > distances["right"] else "right"
        turn_with_head(direction)
        return True

    # ✅ Retreat if obstacle is **too close**
    if distances["forward"] < 40:
        print("🚨 Immediate obstacle detected! Retreating...")
        dog.do_action("bark", speed=80)
        time.sleep(0.5)

        dog.do_action("backward", step_count=2, speed=current_speed["walk_speed"])
        dog.wait_all_done()

        direction = "left" if distances["left"] > distances["right"] else "right"
        turn_with_head(direction)
        return True

    return False

def turn_with_head(direction):
    """Synchronize PiDog’s head movement with turns."""
    dog.head_move([[ -50 if direction == "left" else 50, 0, 0]], speed=current_speed["walk_speed"])
    dog.wait_head_done()
    dog.do_action(f"turn_{direction}", step_count=3, speed=current_speed["turn_speed"])
    dog.head_move([[0, 0, 0]], speed=current_speed["walk_speed"])
    dog.wait_head_done()

def monitor_keyboard():
    """Cycle through speed profiles with keyboard input."""
    while True:
        if keyboard.is_pressed('space'):
            profiles = list(speed_profiles.keys())
            current_index = profiles.index(current_profile)
            new_index = (current_index + 1) % len(profiles)
            global current_profile, current_speed
            current_profile = profiles[new_index]
            current_speed = speed_profiles[current_profile]
            print(f"⚡ Speed Profile Changed: {current_profile}")
            time.sleep(1)

def start_behavior():
    """PiDog continuously patrols while dynamically adjusting movement based on obstacles."""
    print(f"🐶 Patrol Mode Activated! Default Speed: {current_profile}")
    threading.Thread(target=monitor_keyboard, daemon=True).start()

    while True:
        obstacle_detected = detect_obstacle()

        if not obstacle_detected:
            update_position("forward")
            dog.do_action("forward", step_count=2, speed=current_speed["walk_speed"])

        dog.wait_all_done()
        time.sleep(0.5)

    print("🚪 Exiting Patrol Mode!")
    dog.close()