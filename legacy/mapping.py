#!/usr/bin/env python3
import random
import time
from pidog import Pidog

# Initialize PiDog
dog = Pidog()
dog.do_action("stand", speed=80)  # Ensure PiDog is ready
dog.wait_all_done()
time.sleep(0.5)

# ✅ Position tracking variables
position = [0, 0]  # Track PiDog's location
blocked_positions = set()  # Store blocked areas
mapped_area = {}  # Home mapping grid


def update_position(direction):
    """Adjust PiDog's coordinates based on movement."""
    if direction == "forward":
        position[1] += 1
    elif direction == "backward":
        position[1] -= 1
    elif direction == "left":
        position[0] -= 1
    elif direction == "right":
        position[0] += 1

    # ✅ Mark the area as explored
    mapped_area[tuple(position)] = "visited"
    print(f"PiDog's current position: {position}")


def detect_obstacle():
    """Check for obstacles and store blocked positions."""
    distance = dog.read_distance()
    if distance < 30:
        blocked_positions.add(tuple(position))
        print(f"Blocked at position: {position}")

    return distance < 30


def move_forward():
    """Move PiDog forward and track mapping data."""
    speed = random.choice([80, 100, 120])
    print(f"Moving forward at speed {speed}...")

    for _ in range(5):
        update_position("forward")

        if tuple(position) in blocked_positions:
            print("Previously blocked area detected! Changing direction...")
            respond_to_obstacle()
            return

        dog.do_action("forward", step_count=1, speed=speed)
        dog.wait_all_done()
        time.sleep(0.2)

        if detect_obstacle():
            print("Obstacle detected mid-movement! Stopping immediately...")
            stop_movement()
            respond_to_obstacle()
            return


def stop_movement():
    """Immediately stop PiDog to prevent collisions."""
    print("Stopping immediately!")
    dog.do_action("stand", speed=80)
    dog.wait_all_done()
    time.sleep(0.5)


def retreat():
    """Move PiDog backward when an obstacle is detected."""
    print("Executing Retreat: Moving backward 2 steps...")
    update_position("backward")
    dog.do_action("backward", step_count=2, speed=100)
    dog.wait_all_done()
    time.sleep(0.5)

    navigate_around_obstacle()


def navigate_around_obstacle():
    """Turn and adjust movement while updating the map."""
    turn_direction = random.choice(["left", "right"])
    print(f"Turning {turn_direction} to avoid obstacle...")

    update_position(turn_direction)

    if turn_direction == "left":
        dog.do_action("turn_left", step_count=5, speed=100)
    else:
        dog.do_action("turn_right", step_count=5, speed=100)

    dog.wait_all_done()
    time.sleep(0.5)

    print("Resuming mapped movement...")
    dog.do_action("forward", step_count=5, speed=100)
    dog.wait_all_done()


def respond_to_obstacle():
    """Choose either retreat or navigate around obstacle."""
    action = random.choice(["retreat", "navigate"])

    if action == "retreat":
        retreat()
    else:
        navigate_around_obstacle()


def return_to_start():
    """Guide PiDog back to its starting position."""
    print("Returning to home base...")

    while position != [0, 0]:
        if position[0] > 0:
            update_position("left")
            dog.do_action("turn_left", step_count=5, speed=100)
        elif position[0] < 0:
            update_position("right")
            dog.do_action("turn_right", step_count=5, speed=100)
        elif position[1] > 0:
            update_position("backward")
            dog.do_action("backward", step_count=5, speed=100)

        dog.wait_all_done()
        time.sleep(0.5)

    print("PiDog has returned home!")


# Main Mapping Mode
try:
    while True:
        move_forward()

        # Occasionally scan and map surrounding area
        if random.random() < 0.2:
            print("Scanning new area...")
            navigate_around_obstacle()

except KeyboardInterrupt:
    print("Returning to start position...")
    return_to_start()
    dog.do_action("stand", speed=50)
    dog.wait_all_done()
    dog.close()
