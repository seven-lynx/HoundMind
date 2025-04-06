#!/usr/bin/env python3
import time
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)
dog.wait_all_done()
time.sleep(0.5)

# Memory storage
behavior_memory = {}

def update_memory(event):
    """Store interactions for future reactions."""
    if event in behavior_memory:
        behavior_memory[event] += 1
    else:
        behavior_memory[event] = 1

def react_based_on_memory():
    """PiDog adjusts behavior based on past interactions."""
    if behavior_memory.get("good_dog", 0) > behavior_memory.get("bad_dog", 0):
        print("PiDog feels happy! Wagging tail...")
        dog.do_action("tail_wag", speed=100)
    else:
        print("PiDog feels sad... Lowering ears.")
        dog.do_action("lower_ears", speed=50)

def learning_mode():
    """Continuously learn from interactions."""
    print("Entering Learning Mode...")
    
    try:
        while True:
            event = input("Did you say 'good dog' or 'bad dog'? ").strip().lower()
            if event in ["good dog", "bad dog"]:
                update_memory(event.replace(" ", "_"))
                react_based_on_memory()
    
    except KeyboardInterrupt:
        print("Exiting Learning Mode...")
        dog.do_action("stand", speed=50)
        dog.wait_all_done()
        dog.close()

# Start Learning Mode
learning_mode()