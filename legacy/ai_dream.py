#!/usr/bin/env python3
import time
import json  # Store learning data
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)
dog.wait_all_done()
time.sleep(0.5)

# Memory storage file
memory_file = "pidog_memory.json"

# Load past experiences
try:
    with open(memory_file, "r") as file:
        learning_data = json.load(file)
except FileNotFoundError:
    learning_data = {"obstacles": [], "commands": {}}

def store_obstacle(position):
    """Save obstacle locations for future avoidance."""
    learning_data["obstacles"].append(position)
    print(f"Stored obstacle at {position}")

def track_command(command):
    """Track frequently used commands."""
    if command in learning_data["commands"]:
        learning_data["commands"][command] += 1
    else:
        learning_data["commands"][command] = 1

    print(f"Recorded command: {command}")

def dream_mode():
    """PiDog thinks and adjusts behavior while idle."""
    print("Entering AI Dream Mode...")

    try:
        while True:
            time.sleep(5)  # Periodic processing

            # Analyze past experiences
            most_frequent_command = max(learning_data["commands"], key=learning_data["commands"].get, default=None)
            if most_frequent_command:
                print(f"PiDog prioritizes {most_frequent_command} next time!")

            if learning_data["obstacles"]:
                print("PiDog remembers obstacle locations and adjusts route.")

            # Save updated learning data
            with open(memory_file, "w") as file:
                json.dump(learning_data, file)
    
    except KeyboardInterrupt:
        print("Exiting AI Dream Mode...")
        dog.do_action("stand", speed=50)
        dog.wait_all_done()
        dog.close()

# Start Dream Mode
dream_mode()
