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
blocked_positions = set()

# ✅ Flag to control movement
manual_mode = False

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

def retreat():
    """Move PiDog backward after detecting an obstacle and ensure patrol resumes."""
    print("Retreating from obstacle...")
    update_position("backward")

    dog.head_move([[0, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()

    dog.do_action("backward", step_count=2, speed=120)
    dog.wait_all_done()
    time.sleep(0.5)

    print("Resuming patrol after retreat...")
    resume_patrol()

def check_sides():
    """PiDog dynamically selects the safest path, avoiding previously blocked areas."""
    print("Checking for side paths after retreating...")
    update_emotion("avoiding")

    dog.head_move([[-40, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    left_distance = dog.read_distance()
    time.sleep(0.2)

    dog.head_move([[40, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    right_distance = dog.read_distance()
    time.sleep(0.2)

    dog.head_move([[0, 0, 0]], immediately=True, speed=60)  # ✅ Reset head position
    dog.wait_head_done()

    print(f"Left distance: {left_distance}, Right distance: {right_distance}")

    left_position = (position[0] - 1, position[1])
    right_position = (position[0] + 1, position[1])

    if left_distance > right_distance and left_position not in blocked_positions:
        print("Turning left toward open space...")
        update_position("left")
        dog.do_action("turn_left", step_count=3, speed=200)
    elif right_position not in blocked_positions:
        print("Turning right toward open space...")
        update_position("right")
        dog.do_action("turn_right", step_count=3, speed=200)
    else:
        print("Both sides blocked. Retreating further...")
        retreat()

    dog.wait_all_done()
    resume_patrol()

def resume_patrol():
    """Ensure PiDog resumes patrol after obstacle avoidance."""
    global manual_mode
    manual_mode = False  # ✅ Resume patrol mode
    move_forward()

def detect_obstacle():
    """Scan forward, left, and right for obstacles & preemptively avoid them."""
    forward_distance = dog.read_distance()
    print(f"🚧 Forward obstacle distance: {forward_distance}")

    dog.head_move([[-40, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    left_distance = dog.read_distance()
    time.sleep(0.2)

    dog.head_move([[40, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()
    right_distance = dog.read_distance()
    time.sleep(0.2)

    dog.head_move([[0, 0, 0]], immediately=True, speed=60)  # ✅ Reset head to forward position
    dog.wait_head_done()

    print(f"🔎 Left distance: {left_distance}, Right distance: {right_distance}")

    if forward_distance < 40:
        print("🚨 Obstacle ahead detected!")

        current_position = tuple(position)
        obstacle_count[current_position] = obstacle_count.get(current_position, 0) + 1

        if obstacle_count[current_position] >= 3:
            if current_position not in blocked_positions:
                print("🚧 Marking current position as blocked.")
                blocked_positions.add(current_position)

        retreat()
        check_sides()
        return True

    elif left_distance < 35:  
        print("🛑 Obstacle detected on the left! Turning right to avoid.")
        turn_right()
    
    elif right_distance < 35:  
        print("🛑 Obstacle detected on the right! Turning left to avoid.")
        turn_left()

    return False

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

def adjust_gait():
    """Modify PiDog's movement based on detected imbalance using IMU."""
    global current_speed  

    imu_data = dog.gyroData  
    acceleration = dog.accData  

    if imu_data is None or acceleration is None:
        print("⚠️ IMU data unavailable, maintaining current speed.")
        return

    pitch, roll, yaw = imu_data
    ax, ay, az = acceleration

    # ✅ Detect imbalance based on pitch, roll, and sudden acceleration changes
    if abs(pitch) > 30 or abs(roll) > 30 or abs(ax) > 3.0 or abs(ay) > 3.0:
        print("⚠️ Unstable terrain detected! Adjusting PiDog's stability...")

        # ✅ Gradually decrease speed when instability is detected
        current_speed = max(current_speed - 20, 60)  

        # ✅ Adjust balance dynamically
        correction_factor = 0.5  # Fine-tune corrective adjustments
        balanced_pitch = -pitch * correction_factor  
        balanced_roll = -roll * correction_factor  

        # ✅ Apply corrections
        dog.set_rpy(roll=balanced_roll, pitch=balanced_pitch, yaw=0, pid=True)

    else:
        print("✅ Stable terrain detected. Restoring normal speed...")
        current_speed = min(current_speed + 20, 120)  # ✅ Smooth speed transition back to normal
        dog.set_rpy(roll=0, pitch=0, yaw=0, pid=True)  # ✅ Reset corrections

    print(f"Current speed: {current_speed}, Roll correction: {balanced_roll}, Pitch correction: {balanced_pitch}")

def move_forward():
    """Move PiDog forward while checking obstacles, allowing manual override."""
    global manual_mode, current_speed  

    update_emotion("patrolling")

    for _ in range(5):
        if manual_mode:
            return 
        
        adjust_gait()

        if detect_obstacle():  
            stop_movement()
            check_sides()  
            return

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

    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source)
        print("Listening for commands...")

        while True:
            try:
                audio = recognizer.listen(source)  # Remove timeout for continuous listening
                command = recognizer.recognize_google(audio).lower()
                print(f"Detected speech: {command}")
                process_command(command)  # Execute detected command
                    
            except sr.UnknownValueError:
                print("Could not understand speech.")
            except sr.RequestError:
                print("Speech recognition service error.")

def process_command(command):
    """Interpret and execute voice commands"""
    if not command:
        return

    if command in ["come here", "come", "go forward"]:
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

    else:
        print("Unknown command. Try again.")

# ✅ Start voice command detection in a separate thread
voice_thread = threading.Thread(target=listen_for_command, daemon=True)
voice_thread.start()

# ✅ Main loop (Always patrolling unless interrupted)
try:
    while True:
        if manual_mode:
            time.sleep(0.5)  # ✅ Pauses only when a voice command interrupts patrol
        else:
            move_forward()  # ✅ Patrol never stops unless overridden
            time.sleep(0.5)  # ✅ Allows periodic adjustments

except KeyboardInterrupt:
    print("🚪 Exiting PiDog patrol mode...")
    stop_movement()  
    dog.close()  