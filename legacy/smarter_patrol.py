#!/usr/bin/env python3
import time
import random
import threading
from pidog import Pidog

# Initialize PiDog
dog = Pidog()
dog.do_action("stand", speed=120)  # Ensure PiDog is ready
dog.wait_all_done()
time.sleep(0.5)

# Position tracking variables
position = {"x": 0, "y": 0}
blocked_positions = set()

# Flag to control movement
manual_mode = False

# ✅ Define global movement speed
current_speed = 120  # Default normal speed


def recalibrate_position():
    """Periodically recalibrate position using PiDog’s IMU."""
    imu_data = dog.gyroData  # Get motion data
    print(f"🔄 Recalibrating position using IMU: {imu_data}")

    if abs(imu_data[0]) > 5 or abs(imu_data[1]) > 5:
        position["x"] += round(imu_data[0] * 0.1)
        position["y"] += round(imu_data[1] * 0.1)
        print(f"✅ Adjusted position after recalibration: {position}")


def update_position(direction):
    """Update PiDog’s exact coordinates based on movement direction."""
    step_size = 1  # Adjust step size based on PiDog's movement range

    if direction == "forward":
        position["y"] += step_size
    elif direction == "backward":
        position["y"] -= step_size
    elif direction == "left":
        position["x"] -= step_size
    elif direction == "right":
        position["x"] += step_size

    print(f"📍 PiDog’s current position: {position['x']}, {position['y']}")


def detect_obstacle():
    """Check for obstacles directly ahead with updated threshold."""
    forward_distance = dog.read_distance()
    print(f"Forward obstacle distance: {forward_distance}")

    if forward_distance < 40:
        blocked_positions.add(tuple(position))
        update_emotion("blocked")

        print("Obstacle detected! Retreating first before finding new route...")
        retreat()
        check_sides()
        return True

    return False


def patrol_head_movement():
    # Move PiDog's head side to side slowly, reset forward, then scan forward for obstacles.
    update_emotion("scanning")

    # Side-to-side head movement for patrol effect
    dog.head_move([[30, 0, 0]], immediately=True, speed=30)  # Look right
    dog.wait_head_done()
    time.sleep(0.3)

    dog.head_move([[-30, 0, 0]], immediately=True, speed=30)  # Look left
    dog.wait_head_done()
    time.sleep(0.3)

    # Reset head to FORWARD before obstacle scanning
    dog.head_move([[0, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()


def check_sides():
    # PiDog dynamically turns toward the most open area.
    print("Obstacle detected ahead! Checking for side paths...")
    update_emotion("avoiding")

    # Scan left and measure distance
    dog.head_move([[-30, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    left_distance = dog.read_distance()
    print(f"Left obstacle distance: {left_distance}")
    time.sleep(0.2)

    # Scan right and measure distance
    dog.head_move([[30, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    right_distance = dog.read_distance()
    print(f"Right obstacle distance: {right_distance}")
    time.sleep(0.2)

    # Reset head position after scanning
    dog.head_move([[0, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()

    print(f"Left distance: {left_distance}, Right distance: {right_distance}")

    # Determine best direction based on measurements
    if left_distance > right_distance:
        print("Turning toward the left (more open space)...")
        update_position("left")
        dog.do_action("turn_left", step_count=3, speed=200)  # Faster reaction
    else:
        print("Turning toward the right (more open space)...")
        update_position("right")
        dog.do_action("turn_right", step_count=3, speed=200)  # Faster reaction

    dog.wait_all_done()
    resume_patrol()  # Ensure patrol resumes


def retreat():
    # Move PiDog backward after detecting an obstacle and ensure patrol resumes.
    print("No sidestep available! Retreating...")
    update_position("backward")

    # Reset head to neutral before retreating
    dog.head_move([[0, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()

    # Move backward while maintaining speed
    dog.do_action("backward", step_count=2, speed=120)
    dog.wait_all_done()
    time.sleep(0.5)

    print("Resuming patrol after retreat...")
    resume_patrol()


def resume_patrol():
    # Ensure PiDog resumes forward movement after obstacle avoidance.
    global manual_mode
    manual_mode = False  # Ensure patrol mode resumes
    move_forward()


def move_forward():
    # Move PiDog forward while checking obstacles.
    global manual_mode
    speed = 120

    update_emotion("patrolling")

    for _ in range(5):
        if manual_mode:
            return

        patrol_head_movement()

        if detect_obstacle():
            stop_movement()
            check_sides()
            return

        update_position("forward")

        if tuple(position) in blocked_positions:
            print("Detected previously blocked area! Changing direction...")
            check_sides()
            return

        dog.do_action("forward", step_count=1, speed=speed)
        dog.wait_all_done()
        time.sleep(0.2)


def stop_movement():
    # Immediately stop PiDog.
    global manual_mode
    manual_mode = True
    dog.do_action("stand", speed=120)
    dog.wait_all_done()
    time.sleep(0.5)


def update_emotion(status):
    # Change PiDog's RGB LED colors based on events.
    if status == "patrolling":
        dog.rgb_strip.set_mode(style="breath", color="green", brightness=1)
        print("PiDog is happily patrolling!")

    elif status == "scanning":
        dog.rgb_strip.set_mode(style="breath", color="blue", brightness=1)
        print("PiDog is scanning for obstacles...")

    elif status == "blocked":
        dog.rgb_strip.set_mode(style="boom", color="red", brightness=1)
        print("PiDog detected an obstacle and stopped!")

    elif status == "avoiding":
        dog.rgb_strip.set_mode(style="bark", color="yellow", brightness=1)
        print("PiDog is changing its path!")

    dog.wait_all_done()


# Terminal command listener
def manual_control():
    # Listen for terminal commands to manually control PiDog.
    global manual_mode

    while True:
        command = (
            input("Enter command ('left', 'right', 'stop', 'resume'): ").strip().lower()
        )

        if command == "left":
            print("Manual turn left!")
            update_position("left")
            dog.do_action("turn_left", step_count=5, speed=200)
            dog.wait_all_done()

        elif command == "right":
            print("Manual turn right!")
            update_position("right")
            dog.do_action("turn_right", step_count=5, speed=200)
            dog.wait_all_done()

        elif command == "stop":
            print("Stopping PiDog!")
            stop_movement()

        elif command == "resume":
            print("Resuming autonomous patrol mode!")
            resume_patrol()

        else:
            print("Invalid command. Use 'left', 'right', 'stop', or 'resume'.")


# Run manual control in a separate thread
control_thread = threading.Thread(target=manual_control, daemon=True)
control_thread.start()

# Main loop (Autonomous patrol)
try:
    while True:
        if not manual_mode:
            move_forward()

except KeyboardInterrupt:
    print("Stopping PiDog...")
    dog.do_action("stand", speed=120)
    dog.wait_all_done()
    dog.close()
