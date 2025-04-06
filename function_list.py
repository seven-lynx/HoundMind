#!/usr/bin/env python3
import time
import threading
from pidog import Pidog

# ✅ Initialize PiDog
dog = Pidog()
dog.do_action("stand", speed=120)  # Ensure PiDog is ready
dog.wait_all_done()
time.sleep(0.5)

def list_pidog_functions():
    """List all available functions and attributes for PiDog."""
    print("📜 Listing all available PiDog functions...")

    # Get all functions & attributes
    all_methods = dir(dog)

    # ✅ Filter out internal methods (__methods__) and keep only user-accessible ones
    user_methods = [method for method in all_methods if not method.startswith("__")]

    # ✅ Display available functions
    for method in user_methods:
        print(f"- {method}")

# Run function to list all available PiDog commands
list_pidog_functions()

# ✅ Close PiDog safely
dog.close()