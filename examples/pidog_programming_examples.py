#!/usr/bin/env python3
"""
Complete PiDog Programming Examples - BEGINNER FRIENDLY! 
=========================================================

🎓 PERFECT FOR BEGINNERS! 🎓

This file contains working code examples for EVERY PiDog feature.
Each example is explained step-by-step so complete beginners can understand.

🚀 How to use this file:
1. Run it: python3 pidog_programming_examples.py  
2. Choose an example from the menu
3. Watch your PiDog perform the action
4. Look at the code to see HOW it works

🎯 What you'll learn:
- Basic movement commands (sit, stand, walk)
- Head and tail control  
- Reading sensors (touch, ultrasonic, IMU)
- LED light effects
- Sound interactions
- Advanced behaviors and AI patterns

⚠️ Safety First:
- Always have space around your PiDog
- Keep the emergency stop button ready (Ctrl+C)
- Start with slow speeds when testing
"""

from pidog import Pidog
import time
import math
import random


class PiDogExamples:
    """
    🤖 Complete collection of PiDog programming examples 
    
    This class is like a "remote control" that contains all the example programs.
    Think of it as a collection of different "tricks" your PiDog can perform!
    """
    
    def __init__(self):
        """
        Set up our example collection (constructor)
        
        What this does:
        - Creates a place to store our PiDog controller
        - Doesn't actually connect to PiDog yet (that happens in safe_init)
        """
        self.dog = None  # This will hold our PiDog controller when we connect
        
    def safe_init(self):
        """
        🔌 Connect to PiDog safely (with error protection)
        
        What this does:
        - Tries to "wake up" your PiDog
        - If something goes wrong, tells you what happened instead of crashing
        - Returns True if successful, False if failed
        
        Why "safe"? Because robots can fail to connect due to:
        - Hardware not plugged in
        - Permission problems  
        - Other programs using the robot
        """
        try:
            print("🤖 Waking up PiDog...")
            self.dog = Pidog()  # This "wakes up" the robot hardware
            print("✅ PiDog is awake and ready!")
            return True
        except Exception as e:
            print(f"❌ Oops! Could not wake up PiDog: {e}")
            print("💡 Check: Is PiDog plugged in? Are you running as administrator?")
            return False
    
    def safe_close(self):
        """
        🔒 Put PiDog to "sleep" safely
        
        What this does:
        - Tells PiDog to lie down (safe position)
        - Turns off all the servo motors (saves power, prevents overheating)
        - Closes the connection cleanly
        
        Why always do this?
        - Prevents servo motors from overheating
        - Saves battery power
        - Leaves PiDog in a safe position
        - Frees up the connection for other programs
        """
        if self.dog:  # Only if we actually have a PiDog connected
            try:
                print("🛌 Putting PiDog to sleep...")
                self.dog.stop_and_lie()  # Safe position: lying down with motors off
                self.dog.close()         # Close the connection
                print("✅ PiDog is safely asleep. Goodnight!")
            except Exception as e:
                print(f"❌ Problem during shutdown: {e}")
                print("💡 This usually isn't serious - PiDog should still be safe")
    
    def basic_movements(self):
        """
        🏃‍♂️ Example 1: Basic Movement Commands
        
        This is your FIRST PiDog program! We'll teach PiDog the basic "tricks":
        - Stand up (like a soldier at attention)
        - Walk forward (just like a real dog)
        - Turn around (to face the opposite direction)  
        - Sit down (good dog behavior!)
        
        🎯 Learning Goals:
        - Understand do_action() - the main command function
        - Learn about speed (how fast to move)
        - See why wait_all_done() is important
        """
        print("\n🏃‍♂️ === BASIC MOVEMENTS DEMO ===")
        print("Teaching PiDog the essential moves every dog should know!")
        
        # 📍 MOVEMENT 1: Stand up
        print("\n1️⃣ Teaching PiDog to stand up...")
        self.dog.do_action("stand", speed=60)  # speed=60 is medium fast (safe for beginners)
        self.dog.wait_all_done()               # WAIT until standing is completely finished
        print("   ✅ PiDog is now standing! (Look how proud!)")
        time.sleep(1)  # Pause so you can see the result
        
        # 📍 MOVEMENT 2: Walk forward  
        print("\n2️⃣ Teaching PiDog to walk forward...")
        print("   (Watch those legs move in coordination!)")
        self.dog.do_action("forward", step_count=3, speed=70)  # Take 3 steps forward
        self.dog.wait_all_done()  # Wait until all 3 steps are finished
        print("   ✅ PiDog walked 3 steps forward! (Just like a real dog!)")
        
        # 📍 MOVEMENT 3: Turn around
        print("\n3️⃣ Teaching PiDog to turn around...")
        print("   (This will take 4 left turns to face the opposite direction)")
        self.dog.do_action("turn_left", step_count=4, speed=80)  # 4 left steps = 180° turn
        self.dog.wait_all_done()
        print("   ✅ PiDog turned around! (Now facing where it came from)")
        
        # 📍 MOVEMENT 4: Sit down
        print("\n4️⃣ Teaching PiDog to sit (good dog!)...")
        self.dog.do_action("sit", speed=50)    # Slower speed for smooth sitting
        self.dog.wait_all_done()
        print("   ✅ PiDog is sitting! (Such a good dog! 🐕)")
        
        print("\n🎉 Basic movements complete! PiDog now knows the essentials!")
        print("💡 Try changing the speeds and step_counts in the code to experiment!")
    
    def head_control_demo(self):
        """
        🎭 Example 2: Head Movement and Expressions
        
        PiDog's head is like its "face" - it shows emotions and looks around!
        We'll teach PiDog to:
        - Look left and right (like watching tennis)
        - Tilt its head (like a confused puppy)
        - Look up and down (like tracking a flying ball)
        - Use sensors to keep head level (advanced balance!)
        
        🎯 Learning Goals:
        - Understand head_move() coordinates [yaw, roll, pitch]
        - See how head movements create "personality"
        - Learn about IMU sensor balance compensation
        """
        print("\n🎭 === HEAD CONTROL DEMO ===")
        print("Teaching PiDog expressive head movements!")
        
        # 🎬 Define all the head "expressions" PiDog will perform
        # Each movement is [yaw, roll, pitch] = [left/right, tilt, up/down]
        movements = [
            ([30, 0, 0], "Looking left (like hearing a sound)"),
            ([-30, 0, 0], "Looking right (checking the other direction)"), 
            ([0, 20, 0], "Tilting right (confused puppy look)"),
            ([0, -20, 0], "Tilting left (curious about something)"),
            ([0, 0, -20], "Looking down (sniffing the ground)"),
            ([0, 0, 20], "Looking up (watching a bird fly by)"),
            ([0, 0, 0], "Centering (back to neutral position)")
        ]
        
        print("\n🎪 Performing head expression sequence...")
        for i, (angles, description) in enumerate(movements, 1):
            print(f"   {i}️⃣ {description}")
            self.dog.head_move([angles], speed=80)  # Move head to this position
            self.dog.wait_head_done()               # Wait until movement finishes
            time.sleep(0.5)  # Pause so you can see each expression clearly
            print(f"      ✅ Position reached: {angles}")
        
        print("\n🤖 === ADVANCED: IMU BALANCE COMPENSATION ===")
        print("Now teaching PiDog to keep its head level like a chicken!")
        print("(Try gently tilting your PiDog's body while this runs)")
        
        # 🧭 IMU Compensation Demo
        # This keeps the head level even when the body tilts!
        print("\n🔄 Starting 20-second balance demonstration...")
        for i in range(200):  # Run for about 20 seconds (200 x 0.1s)
            # Read the IMU sensors (like PiDog's inner ear)
            ax, ay, az = self.dog.accData
            
            # Calculate how tilted the body is (math magic - don't worry about details!)
            pitch = math.atan2(ay, math.sqrt(ax*ax + az*az)) * 180 / math.pi
            
            # Keep head level by tilting opposite to body tilt
            self.dog.head_move([[0, 0, 0]], pitch_comp=-pitch, speed=60)
            
            # Show progress every 2 seconds
            if i % 20 == 0:
                print(f"   🎯 Balance check {i//20 + 1}/10: Body tilt = {pitch:.1f}°")
            
            time.sleep(0.1)  # Check balance 10 times per second
            
        print("   ✅ Balance demonstration complete!")
        print("\n🎉 Head control demo finished! PiDog is quite the performer!")
        print("💡 Try combining head movements with walking for even more personality!")
    
    def audio_showcase(self):
        """Example 3: Audio system demonstration"""
        print("\n=== Audio Showcase ===")
        
        # All available sound effects
        sounds = [
            ("single_bark_1", "Single bark"),
            ("pant", "Happy panting"),
            ("woohoo", "Excitement"),
            ("howling", "Howling"),
            ("growl_1", "Warning growl")
        ]
        
        for sound_name, description in sounds:
            print(f"♪ Playing: {description}")
            self.dog.speak(sound_name, volume=70)
            time.sleep(2)
    
    def led_light_show(self):
        """Example 4: RGB LED patterns"""
        print("\n=== LED Light Show ===")
        
        patterns = [
            ("breath", "blue", 0.8, "Calm breathing"),
            ("boom", "red", 1.0, "Alert pulse"),
            ("bark", "yellow", 0.9, "Bark indicator"),
            ("breath", "green", 0.6, "Happy mood")
        ]
        
        for style, color, brightness, description in patterns:
            print(f"💡 {description}")
            if style == "boom":
                self.dog.rgb_strip.set_mode(style, color, bps=2.0, brightness=brightness)
            else:
                self.dog.rgb_strip.set_mode(style, color, brightness=brightness)
            time.sleep(3)
        
        # Turn off LEDs
        self.dog.rgb_strip.set_mode("breath", "black")
    
    def sensor_integration(self):
        """Example 5: Multi-sensor behavior"""
        print("\n=== Sensor Integration ===")
        print("Touch the head, make sounds, or put objects in front...")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                # Check ultrasonic distance
                distance = self.dog.ultrasonic.read_distance()
                
                # Check touch sensor
                touch = self.dog.dual_touch.read()
                
                # Check sound direction
                sound_detected = self.dog.ears.isdetected()
                
                # Priority-based behavior
                if touch != "N":
                    self.handle_touch(touch)
                elif distance > 0 and distance < 20:
                    self.handle_obstacle(distance)
                elif sound_detected:
                    self.handle_sound()
                    
                time.sleep(0.05)  # 20Hz update rate
                
        except KeyboardInterrupt:
            print("\n✓ Sensor demo stopped")
    
    def handle_touch(self, touch_type):
        """Handle different touch interactions"""
        touch_responses = {
            "L": ("pant", "green", "Left side petted"),
            "R": ("woohoo", "yellow", "Right side petted"), 
            "LS": ("single_bark_1", "blue", "Left-to-right swipe"),
            "RS": ("single_bark_2", "purple", "Right-to-left swipe")
        }
        
        if touch_type in touch_responses:
            sound, color, message = touch_responses[touch_type]
            print(f"👋 {message}")
            self.dog.speak(sound, volume=60)
            self.dog.rgb_strip.set_mode("breath", color, brightness=0.8)
            
            if "swipe" in message:
                # Turn in swipe direction
                direction = "turn_right" if touch_type == "LS" else "turn_left"
                self.dog.do_action(direction, step_count=1, speed=70)
    
    def handle_obstacle(self, distance):
        """React to nearby obstacles"""
        print(f"⚠️ Obstacle at {distance:.1f}cm - backing away")
        self.dog.speak("confused_1", volume=50)
        self.dog.rgb_strip.set_mode("bark", "red", brightness=1.0)
        self.dog.do_action("backward", step_count=1, speed=60)
        time.sleep(1)  # Prevent rapid retriggering
    
    def handle_sound(self):
        """Turn toward detected sounds"""
        direction = self.dog.ears.read()
        print(f"👂 Sound detected at {direction}°")
        
        # Convert to safe head yaw angle
        if direction > 180:
            yaw = max(-45, (direction - 360) / 4)
        else:
            yaw = min(45, direction / 4)
        
        self.dog.head_move([[yaw, 0, 0]], speed=80)
        self.dog.rgb_strip.set_mode("boom", "orange", bps=3.0, brightness=0.8)
        time.sleep(0.5)
    
    def advanced_choreography(self):
        """Example 6: Complex coordinated movements"""
        print("\n=== Advanced Choreography ===")
        
        # Greeting routine
        print("🎭 Performing greeting routine...")
        
        # Stand and wag tail
        self.dog.do_action("stand", speed=60)
        self.dog.wait_all_done()
        
        # Coordinated movements
        for _ in range(8):
            # Queue tail wag and head nod
            self.dog.tail_move([[30], [-30]], immediately=False, speed=90)
            self.dog.head_move([[0, 0, -20], [0, 0, 10]], immediately=False, speed=70)
            
        # Add excitement sound and lights  
        self.dog.speak("woohoo", volume=80)
        self.dog.rgb_strip.set_mode("boom", "rainbow", bps=4.0, brightness=1.0)
        
        # Let choreography run
        time.sleep(4)
        
        # Push-up exercise with head tracking
        print("🎭 Push-up exercise with head level...")
        push_up_angles = [
            [90, -30, -90, 30, 80, 70, -80, -70],   # Up position
            [45, 35, -45, -35, 80, 70, -80, -70]    # Down position
        ]
        
        for _ in range(8):
            # Add push-up to queue
            self.dog.legs_move(push_up_angles, immediately=False, speed=50)
            
            # Keep head level using IMU
            ax, ay, az = self.dog.accData
            pitch = math.atan2(ay, math.sqrt(ax*ax + az*az)) * 180 / math.pi
            self.dog.head_move([[0, 0, 0]], pitch_comp=-pitch, immediately=False, speed=60)
        
        # Wait for completion
        self.dog.wait_all_done()
        print("✓ Choreography complete")
    
    def debug_and_monitoring(self):
        """Example 7: Debug information and monitoring"""
        print("\n=== Debug and Monitoring ===")
        
        for i in range(10):
            print(f"\n--- Status Update {i+1} ---")
            
            # Buffer status
            print(f"Legs buffer: {len(self.dog.legs_action_buffer)} queued")
            print(f"Head buffer: {len(self.dog.head_action_buffer)} queued")
            print(f"Tail buffer: {len(self.dog.tail_action_buffer)} queued")
            
            # Current positions
            print(f"Leg angles: {self.dog.leg_current_angles}")
            print(f"Head angles: {self.dog.head_current_angles}")
            print(f"Tail angle: {self.dog.tail_current_angles}")
            
            # Sensor readings
            distance = self.dog.ultrasonic.read_distance()
            ax, ay, az = self.dog.accData  
            gx, gy, gz = self.dog.gyroData
            touch = self.dog.dual_touch.read()
            
            print(f"Distance: {distance:.2f}cm")
            print(f"Accelerometer: X={ax:6d} Y={ay:6d} Z={az:6d}")
            print(f"Gyroscope: X={gx:4d} Y={gy:4d} Z={gz:4d}")
            print(f"Touch: {touch}")
            
            # Add some movement for variety
            if i % 3 == 0:
                self.dog.head_move([[random.randint(-30, 30), 0, 0]], speed=50)
            
            time.sleep(2)
    
    def run_all_examples(self):
        """Run all examples in sequence"""
        if not self.safe_init():
            return
        
        try:
            examples = [
                self.basic_movements,
                self.head_control_demo,
                self.audio_showcase,
                self.led_light_show,
                self.advanced_choreography,
                # self.sensor_integration,  # Interactive - run separately
                # self.debug_and_monitoring  # Verbose - run separately
            ]
            
            for i, example in enumerate(examples, 1):
                print(f"\n{'='*50}")
                print(f"Running Example {i}/{len(examples)}")
                print(f"{'='*50}")
                
                try:
                    example()
                    print(f"✓ Example {i} completed successfully")
                except Exception as e:
                    print(f"✗ Example {i} failed: {e}")
                
                if i < len(examples):
                    print("\nWaiting 3 seconds before next example...")
                    time.sleep(3)
        
        except KeyboardInterrupt:
            print("\n\nExamples interrupted by user")
        
        finally:
            self.safe_close()


def main():
    """Main function with menu system"""
    examples = PiDogExamples()
    
    print("PiDog Programming Examples")
    print("=" * 30)
    print("1. Run all examples")
    print("2. Basic movements")
    print("3. Head control")  
    print("4. Audio showcase")
    print("5. LED light show")
    print("6. Sensor integration (interactive)")
    print("7. Advanced choreography")
    print("8. Debug monitoring")
    print("0. Exit")
    
    while True:
        try:
            choice = input("\nEnter choice (0-8): ").strip()
            
            if choice == "0":
                break
            elif choice == "1":
                examples.run_all_examples()
            elif choice in ["2", "3", "4", "5", "6", "7", "8"]:
                if examples.safe_init():
                    try:
                        if choice == "2":
                            examples.basic_movements()
                        elif choice == "3":
                            examples.head_control_demo()
                        elif choice == "4":
                            examples.audio_showcase()
                        elif choice == "5":
                            examples.led_light_show()
                        elif choice == "6":
                            examples.sensor_integration()
                        elif choice == "7":
                            examples.advanced_choreography()
                        elif choice == "8":
                            examples.debug_and_monitoring()
                    finally:
                        examples.safe_close()
            else:
                print("Invalid choice. Please enter 0-8.")
                
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()