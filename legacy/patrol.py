#!/usr/bin/env python3
import random
import time
from pidog import Pidog

# Initialize Pidog
t = time.time()
dog = Pidog()
dog.do_action("stand", speed=80)  # Ensure Pidog is ready
dog.wait_all_done()
time.sleep(0.5)


def move_forward():
    """Move Pidog forward with obstacle detection & randomized speed."""
    speed = random.choice([80, 100, 120])  # ✅ Random speed variation
    print(f"Moving forward at speed {speed}...")

    for _ in range(5):  # Move forward step-by-step
        dog.do_action("forward", step_count=1, speed=speed)  # Adjusted speed
        dog.wait_all_done()
        time.sleep(0.2)

        # ✅ Check for obstacles EVERY SINGLE STEP
        if detect_obstacle():
            print("Obstacle detected mid-movement! Stopping immediately...")
            stop_movement()  # Emergency stop
            respond_to_obstacle()  # Choose an avoidance method randomly
            return  # Exit movement immediately to handle obstacle

    # ✅ Occasionally perform an idle behavior after moving forward
    if random.random() < 0.3:  # 30% chance to do idle behavior
        perform_idle_behavior()


def stop_movement():
    """Immediately stop Pidog to prevent collisions."""
    print("Stopping immediately!")
    dog.do_action("stand", speed=80)  # Stop all movement
    dog.wait_all_done()
    time.sleep(0.5)


def detect_obstacle():
    """Check for obstacles using the ultrasonic sensor."""
    distance = dog.read_distance()  # Correct method call
    print(f"Distance detected: {distance} cm")  # Debugging output
    return distance < 60  # Increased detection range for earlier reaction


def retreat():
    """Move Pidog backward when an obstacle is detected."""
    print("Executing Retreat: Moving backward 2 steps at speed 100...")
    dog.do_action("backward", step_count=2, speed=100)  # Moves backward at steady speed
    dog.wait_all_done()
    time.sleep(0.5)

    navigate_around_obstacle()  # Turn after retreating


def reverse_turn():
    """Move backward while turning in a random direction."""
    print("Executing Reverse Turn: Moving backward while turning...")

    turn_direction = random.choice(["left", "right"])
    print(f"Reverse turning {turn_direction}")  # Debugging output

    if turn_direction == "left":
        dog.do_action(
            "backward_left", step_count=5, speed=100
        )  # Moves backward while turning left
    else:
        dog.do_action(
            "backward_right", step_count=5, speed=100
        )  # Moves backward while turning right

    dog.wait_all_done()
    time.sleep(0.5)


def respond_to_obstacle():
    """Randomly choose between retreating or reverse turning when an obstacle is detected."""
    action = random.choice(
        ["retreat", "reverse_turn"]
    )  # Randomly selects avoidance method

    if action == "retreat":
        retreat()  # Executes retreat behavior
    else:
        reverse_turn()  # Executes reverse turn behavior


def navigate_around_obstacle():
    """Turn left or right randomly, then fully reset movement before continuing."""
    turn_direction = random.choice(["left", "right"])
    turn_style = random.choice(["sharp", "smooth"])

    print(f"Turning {turn_direction}, Style: {turn_style}")  # Debugging output

    if turn_direction == "left":
        if turn_style == "sharp":
            dog.do_action("turn_left", step_count=10, speed=100)  # Increased turn speed
        else:
            dog.do_action("turn_left", step_count=5, speed=100)  # Increased turn speed
    else:
        if turn_style == "sharp":
            dog.do_action(
                "turn_right", step_count=10, speed=100
            )  # Increased turn speed
        else:
            dog.do_action("turn_right", step_count=5, speed=100)  # Increased turn speed

    dog.wait_all_done()
    time.sleep(0.5)

    # ✅ Reset movement state before moving forward again
    print("Resetting PiDog before moving forward...")
    dog.do_action("stand", speed=80)  # Stand first to clear movement state
    dog.wait_all_done()
    time.sleep(0.5)

    # ✅ Explicitly restart forward movement at speed 100
    print("Resuming forward movement at speed 100...")
    dog.do_action("forward", step_count=5, speed=100)  # Reset movement speed properly
    dog.wait_all_done()


def perform_idle_behavior():
    """Make PiDog do idle animations to simulate natural behavior."""
    idle_action = random.choice(["head_tilt", "tail_wag", "bark"])

    if idle_action == "head_tilt":
        print("PiDog tilts its head curiously...")
        dog.do_action("head_tilt", speed=50)
    elif idle_action == "tail_wag":
        print("PiDog wags its tail playfully...")
        dog.do_action("tail_wag", speed=50)
    else:
        print("PiDog makes a playful bark sound!")
        dog.do_action("bark", speed=50)

    dog.wait_all_done()
    time.sleep(0.5)


def scan_area():
    """Make PiDog scan its surroundings before resuming patrol."""
    print("Scanning the area before continuing...")

    dog.do_action("turn_left", step_count=5, speed=80)  # Looks left
    dog.wait_all_done()
    time.sleep(0.5)

    dog.do_action("turn_right", step_count=5, speed=80)  # Looks right
    dog.wait_all_done()
    time.sleep(0.5)


# Main loop
try:
    while True:
        move_forward()

        # ✅ Occasionally scan the area before continuing patrol
        if random.random() < 0.2:  # 20% chance to perform an area scan
            scan_area()

except KeyboardInterrupt:
    print("Stopping Pidog...")
    dog.do_action("stand", speed=50)  # Stop movement safely
    dog.wait_all_done()
    dog.close()  # Shut down Pidog properly
