#!/usr/bin/env python3
import time
import random
import threading
import speech_recognition as sr  # Speech recognition library
from pidog import Pidog

# ✅ Initialize PiDog
dog = Pidog()
dog.do_action("stand", speed=120)  # Ensure PiDog is ready
dog.wait_all_done()

time.sleep(0.5)

# ✅ Define global movement speed
current_speed = 120  # Default normal speed

# ✅ Position tracking with structured mapping
position = {"x": 0, "y": 0, "blocked": set()}

# ✅ Flag to control movement
manual_mode = False

# ✅ Track obstacle detection count
obstacle_count = {}


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


def recalibrate_position():
    """Periodically recalibrate position using PiDog’s IMU."""
    imu_data = dog.gyroData  # Get motion data
    print(f"🔄 Recalibrating position using IMU: {imu_data}")

    if abs(imu_data[0]) > 5 or abs(imu_data[1]) > 5:
        position["x"] += round(imu_data[0] * 0.1)
        position["y"] += round(imu_data[1] * 0.1)
        print(f"✅ Adjusted position after recalibration: {position}")


def resume_patrol():
    """Resume autonomous patrol by clearing manual override flag."""
    global manual_mode
    manual_mode = False


def retreat():
    """Move PiDog backward after detecting an obstacle and ensure patrol resumes."""
    print("🚨 Retreating from obstacle...")
    update_position("backward")

    dog.head_move([[0, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()

    dog.do_action("backward", step_count=2, speed=120)
    dog.wait_all_done()
    time.sleep(0.5)

    print("Resuming patrol after retreat...")
    resume_patrol()


def detect_obstacle():
    """Scan forward, left, and right for obstacles & preemptively avoid them."""
    forward_distance = dog.read_distance()
    print(f"🚧 Forward obstacle distance: {forward_distance}")

    # ✅ Scan left and right
    dog.head_move([[-40, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    left_distance = dog.read_distance()
    time.sleep(0.2)

    dog.head_move([[40, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    right_distance = dog.read_distance()
    time.sleep(0.2)

    dog.head_move(
        [[0, 0, 0]], immediately=True, speed=60
    )  # ✅ Reset head to forward position
    dog.wait_head_done()

    print(f"🔎 Left distance: {left_distance}, Right distance: {right_distance}")

    # ✅ Determine best direction dynamically
    if forward_distance < 40:
        print("🚨 Obstacle ahead detected!")

        # ✅ Track obstacle detections before marking position as blocked
        current_position = tuple((position["x"], position["y"]))
        obstacle_count[current_position] = obstacle_count.get(current_position, 0) + 1

        if obstacle_count[current_position] >= 3:  # Only block after 3 detections
            position["blocked"].add(current_position)

        retreat()
        check_sides()
        return True

    elif left_distance < 35:
        print("🛑 Obstacle detected on the left! Turning right to avoid.")
        update_position("right")
        dog.do_action(
            "turn_right", step_count=3, speed=200
        )  # ✅ Turn away from obstacle
        dog.wait_all_done()

    elif right_distance < 35:
        print("🛑 Obstacle detected on the right! Turning left to avoid.")
        update_position("left")
        dog.do_action(
            "turn_left", step_count=3, speed=200
        )  # ✅ Turn away from obstacle
        dog.wait_all_done()

    return False  # ✅ Continue moving forward if no obstacle is detected


def check_sides():
    """Determine if PiDog can move left or right after retreating from an obstacle."""
    print("🔎 Checking for alternative paths...")

    left_position = (position["x"] - 1, position["y"])
    right_position = (position["x"] + 1, position["y"])

    dog.head_move([[-40, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    left_distance = dog.read_distance()
    time.sleep(0.2)

    dog.head_move([[40, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    right_distance = dog.read_distance()
    time.sleep(0.2)

    dog.head_move([[0, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()

    if left_distance > right_distance and left_position not in position["blocked"]:
        print("🔄 Turning left toward open space...")
        turn_left()
    elif right_position not in position["blocked"]:
        print("🔄 Turning right toward open space...")
        turn_right()
    else:
        print("❌ No clear path found. Retreating further...")
        retreat()


def turn_left():
    """PiDog turns left while adjusting head movement."""
    print("🔄 Turning left...")
    dog.head_move([[-30, 0, 0]], immediately=True, speed=80)
    dog.wait_head_done()

    dog.do_action("turn_left", step_count=3, speed=120)
    dog.wait_all_done()

    dog.head_move([[0, 0, 0]], immediately=True, speed=80)
    dog.wait_head_done()


def turn_right():
    """PiDog turns right while adjusting head movement."""
    print("🔄 Turning right...")
    dog.head_move([[30, 0, 0]], immediately=True, speed=80)
    dog.wait_head_done()

    dog.do_action("turn_right", step_count=3, speed=120)
    dog.wait_all_done()

    dog.head_move([[0, 0, 0]], immediately=True, speed=80)
    dog.wait_head_done()


def move_forward():
    """Move PiDog forward while checking obstacles, allowing manual override."""
    global manual_mode, current_speed

    for _ in range(5):
        if manual_mode:
            return

        detect_obstacle()
        recalibrate_position()
        update_position("forward")

        dog.do_action("forward", step_count=1, speed=current_speed)


def stop_movement():
    """Immediately stop PiDog."""
    global manual_mode
    manual_mode = True
    dog.do_action("stand", speed=80)
    dog.wait_all_done()
    time.sleep(0.5)


def listen_for_command():
    """Continuously listen for voice commands."""
    recognizer = sr.Recognizer()
    global manual_mode

    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source)
        print("Listening for commands...")

        while True:
            try:
                audio = recognizer.listen(source)
                command = recognizer.recognize_google(audio).lower()
                print(f"Detected speech: {command}")

                if command in ["resume patrol", "start patrol"]:
                    print("Resuming patrol mode...")
                    manual_mode = False

                elif command in ["come here", "come", "go forward"]:
                    print("PiDog heard you! Moving forward...")
                    dog.do_action("forward", step_count=5, speed=120)

                elif command in ["backward", "move back", "go back"]:
                    print("PiDog moving backward...")
                    dog.do_action("backward", step_count=5, speed=120)

                elif command in ["stop", "halt", "freeze", "stop moving"]:
                    stop_movement()

                elif command in ["bark", "speak"]:
                    print("PiDog barking!")
                    dog.do_action("bark", speed=100)

                elif command in ["turn left", "go left"]:
                    print("PiDog turning left!")
                    dog.do_action("turn_left", step_count=5, speed=200)

                elif command in ["turn right", "go right"]:
                    print("PiDog turning right!")
                    dog.do_action("turn_right", step_count=5, speed=200)

                elif command in ["lay down", "lie down"]:
                    print("PiDog lying down...")
                    dog.do_action("lay_down", speed=80)

                elif command in ["good dog", "great job"]:
                    print("PiDog wags its tail in excitement!")
                    dog.do_action("tail_wag", speed=50)

                elif command in ["turn around"]:
                    print("PiDog turns to face the opposite direction")
                    dog.do_action("turn_right", step_count=12, speed=200)

                elif command in ["sit", "take a seat"]:
                    print("🐾 PiDog sitting down...")
                    dog.do_action("sit", speed=50)

                else:
                    print("Unknown command. Try again.")

            except sr.UnknownValueError:
                print("Could not understand speech.")
            except sr.RequestError:
                print("Speech recognition service error.")


# Run voice command detection in a separate thread
voice_thread = threading.Thread(target=listen_for_command, daemon=True)
try:
    voice_thread.start()
except Exception as e:
    print(f"⚠️ Error starting voice command thread: {e}")

# ✅ Main loop (Autonomous patrol)
try:
    while True:
        if not manual_mode:
            move_forward()
        time.sleep(1)

except KeyboardInterrupt:
    print("🚪 Exiting PiDog patrol mode...")
    stop_movement()
    dog.close()
