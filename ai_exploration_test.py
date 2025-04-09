#!/usr/bin/env python3
import random
import time
from pidog import Pidog

# Initialize PiDog
dog = Pidog()
dog.do_action("stand", speed=80)
dog.wait_all_done()
time.sleep(0.5)

# Position tracking variables
position = [0, 0]  # Track PiDog's location
explored_map = {}  # Mapping grid
blocked_positions = set()  # Store blocked areas

def update_position(direction):
    """Update PiDog's mapped location."""
    if direction == "forward":
        position[1] += 1
    elif direction == "backward":
        position[1] -= 1
    elif direction == "left":
        position[0] -= 1
    elif direction == "right":
        position[0] += 1

    explored_map[tuple(position)] = "visited"
    print(f"PiDog's current position: {position}")

def detect_obstacle():
    """Check for obstacles and store blocked positions."""
    distance = dog.read_distance()
    if distance < 30:
        blocked_positions.add(tuple(position))
        print(f"Blocked at position: {position}")

    return distance < 30

def explore_environment():
    """Move and scan surroundings dynamically."""
    speed = random.choice([80, 100, 120])
    print(f"Exploring at speed {speed}...")

    for _ in range(5):
        update_position("forward")

        if tuple(position) in blocked_positions:
            print("Previously blocked area detected! Changing path...")
            adjust_route()
            return
        
        dog.do_action("forward", step_count=1, speed=speed)
        dog.wait_all_done()
        time.sleep(0.2)

        if detect_obstacle():
            print("Obstacle detected! Adjusting route...")
            adjust_route()
            return

def adjust_route():
    """Modify movement based on obstacles detected."""
    turn_direction = random.choice(["left", "right"])
    print(f"Adjusting path: Turning {turn_direction}...")

    update_position(turn_direction)

    if turn_direction == "left":
        dog.do_action("turn_left", step_count=5, speed=100)
    else:
        dog.do_action("turn_right", step_count=5, speed=100)

    dog.wait_all_done()
    time.sleep(0.5)
    
    explore_environment()  # Resume exploration

# Main Exploration Loop
try:
    while True:
        explore_environment()

except KeyboardInterrupt:
    print("Exiting AI Exploration Mode...")
    dog.do_action("stand", speed=50)
    dog.wait_all_done()
    dog.close()