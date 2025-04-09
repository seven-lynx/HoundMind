#!/usr/bin/env python3
"""
PiDog Actions Module
==================================
This module centralizes all movement, reactions, and emotional responses, allowing 
other modules (like `smarter_patrol.py`) to execute actions efficiently.

Key Features:
✅ Centralized movement and emotional actions.
✅ Dynamically loads external behavior modules.
✅ Adjusts movements based on PiDog’s emotional state (`global_state.py`).
✅ Implements **fault tolerance** when loading modules.
✅ Verifies external module availability (`find_open_space.py`) before execution.
✅ Improved obstacle detection logic with adaptive thresholds.

7-lynx
"""

import random
import time
import importlib  # ✅ Dynamic module loading
from pidog import Pidog
from pidog.b9_rgb import RGB
import global_state  # ✅ Integrated state tracking

# ✅ Initialize PiDog hardware
dog = Pidog()
rgb = RGB(dog)

# ✅ Define global tracking variables
position = global_state.position_tracker  # ✅ Sync PiDog's movement tracking globally
obstacle_count = 0  # ✅ Track consecutive obstacle encounters across states

# ✅ Load external behaviors dynamically
def load_behavior(module_name, function_name):
    """Load an external behavior module dynamically with error handling."""
    try:
        module = importlib.import_module(module_name)
        return getattr(module, function_name)
    except (ModuleNotFoundError, AttributeError):
        print(f"❌ Error: {module_name}.{function_name} not found! Selecting fallback action...")
        return fallback_action  # ✅ Select fallback if module isn't found

# ✅ LED Control
def update_led(color, effect=None):
    """Updates LED effects based on PiDog's action state."""
    rgb.set_color(color)
    if effect:
        effect(1)

# ✅ Scanning and Navigation
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

def detect_obstacle():
    """Detect obstacles and adjust PiDog’s movement dynamically."""
    global obstacle_count
    distances = scan_surroundings()
    current_position = (position["x"], position["y"])

    # ✅ Update obstacle memory tracking
    if distances["forward"] < 80:
        global_state.obstacle_memory[current_position] = global_state.obstacle_memory.get(current_position, 0) + 1
        obstacle_count += 1
        print(f"📌 Memory Map Updated: {global_state.obstacle_memory}")

    # ✅ Trigger open space search if **too many consecutive obstacles**
    if obstacle_count >= 3:
        print("🚨 Too many obstacles encountered! Switching to open space search...")
        start_find_open_space()
        obstacle_count = 0  # ✅ Reset obstacle counter
        return True

    # ✅ Preemptive turning if obstacle is **close but not blocking**
    if 40 < distances["forward"] < 80:
        print("⚠️ Obstacle detected ahead, maneuvering...")
        direction = "left" if distances["left"] > distances["right"] else "right"
        turn_with_head(direction)
        return True

    # ✅ Retreat if obstacle is **too close**
    if distances["forward"] < 40:
        print("🚨 Immediate obstacle detected! Retreating...")
        dog.do_action("bark", speed=80)
        time.sleep(0.5)

        dog.do_action("backward", step_count=2, speed=global_state.speed)
        dog.wait_all_done()

        direction = "left" if distances["left"] > distances["right"] else "right"
        turn_with_head(direction)
        return True

    return False

# ✅ Movement Functions
def turn(direction, step_count):
    """Generalized turn function for left and right turns."""
    print(f"↩️ Turning {direction} {step_count} steps...")
    update_led((255, 255, 50), rgb.pulse)
    head_angle = -50 if direction == "left" else 50

    dog.head_move([[head_angle, 0, 0]], speed=120)  # ✅ Sync head movement
    dog.wait_head_done()
    dog.do_action(f"turn_{direction}", step_count=step_count, speed=200)
    dog.head_move([[0, 0, 0]], speed=120)  # ✅ Reset head position

# ✅ Verified External Module Availability
def start_find_open_space():
    """Starts PiDog's adaptive navigation only if module exists."""
    if importlib.util.find_spec("find_open_space"):
        print("🔎 Running adaptive navigation...")
        navigation_module = importlib.import_module("find_open_space")
        navigate_function = getattr(navigation_module, "navigate", None)

        if navigate_function:
            update_led((0, 255, 255), None)
            navigate_function()
        else:
            print("❌ Adaptive Navigation function missing!")
    else:
        print("❌ `find_open_space.py` module not found!")

# ✅ Emotion-Driven Action Selection
def express_emotion():
    """Adjust actions based on PiDog’s emotion state."""
    emotion = global_state.emotion  # ✅ Retrieve current emotion state
    
    emotion_actions = {
        "happy": wag_tail,
        "sad": lay_down,
        "excited": jump_and_wag,
        "confused": tilting_head,
        "scared": bark,
        "sleepy": stop_and_stand,
        "playful": chase_tail,
        "alarmed": bark,
        "neutral": stop_and_stand,
    }

    print(f"🐶 Expressing emotion: {emotion}")
    action_function = emotion_actions.get(emotion, stop_and_stand)  # ✅ Default fallback: stop_and_stand
    action_function()

# ✅ Fallback Action
def fallback_action():
    """Defines a safe fallback behavior when a module fails to load."""
    print("⚠️ Unable to load requested module! Performing neutral behavior instead.")
    stop_and_stand()  # ✅ Default action when module fails

# ✅ Initialize PiDog Command System
print("🚀 PiDog action system ready!")