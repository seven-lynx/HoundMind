# Complete PiDog Programming Guide

> **The definitive beginner-friendly guide to programming the SunFounder PiDog robotic dog with Python**

- Last updated: 2025-10-22
- Target audience: **Complete beginners to advanced programmers**
- Prerequisites: **No prior robotics experience required!** Basic Python helpful but not essential
- Hardware: SunFounder PiDog robotic dog (fully assembled)

## 🎓 **For Complete Beginners**

**Never programmed a robot before? No problem!** This guide is designed to teach you step-by-step:

- 🤖 **What is the PiDog?** - A friendly robotic dog you can control with Python code
- 💡 **How does it work?** - Your Python code sends commands to motors (servos) and reads sensors
- 📝 **What will you learn?** - How to make your PiDog walk, react to touch, avoid obstacles, and more
- 🛡️ **Safety first** - We'll show you how to write safe code that won't harm your robot

**Key Concepts Explained:**
- **Servo motors** = The "muscles" that move the PiDog's legs, head, and tail
- **Sensors** = The "senses" that let PiDog see, hear, and feel its environment  
- **Python code** = The "brain" that tells PiDog how to behave
- **APIs** = Pre-written commands that make controlling PiDog easy

---

## 📋 Table of Contents

- [Quick Start Resources](#quick-start-resources)
- [1. PiDog Class: Core Architecture](#1-pidog-class-core-architecture)
- [2. Motion Control: Complete Movement API](#2-motion-control-complete-movement-api)
- [3. Sensor Integration](#3-sensor-integration)
- [4. Audio System](#4-audio-system)
- [5. RGB LED Control](#5-rgb-led-control)
- [6. Advanced Control Patterns](#6-advanced-control-patterns)
- [7. Error Handling and Safety](#7-error-handling-and-safety)
- [8. Complete Debugging and Monitoring](#8-complete-debugging-and-monitoring)
- [9. Project Templates and Patterns](#9-project-templates-and-patterns)
- [Additional Resources](#additional-resources)

---

## Quick Start Resources

> **🚀 New to PiDog programming?** These resources get you coding quickly:

- **[`pidog_programming_examples.py`](./pidog_programming_examples.py)** - Runnable examples for every feature with menu system
- **[`api_reference_enhanced.md`](./api_reference_enhanced.md)** - Complete method documentation with all parameters
- **[`advanced_pidog_ai.py`](./advanced_pidog_ai.py)** - Advanced AI behavior system demonstration

---

## 1. 🤖 PiDog Class: Your Robot's "Brain" (For Beginners)

**What is the PiDog class?** Think of it as the "remote control app" for your robotic dog. Just like how you use an app to control a smart TV, the PiDog class lets you control your robot from Python code.

### Simple Initialization (Start Here!)

```python
# STEP 1: Tell Python we want to use the PiDog controller
from pidog import Pidog

# STEP 2: Create your personal robot controller
dog = Pidog()  # This "wakes up" your robot and gets it ready to receive commands

# STEP 3: Use your controller to make the robot do things
dog.do_action("sit")  # Tell the robot to sit down

# STEP 4: ALWAYS close when finished (like turning off a remote)
dog.close()  # This safely "sleeps" the robot
```

### Advanced Initialization (For Experienced Users)

**What are servo pins?** Servo motors are the "muscles" that move your PiDog's body parts. Each servo is connected to a specific numbered pin on the robot's brain (Raspberry Pi). You usually don't need to change these unless you're building a custom robot.

```python
# Custom setup (only needed if you modify the hardware)
dog = Pidog(
    leg_pins=[2, 3, 7, 8, 0, 1, 10, 11],  # Which pins control the 8 leg servos
    head_pins=[4, 6, 5],                   # Pins for head movement (left/right, roll, up/down)
    tail_pin=[9],                          # Pin for tail wagging
    leg_init_angles=[45, -45, -45, 45, 45, -45, -45, 45],  # Starting leg positions (degrees)
    head_init_angles=[0, 0, 0],            # Starting head position [yaw, roll, pitch]
    tail_init_angle=[0]                    # Starting tail position
)
```

**🎯 Understanding Angles:**
- **Positive numbers** = One direction (e.g., leg forward, head right)
- **Negative numbers** = Opposite direction (e.g., leg backward, head left)  
- **Zero (0)** = Neutral/center position

### Safe Programming Pattern (Always Use This!)

```python
# The SAFEST way to control your PiDog
from pidog import Pidog

def safe_pidog_program():
    dog = Pidog()  # Start the robot
    
    try:
        # Your robot commands go here
        dog.do_action("stand")
        dog.do_action("wag_tail", step_count=5)
        
    except Exception as error:
        print(f"Something went wrong: {error}")
        
    finally:
        # This ALWAYS runs, even if there's an error
        dog.close()  # Safely shut down the robot

# Run your program
safe_pidog_program()
```

**Why use try/except/finally?**
- **`try:`** = "Attempt to run this code"
- **`except:`** = "If something goes wrong, do this instead of crashing"
- **`finally:`** = "Always do this at the end, no matter what happened"
- This prevents your robot from getting "stuck" if your code has a bug!

---

## 2. 🏃‍♂️ Motion Control: Making Your PiDog Move!

### 2.1 🎬 Preset Actions - Pre-Made Robot "Movies"

**What are preset actions?** Think of them as pre-recorded "movies" for your robot. Instead of manually controlling each leg and joint, you just say "play the walking movie" and your PiDog knows how to walk!

**🔧 Key Parameters Explained:**
- **`speed`** = How fast to move (1-100). Start with 50 for safety!
- **`step_count`** = How many times to repeat the action (like "walk 5 steps")

#### Basic Postures (Your PiDog's "Poses")

```python
# Essential positions every PiDog should know
dog.do_action("stand", speed=60)           # Stand up straight (like attention!)
dog.do_action("sit", speed=50)             # Sit like a good dog 🐕
dog.do_action("lie", speed=40)             # Lie down flat (nap time)
dog.do_action("half_sit", speed=50)        # Half sitting (relaxed position)

# Pro tip: Lower speed = smoother, safer movements for beginners
```

#### Walking and Movement (The Fun Stuff!)

```python
# Basic locomotion - your PiDog learns to walk!
dog.do_action("forward", step_count=5, speed=70)    # Walk forward 5 steps
dog.do_action("backward", step_count=3, speed=60)   # Back up 3 steps (careful!)
dog.do_action("turn_left", step_count=2, speed=80)  # Turn left 2 steps
dog.do_action("turn_right", step_count=2, speed=80) # Turn right 2 steps
dog.do_action("trot", step_count=10, speed=90)      # Fast trotting gait (like a horse!)

# 🎯 Beginner tip: Start with step_count=1 to see what each action does
```

#### Playful Actions (Show Off Your PiDog!)

```python
# Fun actions that make your PiDog look alive
dog.do_action("stretch", speed=50)                  # Morning stretch (so cute!)
dog.do_action("push_up", step_count=5, speed=60)   # Exercise routine - 5 push-ups
dog.do_action("wag_tail", step_count=20, speed=90) # Happy tail wagging 🐕‍🦺

# 💡 Combine actions to create "behaviors"
# Example: Stand → Stretch → Wag Tail = "Happy morning routine"
```

#### Head Expressions (Your PiDog's "Face")

```python
# Head movements add personality and communication
dog.do_action("shake_head", step_count=3, speed=70)      # "No no no!" gesture
dog.do_action("tilting_head", step_count=4, speed=30)    # Curious "What's that?" look
dog.do_action("tilting_head_left", step_count=2, speed=40)   # Tilt left (confused)
dog.do_action("tilting_head_right", step_count=2, speed=40)  # Tilt right (puzzled)
dog.do_action("head_bark", step_count=3, speed=80)       # Aggressive barking motion
dog.do_action("head_up_down", step_count=3, speed=60)    # "Yes yes yes!" nodding

# 🎭 Think of these as your PiDog's "facial expressions"
```

#### Sleepy/Calm Actions (Quiet Time)

```python
# Gentle, slow movements for calm moments
dog.do_action("doze_off", speed=30)                      # Getting sleepy... 😴
dog.do_action("nod_lethargy", step_count=5, speed=20)    # Slow, sleepy head nods

# 🌙 Perfect for bedtime routines or when you want PiDog to be calm
```

#### Waiting for Actions to Complete (Important!)

```python
# Make sure actions finish before starting new ones
dog.do_action("sit")              # Tell PiDog to sit
dog.wait_all_done()              # Wait until sitting is completely finished
dog.do_action("lie")             # Now tell PiDog to lie down

# Alternative: Wait for specific body parts
dog.do_action("forward", step_count=3)
dog.wait_legs_done()             # Wait only for legs to finish moving
dog.wait_head_done()             # Wait only for head to finish
dog.wait_tail_done()             # Wait only for tail to finish

# 🔄 Why wait? Prevents "command collision" - like trying to sit while walking!
```

**🎯 Beginner Project Ideas:**
1. **Morning Routine:** Stand → Stretch → Shake Head → Wag Tail
2. **Greeting Sequence:** Sit → Tilt Head → Nod → Wag Tail  
3. **Exercise Program:** Stand → Push-ups → Trot → Stretch → Lie Down
4. **Playful Interaction:** Shake Head → Tilt Head → Bark Movement → Happy Tail Wag

### 2.2 🔧 Low-Level Servo Control (Advanced Users)

**What is "low-level" control?** Instead of using preset actions like "sit" or "walk", you directly control each individual servo motor (the robot's "muscles"). This is like being a puppet master - you control every joint manually!

**⚠️ Beginner Warning:** Start with preset actions first! Low-level control requires understanding angles and can damage your robot if done incorrectly.

#### Understanding Your PiDog's Anatomy

```python
# Your PiDog has 8 leg servos (think of them as joints):
# 
#   FRONT LEGS        BACK LEGS
#   LF = Left Front   LH = Left Hind  
#   RF = Right Front  RH = Right Hind
#
# Each leg has 2 servos:
# - Shoulder servo (lifts leg up/down)
# - Leg servo (moves leg forward/back)

# Servo order: [LF_shoulder, LF_leg, RF_shoulder, RF_leg, 
#               LH_shoulder, LH_leg, RH_shoulder, RH_leg]
```

#### Manual Servo Control Examples

```python
# Example: Custom push-up positions
push_up_angles = [
    # Each list has 8 numbers (one for each leg servo)
    [90, -30, -90, 30, 80, 70, -80, -70],   # Push-up UP position (chest high)
    [45, 35, -45, -35, 80, 70, -80, -70],   # Push-up DOWN position (chest low)
]

# Move to push-up UP position immediately (waits until finished)
dog.legs_move(push_up_angles[0], speed=50)

# 🎯 Understanding the numbers:
# - Positive angles = One direction (e.g., leg forward)
# - Negative angles = Opposite direction (e.g., leg backward)  
# - Bigger numbers = More extreme positions
# - Safe range: Usually -90 to +90 degrees
# Wait for the movement to completely finish
dog.wait_legs_done()

# 🔄 Advanced: Queue Multiple Movements (Like a Dance!)
# "immediately=False" means "add this to the to-do list, don't wait"
for _ in range(10):  # Repeat 10 times
    dog.legs_move(push_up_angles, immediately=False, speed=60)
    # This creates a "push-up routine" that runs automatically

# 🎭 Direct Head Control - Your PiDog's "Facial Expressions"
# Head has 3 types of movement: [yaw, roll, pitch]
# Think of it like your own head movements:

dog.head_move([[30, 0, 0]], speed=80)      # YAW: Turn head left 30° (like looking left)
dog.head_move([[0, 20, 0]], speed=80)      # ROLL: Tilt head right 20° (like confused puppy)
dog.head_move([[0, 0, -20]], speed=80)     # PITCH: Look down 20° (like sniffing ground)

# 🎯 Head Movement Guide:
# - YAW (left/right): Positive = left, Negative = right
# - ROLL (tilt): Positive = right shoulder up, Negative = left shoulder up  
# - PITCH (up/down): Positive = look up, Negative = look down

# 🤖 Advanced: IMU Compensation (Auto-Balance Head)
# IMU = sensors that detect if PiDog is tilted
# This keeps the head level even if the body is tilted!
dog.head_move([[0, 0, 0]], roll_comp=10, pitch_comp=-5, speed=80)
# roll_comp=10 means "compensate for 10° body roll"
# pitch_comp=-5 means "compensate for 5° body pitch"

# 🐕 Tail Control - Express Emotions!
dog.tail_move([[30]], speed=70)            # Wag right (happy!)
dog.tail_move([[-30]], speed=70)           # Wag left (excited!)
dog.tail_move([[0]], speed=50)             # Center position (neutral)
```

### 2.3 🎼 Movement Coordination - Making Your PiDog "Dance"

**What is coordination?** Making multiple body parts move at the same time, like a choreographed dance routine! This is how you create complex, lifelike behaviors.

```python
# 🎭 Example: Create a "Happy Greeting" Routine
# Step 1: Define the movements
head_shake = [[30, 0, 0], [-30, 0, 0]]     # Shake head left-right
tail_wag = [[40], [-40]]                    # Wag tail left-right

# Step 2: Queue up synchronized movements  
for _ in range(15):  # Repeat 15 times for a good show
    # "immediately=False" means "add to queue, don't wait"
    dog.head_move(head_shake, immediately=False, speed=80)   # Fast head shaking
    dog.tail_move(tail_wag, immediately=False, speed=90)     # Fast tail wagging

# Step 3: Let the "performance" run while you do other things
print("🎉 PiDog is performing! Watch the happy dance!")
time.sleep(5)  # Watch the show for 5 seconds

# Step 4: Stop all movements safely
print("🛑 Show's over! Stopping all movement...")
dog.body_stop()  # Emergency stop - stops ALL servos immediately

# 🎯 Why use "immediately=False"?
# - Lets you queue up many movements at once
# - Creates smooth, continuous motion instead of jerky stop-start
# - Like giving PiDog a "playlist" of movements to perform

# 🚨 Safety Tip: Always use dog.body_stop() if something goes wrong!
```

**🎨 Creative Ideas for Coordination:**
1. **Excited Greeting:** Head shake + Tail wag + Standing position
2. **Searching Behavior:** Head looking around + Walking in circles
3. **Alert Mode:** Head up + Tail straight + Standing tall
4. **Playful Mode:** Head tilting + Tail wagging + Bouncy movements

---

## 3. 👁️ Sensor Integration - Giving Your PiDog "Senses"

**What are sensors?** Think of them as your PiDog's senses - just like you have eyes to see, ears to hear, and skin to feel, your PiDog has electronic sensors that detect the world around it!

### 3.1 🧭 IMU (Inertial Measurement Unit) - Your PiDog's "Inner Ear"

**What does the IMU do?** Just like your inner ear helps you balance and know which way is up, the IMU tells your PiDog:
- 📐 **Am I tilted?** (like when walking on a ramp)
- 🏃‍♂️ **Am I moving?** (acceleration in any direction)  
- 🔄 **Am I rotating?** (spinning or turning around)

**Why is this useful?** Your PiDog can automatically:
- Keep its balance when walking on uneven surfaces
- Know when it's being picked up or falling over
- React to being pushed or bumped

```python
import math
import time

def read_pidog_balance():
    """
    A beginner-friendly function to understand PiDog's balance and orientation
    """
    print("🧭 Reading PiDog's IMU sensors...")
    
    # Read the raw sensor data (numbers from the hardware)
    ax, ay, az = dog.accData    # ACCELEROMETER: Measures gravity + movement forces
    gx, gy, gz = dog.gyroData   # GYROSCOPE: Measures rotation speed
    
    print(f"📊 Raw accelerometer: X={ax}, Y={ay}, Z={az}")
    print(f"🔄 Raw gyroscope: X={gx}, Y={gy}, Z={gz}")
    
    # Convert raw numbers to meaningful measurements
    # Why divide by 16384? That's how this specific sensor chip works!
    ax_g = ax / 16384.0         # Convert to "G force" (Earth's gravity = 1G)
    ay_g = ay / 16384.0         # G force in Y direction  
    az_g = az / 16384.0         # G force in Z direction
    
    print(f"🌍 G-forces: X={ax_g:.2f}G, Y={ay_g:.2f}G, Z={az_g:.2f}G")
    
    # Calculate how tilted PiDog is (in degrees)
    # This uses trigonometry - don't worry about the math details!
    pitch = math.atan2(ay, math.sqrt(ax*ax + az*az)) * 180 / math.pi
    roll = math.atan2(-ax, az) * 180 / math.pi
    
    print(f"Acc: {ax_g:.2f}g, {ay_g:.2f}g, {az_g:.2f}g")
    print(f"Gyro: {gx}°/s, {gy}°/s, {gz}°/s")
    print(f"Tilt - Pitch: {pitch:.1f}°, Roll: {roll:.1f}°")
    
    # Keep head level using pitch compensation
    dog.head_move([[0, 0, 0]], pitch_comp=-pitch, speed=80)
    
    time.sleep(0.1)
```

### 3.2 Ultrasonic Distance Sensor

```python
# Read distance continuously
while True:
    distance = dog.ultrasonic.read_distance()  # Returns distance in cm
    print(f"Distance: {distance:.2f} cm")
    
    if distance < 20:
        # Obstacle detected - back up and bark
        dog.do_action("backward", step_count=2, speed=70)
        dog.speak("single_bark_1", volume=80)
        
    time.sleep(0.2)
```

### 3.3 Sound Direction Detection

```python
# Detect sound direction and turn head
while True:
    if dog.ears.isdetected():
        direction = dog.ears.read()  # Returns 0-359° (0=front, 90=right)
        print(f"Sound detected at {direction}°")
        
        # Convert to head yaw angle (safe range: -90° to +90°)
        if direction > 180:
            yaw_angle = max(-90, (direction - 360) / 2)
        else:
            yaw_angle = min(90, direction / 2)
            
        # Turn head toward sound
        dog.head_move([[yaw_angle, 0, 0]], speed=80)
        
    time.sleep(0.05)
```

### 3.4 Dual Touch Sensor (Head Petting)

```python
# React to head touches
while True:
    touch_status = dog.dual_touch.read()
    
    if touch_status == "L":          # Left side touched
        dog.speak("pant", volume=60)
        dog.rgb_strip.set_mode("breath", "green", brightness=0.8)
        
    elif touch_status == "R":        # Right side touched
        dog.do_action("wag_tail", step_count=5, speed=90)
        
    elif touch_status == "LS":       # Left to right swipe
        dog.do_action("turn_right", step_count=1, speed=70)
        
    elif touch_status == "RS":       # Right to left swipe
        dog.do_action("turn_left", step_count=1, speed=70)
        
    # "N" = no touch
    time.sleep(0.05)
```

---

## 4. Audio System

### 4.1 Built-in Sound Effects

```python
# Available sound effects (from /sounds directory)
sounds = [
    "angry",         # Angry bark
    "confused_1",    # Confused whine 1
    "confused_2",    # Confused whine 2  
    "confused_3",    # Confused whine 3
    "growl_1",       # Low growl 1
    "growl_2",       # Low growl 2
    "howling",       # Howling sound
    "pant",          # Happy panting
    "single_bark_1", # Single bark 1
    "single_bark_2", # Single bark 2
    "snoring",       # Sleeping snore
    "woohoo"         # Excited sound
]

# Play sounds with volume control
for sound in sounds:
    print(f"Playing: {sound}")
    dog.speak(sound, volume=80)  # Volume 0-100
    time.sleep(2)
```

### 4.2 Audio in Behaviors

```python
def happy_greeting():
    """Happy greeting behavior with sound and movement"""
    dog.speak("woohoo", volume=90)
    dog.do_action("wag_tail", step_count=10, speed=90)
    dog.do_action("head_up_down", step_count=3, speed=70)
    
def angry_warning():
    """Angry warning behavior"""
    dog.speak("growl_1", volume=100)
    dog.rgb_strip.set_mode("bark", "red", brightness=1.0)
    dog.do_action("head_bark", step_count=2, speed=80)
```

---

## 5. RGB LED Control

### 5.1 LED Modes and Effects

```python
# Available LED modes
dog.rgb_strip.set_mode("breath", "blue", brightness=0.7)     # Breathing effect
dog.rgb_strip.set_mode("boom", "red", bps=3.0, brightness=1.0)  # Pulsing boom
dog.rgb_strip.set_mode("bark", "orange", brightness=0.8)     # Bark indicator

# Color options
colors = [
    "red", "green", "blue", "yellow", "purple", "cyan", 
    "white", "black", "pink", "orange"
]

# Hex colors also supported
dog.rgb_strip.set_mode("breath", "#FF6B35", brightness=0.5)  # Custom orange

# Dynamic effects with timing
dog.rgb_strip.set_mode("boom", "green", bps=2.5, brightness=0.9)  # 2.5 beats per second

# Turn off LEDs
dog.rgb_strip.set_mode("breath", "black")
dog.rgb_strip.close()
```

### 5.2 LED Patterns for Behaviors

```python
def emotion_lights(emotion):
    """Set LED colors based on emotion"""
    if emotion == "happy":
        dog.rgb_strip.set_mode("breath", "green", brightness=0.8)
    elif emotion == "angry":
        dog.rgb_strip.set_mode("bark", "red", brightness=1.0)
    elif emotion == "excited":
        dog.rgb_strip.set_mode("boom", "yellow", bps=4.0, brightness=1.0)
    elif emotion == "calm":
        dog.rgb_strip.set_mode("breath", "blue", brightness=0.4)
    elif emotion == "alert":
        dog.rgb_strip.set_mode("boom", "orange", bps=1.5, brightness=0.9)
```

---

## 6. Advanced Control Patterns

### 6.1 Event Loop Template

```python
import time
from pidog import Pidog

def main_behavior_loop():
    """Main behavior loop with sensor integration"""
    dog = Pidog()
    
    try:
        # Initialize position
        dog.do_action("stand", speed=60)
        dog.wait_all_done()
        
        while True:
            # Read all sensors
            distance = dog.ultrasonic.read_distance()
            touch = dog.dual_touch.read()
            sound_detected = dog.ears.isdetected()
            
            # Behavior priorities (higher priority first)
            if touch != "N":
                handle_touch_interaction(dog, touch)
                
            elif distance > 0 and distance < 15:
                handle_obstacle_avoidance(dog)
                
            elif sound_detected:
                handle_sound_attention(dog)
                
            else:
                handle_idle_behavior(dog)
                
            time.sleep(0.05)  # 20Hz update rate
            
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        dog.close()

def handle_touch_interaction(dog, touch_type):
    """Handle different types of touch interactions"""
    if touch_type == "L":
        dog.speak("pant")
        emotion_lights("happy")
    elif touch_type == "R":
        dog.do_action("wag_tail", step_count=3, speed=90)

def handle_obstacle_avoidance(dog):
    """Avoid obstacles detected by ultrasonic sensor"""
    dog.speak("confused_1")
    dog.do_action("backward", step_count=1, speed=60)
    dog.do_action("turn_left", step_count=1, speed=70)

def handle_sound_attention(dog):
    """Turn attention toward detected sounds"""
    direction = dog.ears.read()
    yaw = max(-45, min(45, (direction - 180) / 4))
    dog.head_move([[yaw, 0, 0]], speed=80)

def handle_idle_behavior(dog):
    """Random idle behaviors when nothing is happening"""
    import random
    idle_actions = ["tilting_head", "head_up_down", "wag_tail"]
    if random.random() < 0.01:  # 1% chance per cycle
        action = random.choice(idle_actions)
        dog.do_action(action, step_count=2, speed=50)

if __name__ == "__main__":
    main_behavior_loop()
```

---

## 7. Error Handling and Safety

### 7.1 Safe Program Structure

```python
#!/usr/bin/env python3
"""
Safe PiDog program template with comprehensive error handling
"""
from pidog import Pidog
import time
import signal
import sys

class SafePiDogController:
    def __init__(self):
        self.dog = None
        self.running = True
        
    def setup_signal_handlers(self):
        """Setup graceful shutdown on Ctrl+C"""
        def signal_handler(sig, frame):
            print("\nReceived interrupt signal. Shutting down safely...")
            self.running = False
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def initialize_dog(self):
        """Initialize PiDog with error handling"""
        try:
            print("Initializing PiDog...")
            self.dog = Pidog()
            print("PiDog initialized successfully")
            return True
        except OSError as e:
            print(f"Hardware initialization error: {e}")
            return False
        except Exception as e:
            print(f"Unexpected initialization error: {e}")
            return False
    
    def safe_action(self, action_func, *args, **kwargs):
        """Execute action with error handling"""
        try:
            return action_func(*args, **kwargs)
        except Exception as e:
            print(f"Action error: {e}")
            self.emergency_stop()
            
    def emergency_stop(self):
        """Emergency stop all movement"""
        if self.dog:
            try:
                self.dog.body_stop()
                print("Emergency stop executed")
            except Exception as e:
                print(f"Emergency stop failed: {e}")
    
    def cleanup(self):
        """Clean shutdown"""
        if self.dog:
            try:
                print("Returning to safe position...")
                self.dog.stop_and_lie()
                self.dog.close()
                print("Shutdown complete")
            except Exception as e:
                print(f"Cleanup error: {e}")
    
    def run(self):
        """Main execution with full safety"""
        self.setup_signal_handlers()
        
        if not self.initialize_dog():
            return False
            
        try:
            # Your main program logic here
            self.main_behavior()
            
        except KeyboardInterrupt:
            print("Interrupted by user")
        except Exception as e:
            print(f"Runtime error: {e}")
            self.emergency_stop()
        finally:
            self.cleanup()
            
    def main_behavior(self):
        """Main behavior loop - implement your logic here"""
        self.safe_action(self.dog.do_action, "stand", speed=60)
        self.safe_action(self.dog.wait_all_done)
        
        while self.running:
            # Your behavior code here
            time.sleep(0.1)

# Usage
if __name__ == "__main__":
    controller = SafePiDogController()
    controller.run()
```

### 7.2 Common Error Scenarios

```python
# Servo range limits
def safe_head_move(dog, yaw, roll, pitch):
    """Move head with safety limits"""
    # Clamp to safe ranges
    yaw = max(-90, min(90, yaw))
    roll = max(-70, min(70, roll))  
    pitch = max(-45, min(30, pitch))
    
    dog.head_move([[yaw, roll, pitch]], speed=80)

# Sensor error handling
def read_distance_safe(dog):
    """Read distance with error handling"""
    try:
        distance = dog.ultrasonic.read_distance()
        if distance is None or distance < 0:
            return None
        return distance
    except Exception as e:
        print(f"Distance sensor error: {e}")
        return None

# Buffer overflow protection
def controlled_movement_queue(dog, movements, max_buffer=10):
    """Add movements with buffer size control"""
    current_buffer = len(dog.legs_action_buffer)
    
    if current_buffer > max_buffer:
        print("Buffer full, waiting...")
        dog.wait_legs_done()
    
    for movement in movements:
        dog.legs_move(movement, immediately=False, speed=70)
```

---

## 8. Complete Debugging and Monitoring

```python
# Debug information display
def show_robot_status(dog):
    """Display comprehensive robot status"""
    print("=== PiDog Status ===")
    
    # Buffer status
    print(f"Legs buffer: {len(dog.legs_action_buffer)} actions queued")
    print(f"Head buffer: {len(dog.head_action_buffer)} actions queued") 
    print(f"Tail buffer: {len(dog.tail_action_buffer)} actions queued")
    
    # Current positions
    print(f"Leg angles: {dog.leg_current_angles}")
    print(f"Head angles: {dog.head_current_angles}")
    print(f"Tail angle: {dog.tail_current_angles}")
    
    # Sensor readings
    distance = dog.ultrasonic.read_distance()
    ax, ay, az = dog.accData
    touch = dog.dual_touch.read()
    
    print(f"Distance: {distance:.2f} cm")
    print(f"Accelerometer: X={ax} Y={ay} Z={az}")
    print(f"Touch: {touch}")
    
    # Thread status
    print(f"Exit flag: {dog.exit_flag}")
    print("==================")

# Performance monitoring
import time

def monitor_loop_performance():
    """Monitor main loop timing"""
    loop_times = []
    
    while True:
        start_time = time.time()
        
        # Your main loop code here
        
        loop_time = time.time() - start_time
        loop_times.append(loop_time)
        
        # Report every 100 cycles
        if len(loop_times) >= 100:
            avg_time = sum(loop_times) / len(loop_times)
            max_time = max(loop_times)
            print(f"Loop performance: avg={avg_time*1000:.1f}ms, max={max_time*1000:.1f}ms")
            loop_times.clear()
```

---

## 9. Project Templates and Patterns

### 9.1 Basic Project Template

```python
#!/usr/bin/env python3
"""
PiDog project template

Safely initializes the robot, runs your logic, and shuts down cleanly even on Ctrl+C.
"""
from pidog import Pidog
import time


def run(dog: Pidog) -> None:
    # Put your logic here. Example: stand up, wag tail, then sit.
    dog.do_action("stand", speed=60)
    dog.wait_all_done()

    for _ in range(10):
        dog.tail_move([[30], [-30]], immediately=False, speed=40)
    dog.wait_tail_done()

    dog.do_action("sit", speed=50)
    dog.wait_all_done()


def main() -> None:
    dog = Pidog()
    try:
        run(dog)
    except KeyboardInterrupt:
        # Allow quick abort without stack trace
        pass
    except Exception as e:
        print(f"ERROR: {e}")
        raise
    finally:
        # Always leave servos in a safe state and stop threads
        try:
            dog.stop_and_lie()
        finally:
            dog.close()


if __name__ == "__main__":
    main()
```

### 9.2 Interactive Behavior Template

```python
#!/usr/bin/env python3
"""
Interactive PiDog behavior template
Responds to sensors and user interaction
"""
from pidog import Pidog
import time
import random


class InteractiveDog:
    def __init__(self):
        self.dog = Pidog()
        self.running = True
        self.mood = "neutral"
        
    def run_behavior_loop(self):
        """Main behavior loop"""
        self.dog.do_action("stand", speed=60)
        self.dog.wait_all_done()
        
        try:
            while self.running:
                # Check sensors
                touch = self.dog.dual_touch.read()
                distance = self.dog.ultrasonic.read_distance()
                sound_detected = self.dog.ears.isdetected()
                
                # React based on inputs
                if touch != "N":
                    self.handle_touch(touch)
                elif distance > 0 and distance < 20:
                    self.handle_obstacle()
                elif sound_detected:
                    self.handle_sound()
                else:
                    self.idle_behavior()
                    
                time.sleep(0.05)
                
        except KeyboardInterrupt:
            print("Stopping behavior...")
        finally:
            self.cleanup()
    
    def handle_touch(self, touch_type):
        """React to being petted"""
        self.mood = "happy"
        self.dog.speak("pant", volume=70)
        self.dog.rgb_strip.set_mode("breath", "green", brightness=0.8)
        self.dog.do_action("wag_tail", step_count=5, speed=90)
        
    def handle_obstacle(self):
        """React to obstacles"""
        self.mood = "cautious"
        self.dog.speak("confused_1", volume=60)
        self.dog.rgb_strip.set_mode("bark", "orange", brightness=0.9)
        self.dog.do_action("backward", step_count=1, speed=60)
        
    def handle_sound(self):
        """React to sounds"""
        direction = self.dog.ears.read()
        yaw = max(-45, min(45, (direction - 180) / 4))
        self.dog.head_move([[yaw, 0, 0]], speed=80)
        
    def idle_behavior(self):
        """Random idle movements"""
        if random.random() < 0.01:  # 1% chance per loop
            actions = ["tilting_head", "head_up_down"]
            action = random.choice(actions)
            self.dog.do_action(action, step_count=1, speed=40)
    
    def cleanup(self):
        """Safe shutdown"""
        self.running = False
        self.dog.rgb_strip.close()
        self.dog.stop_and_lie()
        self.dog.close()


if __name__ == "__main__":
    interactive_dog = InteractiveDog()
    interactive_dog.run_behavior_loop()
```

---

## Additional Resources

### Complete Example Files
- **[`pidog_programming_examples.py`](./pidog_programming_examples.py)** - Menu-driven examples for every PiDog feature
- **[`advanced_pidog_ai.py`](./advanced_pidog_ai.py)** - Advanced AI behavior system with emotions and learning

### Reference Documentation
- **[`api_reference_enhanced.md`](./api_reference_enhanced.md)** - Complete API reference with all methods and parameters

### Official Resources
- [Official PiDog Documentation](https://docs.sunfounder.com/projects/pidog/en/latest/)
- [PiDog GitHub Repository](https://github.com/sunfounder/pidog)
- [SunFounder Support Forum](https://forum.sunfounder.com/)

### Development Tips

1. **Always use `try/finally` blocks** to ensure `dog.close()` is called
2. **Test sensor readings** before using them in calculations  
3. **Use `wait_*_done()` methods** to coordinate multi-part movements
4. **Monitor buffer sizes** to prevent overflow in long-running programs
5. **Implement emergency stops** for safety in complex behaviors
6. **Use the `immediately=False` parameter** for smooth continuous movements
7. **Clamp servo angles** to safe ranges before sending commands
8. **Handle interrupts gracefully** with signal handlers or try/except blocks

### Common Patterns

- **Sensor polling loop**: Read sensors at 20Hz, act on changes
- **State machines**: Use enums and current state to drive behaviors  
- **Priority systems**: Handle high-priority inputs (touch) before lower priority (idle)
- **Buffer management**: Monitor and control action buffer sizes
- **Graceful shutdown**: Always return to safe position before exit
- **Error recovery**: Catch exceptions and attempt emergency stop

---

**Happy coding with your PiDog! 🐕🤖**