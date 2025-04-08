#!/usr/bin/env python3
import random
import time
import importlib  # ✅ Dynamic module loading
from pidog import Pidog
from pidog.b9_rgb import RGB

# ✅ Initialize PiDog hardware
dog = Pidog()
rgb = RGB(dog)

# ✅ Load external behaviors dynamically
def load_behavior(module_name, function_name):
    """Load an external behavior module dynamically."""
    try:
        module = importlib.import_module(module_name)
        return getattr(module, function_name)
    except (ModuleNotFoundError, AttributeError):
        print(f"❌ Error: {module_name}.{function_name} not found!")
        return None

# ✅ Balance Mode Import (Fixed)
balance = load_behavior("balance", "pidog_balance")

# ✅ LED Control
def update_led(color, effect=None):
    """Updates LED effects based on action state."""
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
    """Detect obstacles and switch to scanning mode when necessary."""
    global obstacle_count
    distances = scan_surroundings()
    
    current_position = (position["x"], position["y"])

    # ✅ Update obstacle memory tracking
    if distances["forward"] < 80:
        obstacle_map[current_position] = obstacle_map.get(current_position, 0) + 1
        obstacle_count += 1
        print(f"📌 Memory Map Updated: {obstacle_map}")

    # ✅ Trigger open space search if **too many consecutive obstacles**
    if obstacle_count >= 3:
        print("🚨 Too many obstacles encountered! Switching to open space search...")
        find_open_space()
        obstacle_count = 0  # ✅ Reset obstacle counter
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

def navigate():
    """PiDog moves toward the most open direction."""
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

# ✅ General Actions
def sit():
    print("🐶 Sitting...")
    update_led((0, 0, 255), rgb.fade)
    dog.do_action("sit", speed=80)

def lay_down():
    print("🐕 Laying down...")
    update_led((0, 255, 0), rgb.breathe)
    dog.do_action("lay_down", speed=80)

def bark():
    print("🔊 Barking...")
    update_led((255, 0, 0), rgb.flash)
    dog.do_action("bark", speed=100)

def wag_tail():
    print("🐕 Wagging tail...")
    update_led((0, 0, 255), rgb.flash)
    dog.do_action("wag_tail", speed=80)

# ✅ Optimized Movement Function
def turn(direction, step_count):
    """Generalized turn function for left and right turns."""
    print(f"↩️ Turning {direction} {step_count} steps...")
    update_led((255, 255, 50), rgb.pulse)
    head_angle = -50 if direction == "left" else 50

    dog.head_move([[head_angle, 0, 0]], speed=120)  # ✅ Sync head movement
    dog.wait_head_done()
    dog.do_action(f"turn_{direction}", step_count=step_count, speed=200)
    dog.head_move([[0, 0, 0]], speed=120)  # ✅ Reset head position

# ✅ Restored Original Turn Functions (Backward Compatibility)
def turn_left_small():
    turn("left", 4)

def turn_left_medium():
    turn("left", 8)

def turn_left_big():
    turn("left", 12)

def turn_right_small():
    turn("right", 4)

def turn_right_medium():
    turn("right", 8)

def turn_right_big():
    turn("right", 12)

# ✅ Movement Functions
def forward():
    print("🚶‍♂️ Walking forward...")
    update_led((0, 255, 50), rgb.pulse)
    dog.do_action("forward", step_count=3, speed=100)

def backward():
    print("🏃‍♂️ Retreating...")
    update_led((255, 165, 0), rgb.fade)
    dog.do_action("backward", step_count=2, speed=100)

# ✅ Balance Mode
def enable_balance_mode():
    print("⚖️ Balance mode ON!")
    balance.start_balance()

def disable_balance_mode():
    print("🛑 Balance mode OFF!")
    balance.stop_balance()

# ✅ Emergency Stop
def stop_and_stand():
    print("🛑 Emergency Stop! PiDog standing...")
    disable_balance_mode()  # ✅ Ensure balance stops before standing
    dog.do_action("stand", speed=120)
    enable_balance_mode()  # ✅ Restart balance after standing

# ✅ Fun Actions
def play_dead():
    print("💀 Playing dead...")
    update_led((0, 0, 0), rgb.fade)
    dog.do_action("lay_down", speed=60)
    time.sleep(3)

def wave_paw():
    print("👋 Waving paw...")
    update_led((255, 100, 100), rgb.pulse)
    dog.do_action("tilting_head", speed=80)

# ✅ NEW ACTIONS: Jump Variations
def jump():
    """PiDog performs a simple jump while maintaining balance."""
    print("🐶 Jumping with balance mode!")

    enable_balance_mode()  # ✅ Activate balance mode before jumping
    update_led((255, 215, 0), rgb.flash)

    dog.do_action("jump", speed=120)  # ✅ Perform jump
    time.sleep(0.5)

    disable_balance_mode()  # ✅ Disable balance mode afterward
    print("🎉 Finished jumping!")

def jump_and_wag():
    """PiDog jumps while wagging its tail, maintaining balance."""
    print("🐶 Jumping and wagging tail with balance mode!")

    enable_balance_mode()  # ✅ Activate balance mode before movement
    update_led((0, 255, 100), rgb.flash)

    for _ in range(3):  # ✅ Wag tail before jumping
        dog.do_action("wag_tail", speed=100)
        time.sleep(0.3)

    dog.do_action("jump", speed=120)  # ✅ Perform jump
    time.sleep(0.5)

    dog.do_action("wag_tail", speed=100)  # ✅ Wag tail after landing
    disable_balance_mode()  # ✅ Disable balance mode afterward

    print("🎉 Finished jumping and wagging tail!")

# ✅ Load Modules Dynamically
def start_patrol():
    print("🚶‍♂️ Starting patrol mode...")
    patrol_mode = load_behavior("patrol", "start_behavior")
    if patrol_mode:
        update_led((255, 255, 0), rgb.pulse)
        patrol_mode()

def start_idle():
    print("😴 Entering idle mode...")
    idle_mode = load_behavior("idle_behavior", "start_idle_mode")
    if idle_mode:
        update_led((255, 255, 255), rgb.breathe)
        idle_mode()


def start_find_open_space():
    """Starts PiDog's adaptive navigation from find_open_space.py."""
    print("🔎 Running adaptive navigation...")

    navigation_module = importlib.import_module("find_open_space")
    navigate_function = getattr(navigation_module, "navigate", None)

    if navigate_function:
        update_led((0, 255, 255), None)  # ✅ Light cyan for scanning mode
        navigate_function()
    else:
        print("❌ Adaptive Navigation module not found!")

# ✅ Initialize PiDog Command System
print("🚀 PiDog action system ready!")