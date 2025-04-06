#!/usr/bin/env python3
import time
import random
import threading
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
obstacle_count = {}

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

def retreat():
    """Move PiDog backward after detecting an obstacle and ensure patrol resumes."""
    print("Retreating from obstacle...")
    update_position("backward")

    # Reset head to neutral before retreating
    dog.head_move([[0, 0, 0]], immediately=True, speed=60)
    dog.wait_head_done()

    # Move backward
    dog.do_action("backward", step_count=2, speed=120)
    dog.wait_all_done()
    time.sleep(0.5)

    print("Resuming patrol after retreat...")
    resume_patrol()

def resume_patrol():
    # Ensure PiDog resumes patrol after obstacle avoidance.
    global manual_mode
    manual_mode = False  # Ensure patrol mode resumes
    move_forward()

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

    dog.head_move([[0, 0, 0]], immediately=True, speed=60)  # ✅ Reset head to forward position
    dog.wait_head_done()

    print(f"🔎 Left distance: {left_distance}, Right distance: {right_distance}")

    # ✅ Determine best direction dynamically
    if forward_distance < 40:
        print("🚨 Obstacle ahead detected!")

        # ✅ **Track obstacle detections before marking position as blocked**
        current_position = tuple(position)
        obstacle_count[current_position] = obstacle_count.get(current_position, 0) + 1

        if obstacle_count[current_position] >= 3:  # ✅ Only block after 3 detections
            if current_position not in blocked_positions:
                print("🚧 Marking current position as blocked.")
                blocked_positions.add(current_position)

        retreat()
        check_sides()
        return True

    elif left_distance < 35:  
        print("🛑 Obstacle detected on the left! Turning right to avoid.")
        update_position("right")
        dog.do_action("turn_right", step_count=3, speed=200)  # ✅ Turn away from obstacle
        dog.wait_all_done()
    
    elif right_distance < 35:  
        print("🛑 Obstacle detected on the right! Turning left to avoid.")
        update_position("left")
        dog.do_action("turn_left", step_count=3, speed=200)  # ✅ Turn away from obstacle
        dog.wait_all_done()

    return False  # ✅ Continue moving forward if no obstacle is detected

def recalibrate_position():
    """Periodically recalibrate position using PiDog’s IMU."""
    imu_data = dog.gyroData  # Get motion data
    print(f"🔄 Recalibrating position using IMU: {imu_data}")

    if abs(imu_data[0]) > 5 or abs(imu_data[1]) > 5:
        position["x"] += round(imu_data[0] * 0.1)
        position["y"] += round(imu_data[1] * 0.1)
        print(f"✅ Adjusted position after recalibration: {position}")

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

def adjust_gait():
    """Modify PiDog's movement based on detected imbalance using IMU."""
    global current_speed  
    pitch, roll, yaw = dog.gyroData
    ax, ay, az = dog.accData

    if abs(pitch) > 30 or abs(roll) > 30 or abs(ax) > 3.0 or abs(ay) > 3.0:
        print("⚠️ Unstable terrain detected! Slowing PiDog down for better stability...")
        current_speed = 80  # ✅ Reduce speed dynamically

        # ✅ Lower PiDog slightly for extra balance
        current_pose['z'] -= 2
        if current_pose['z'] < 30:
            current_pose['z'] = 30
        
        # ✅ Apply roll & pitch corrections
        current_rpy['roll'] = -roll * 0.5  
        current_rpy['pitch'] = -pitch * 0.5  
    else:
        print("✅ Stable terrain detected. Restoring normal speed...")
        current_speed = 120
        current_pose['z'] = 80  
        current_rpy['roll'] = 0
        current_rpy['pitch'] = 0

def move_forward():
    # Move PiDog forward while checking obstacles.
    global manual_mode, current_speed
    speed = 120  

    update_emotion("patrolling")

    for _ in range(5):
        if manual_mode:
            return 
 
        adjust_gait()  # ✅ Dynamically modify movement based on IMU data
       
        if detect_obstacle():  
            stop_movement()
            check_sides()  
            return
        
        update_position("forward")

        if tuple(position) in blocked_positions:
            print("Detected previously blocked area! Changing direction...")
            check_sides()
            return
        
        dog.do_action("forward", step_count=1, speed=current_speed)  

def turn_left():
    """PiDog turns left while adjusting head movement."""
    print("🔄 Turning left...")
    dog.head_move([[-30, 0, 0]], immediately=True, speed=80)  # ✅ Look left before turning

    dog.do_action("turn_left", step_count=3, speed=120)  # ✅ Execute turn
    dog.wait_all_done()

    dog.head_move([[0, 0, 0]], immediately=True, speed=80)  # ✅ Reset head to neutral
    dog.wait_head_done()

def turn_right():
    """PiDog turns right while adjusting head movement."""
    print("🔄 Turning right...")
    dog.head_move([[30, 0, 0]], immediately=True, speed=80)  # ✅ Look right before turning

    dog.do_action("turn_right", step_count=3, speed=120)  # ✅ Execute turn
    dog.wait_all_done()

    dog.head_move([[0, 0, 0]], immediately=True, speed=80)  # ✅ Reset head to neutral
    dog.wait_head_done()

def stop_movement():
    """Immediately stop PiDog."""
    global manual_mode
    manual_mode = True
    dog.do_action("stand", speed=80)
    dog.wait_all_done()
    time.sleep(0.5)

def update_emotion(status):
    """Change PiDog's RGB LED colors based on events."""
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

# ✅ Continuous IMU Collision Detection
def check_collision():
    """Detect sudden changes in acceleration or tilt that indicate a collision."""
    ax, ay, az = dog.accData  # Get acceleration data from IMU
    pitch, roll, yaw = dog.gyroData  # Get rotation angles from IMU
    
    if abs(ax) > 2.5 or abs(ay) > 2.5:  # Detect sudden acceleration/deceleration
        print("🚨 Collision detected! Taking evasive action...")
        stop_movement()
        retreat()

    if abs(pitch) > 20 or abs(roll) > 20:  # Detect excessive tilt
        print("⚠️ PiDog is tilted! Possible collision or fall detected.")
        stop_movement()
        dog.do_action("stand", speed=120)  # Auto-correct posture

def imu_monitor():
    """Continuously monitor IMU for collisions while PiDog patrols."""

    while True:
        check_collision()
        time.sleep(0.2)

# ✅ Start IMU monitoring in a background thread
imu_thread = threading.Thread(target=imu_monitor, daemon=True)
imu_thread.start()

# Terminal command listener
def manual_control():
    # Listen for terminal commands to manually control PiDog.
    global manual_mode

    while True:
        command = input("Enter command ('left', 'right', 'stop', 'resume'): ").strip().lower()

        if command == "left":
            print("Manual turn left!")
            update_position("left")
            dog.do_action("turn_left", step_count=3, speed=120)
            dog.wait_all_done()

        elif command == "right":
            print("Manual turn right!")
            update_position("right")
            dog.do_action("turn_right", step_count=3, speed=120)
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
    dog.do_action("stand", speed=80)
    dog.wait_all_done()
    dog.close()