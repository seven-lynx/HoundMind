#!/usr/bin/env python3
import time
import threading
import random
from pidog import Pidog
from pidog.b9_rgb import RGB  # Import LED control

# ✅ Initialize PiDog and RGB LED
dog = Pidog()
rgb = RGB(dog)
dog.do_action("stand", speed=100)
dog.wait_all_done()
time.sleep(0.5)

# ✅ Define patrol parameters
position = {"x": 0, "y": 0}
blocked_positions = set()  # Stores permanently blocked areas
direction = "forward"  # Default direction
movement_speed = 100
current_state = "patrolling"  # Default state

# ✅ Emotional LED States
EMOTIONAL_STATES = {
    "patrolling": ("🌟 Curious", (0, 255, 0), rgb.breathe),  # 🟢 Green Breathing LED
    "obstacle_detected": ("😨 Startled", (255, 0, 0), rgb.flash),  # 🔴 Red Flash Effect
    "avoiding_zone": ("🤔 Thinking", (0, 0, 255), rgb.pulse),  # 🔵 Blue Pulsing Effect
    "navigating": ("🔄 Navigating", (255, 165, 0), rgb.breathe),  # 🟠 Orange Breathing LED
}

def update_led():
    """Update LED based on PiDog’s emotional state."""
    emotion, color, effect = EMOTIONAL_STATES.get(current_state, ("😶 Neutral", (255, 255, 255), rgb.breathe))
    rgb.set_color(color)
    effect(1)  # Apply selected LED effect
    print(f"💡 LED updated: {emotion} -> {color}")

def update_position():
    """Track PiDog’s position based on movement direction."""
    step_size = 1  # Movement step size

    if direction == "forward":
        position["y"] += step_size
    elif direction == "backward":
        position["y"] -= step_size
    elif direction == "left":
        position["x"] -= step_size
    elif direction == "right":
        position["x"] += step_size

    print(f"📍 Updated Position: {position}")

def scan_surroundings():
    """Continuously scan left and right while patrolling."""
    dog.head_move([[-40, 0, 0]], immediately=True, speed=80)  # Look left
    dog.wait_head_done()
    left_distance = dog.read_distance()

    dog.head_move([[40, 0, 0]], immediately=True, speed=80)  # Look right
    dog.wait_head_done()
    right_distance = dog.read_distance()

    dog.head_move([[0, 0, 0]], immediately=True, speed=80)  # Reset head position
    forward_distance = dog.read_distance()

    print(f"🔎 Forward: {forward_distance}, Left: {left_distance}, Right: {right_distance}")
    return forward_distance, left_distance, right_distance

def detect_obstacle():
    """Detect obstacles continuously and react dynamically."""
    global direction, current_state

    forward_distance, left_distance, right_distance = scan_surroundings()

    current_position = (position["x"], position["y"])

    # ✅ Predictive Avoidance: If an area has 3+ obstacles detected, mark it as blocked
    if current_position in blocked_positions:
        print("⚠️ Predicting obstacle—changing path!")
        current_state = "avoiding_zone"
        update_led()
        direction = random.choice(["left", "right"])
        return True

    # ✅ Head-on obstacle detected, retreat and find open space
    if forward_distance < 40:
        print("🚨 Obstacle ahead! Retreating...")
        current_state = "obstacle_detected"
        update_led()
        dog.do_action("bark", speed=80)  # Bark when startled
        time.sleep(0.5)

        dog.do_action("backward", step_count=2, speed=120)  # Step backward
        dog.wait_all_done()

        # Choose open direction
        direction = "left" if left_distance > right_distance else "right"
        return True

    # ✅ Avoid obstacles detected to the left or right
    if left_distance < 35:
        print("🛑 Left obstacle detected! Turning right.")
        direction = "right"
        return True

    if right_distance < 35:
        print("🛑 Right obstacle detected! Turning left.")
        direction = "left"
        return True

    current_state = "patrolling"
    update_led()
    return False  # No obstacles detected

def patrol():
    """PiDog continuously patrols while scanning left and right."""
    global direction, movement_speed

    print("🐶 Starting Patrol Mode...")
    while True:
        obstacle_detected = detect_obstacle()

        if obstacle_detected:
            dog.do_action(f"turn_{direction}", step_count=3, speed=200)
        else:
            update_position()
            dog.do_action(direction, step_count=2, speed=movement_speed)

        dog.wait_all_done()
        time.sleep(0.5)  # Short delay between movements

# ✅ Start patrol in a separate thread
patrol_thread = threading.Thread(target=patrol, daemon=True)
patrol_thread.start()

try:
    while True:
        time.sleep(1)  # Keep the main thread alive
except KeyboardInterrupt:
    print("🔴 Stopping Patrol Mode...")
    dog.do_action("stand", speed=80)
    dog.wait_all_done()
    dog.close()