#!/usr/bin/env python3
import time
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)  # Set Guard Mode position
dog.wait_all_done()
time.sleep(0.5)

def detect_movement():
    """Detect movement using ultrasonic sensor."""
    distance = dog.read_distance()
    print(f"Monitoring area... Distance: {distance} cm")
    
    return distance < 100  # Trigger action if something enters range

def guard_mode():
    """Monitor surroundings and react to movement."""
    print("Entering Guard Mode...")

    try:
        while True:
            if detect_movement():
                print("Movement detected! Activating response...")
                dog.do_action("bark", speed=100)  # Alert sound
                dog.wait_all_done()
                time.sleep(0.5)

                dog.do_action("turn_left", step_count=5, speed=80)  # Look around
                dog.wait_all_done()
                time.sleep(0.5)

            else:
                print("No movement detected. Remaining in Guard Mode.")
                time.sleep(1)  # Pause between scans
    
    except KeyboardInterrupt:
        print("Exiting Guard Mode...")
        dog.do_action("stand", speed=50)  # Stop movement safely
        dog.wait_all_done()
        dog.close()  # Shut down Pidog properly

# Start Guard Mode
guard_mode()