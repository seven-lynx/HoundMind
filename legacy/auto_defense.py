#!/usr/bin/env python3
import time
import random
from pidog import Pidog

# Initialize PiDog
dog = Pidog()
dog.do_action("stand", speed=80)
dog.wait_all_done()
time.sleep(0.5)

def detect_threat():
    """Monitor surroundings for fast-moving objects."""
    distance = dog.read_distance()
    speed_of_object = random.randint(50, 200)  # Simulated speed detection

    print(f"Object detected at {distance} cm, approaching at speed {speed_of_object}.")

    if distance < 20 and speed_of_object > 100:
        return "dodge"
    elif distance < 10 and speed_of_object <= 100:
        return "brace"
    return None

def auto_defense_mode():
    """React dynamically to potential threats."""
    print("Entering Auto-Defense Mode...")

    try:
        while True:
            threat_response = detect_threat()
            
            if threat_response == "dodge":
                print("⚠️ Fast-moving object detected! Dodging...")
                dog.do_action("jump_left", speed=120)  # Quick dodge left
                dog.wait_all_done()

            elif threat_response == "brace":
                print("⚠️ Object is very close! Bracing for impact...")
                dog.do_action("brace", speed=80)  # Lower stance to reduce impact
                
            time.sleep(1)  # Continuous monitoring
    
    except KeyboardInterrupt:
        print("Exiting Auto-Defense Mode...")
        dog.do_action("stand", speed=50)
        dog.wait_all_done()
        dog.close()

# Start Auto-Defense Mode
auto_defense_mode()
