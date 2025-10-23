raise ImportError("Archived module: memory responsibilities moved to services/state; remove imports.")
#!/usr/bin/env python3
"""
PiDog Memory System (Optimized)
==================================
This module manages **short-term and long-term memory**, allowing PiDog to store experiences,
track patterns, and adjust behaviors accordingly.

Key Features:
✅ **Short-Term Memory:** Stores temporary interactions (recent commands, detected obstacles).
✅ **Long-Term Memory:** Saves important recurring experiences in JSON for persistence.
✅ **Categorized Storage:** Organizes memories into `interactions`, `commands`, and `obstacles`.
✅ **Trend Tracking:** Recognizes frequently used commands and common obstacles.
✅ **Auto-Expiry Mechanism:** Clears outdated short-term memory to maintain efficiency.
✅ **Error Handling & Logging:** Ensures reliable memory operations.

7-lynx
"""

import time
import json
import os
import global_state  # ✅ Integrated state tracking

# ✅ Short-Term Memory (Session-Based)
short_term_memory = {
    "recent_commands": [],
    "recent_obstacles": []
}

# ✅ Persistent Storage for Long-Term Memory
memory_file = "pidog_memory.json"

# ✅ Load existing long-term memory or initialize
if os.path.exists(memory_file):
    with open(memory_file, "r") as file:
        long_term_memory = json.load(file)
else:
    long_term_memory = {
        "interactions": {},
        "commands": {},
        "obstacles": {}
    }

def update_short_term_memory(category, data):
    """Stores short-term memories with auto-expiry handling."""
    if category in short_term_memory:
        short_term_memory[category].append({"timestamp": time.time(), "data": data})

        # ✅ Auto-expiry mechanism (keep only last 10 entries)
        if len(short_term_memory[category]) > 10:
            short_term_memory[category].pop(0)

def update_long_term_memory(category, key):
    """Stores experiences in long-term memory for persistent learning."""
    if category in long_term_memory:
        if key in long_term_memory[category]:
            long_term_memory[category][key] += 1  # ✅ Increment familiarity count
        else:
            long_term_memory[category][key] = 1

    save_memory_to_file()  # ✅ Ensure memory is saved instantly

def save_memory_to_file():
    """Saves long-term memory to disk for persistence."""
    try:
        with open(memory_file, "w") as file:
            json.dump(long_term_memory, file, indent=4)
        print("💾 Long-term memory saved successfully.")
    except Exception as e:
        global_state.error_log.append({"timestamp": time.time(), "error": f"Failed to save memory: {e}"})
        print("❌ Error saving memory!")

def recall_memory(category, key):
    """Retrieves memory entries for decision-making."""
    return long_term_memory.get(category, {}).get(key, 0)

def react_based_on_memory():
    """PiDog adjusts behavior based on long-term interactions."""
    good_dog_count = recall_memory("interactions", "good_dog")
    bad_dog_count = recall_memory("interactions", "bad_dog")

    if good_dog_count > bad_dog_count:
        print("🐶 PiDog feels happy! Wagging tail...")
        global_state.interaction_history.append({"timestamp": time.time(), "event": "happy_response"})
    else:
        print("😟 PiDog feels sad... Lowering ears.")
        global_state.interaction_history.append({"timestamp": time.time(), "event": "sad_response"})

def learning_mode():
    """Continuously learn from interactions and save experiences."""
    print("📖 Entering Learning Mode...")
    
    try:
        while True:
            event = input("Did you say 'good dog' or 'bad dog'? ").strip().lower()
            if event in ["good dog", "bad dog"]:
                key = event.replace(" ", "_")
                update_long_term_memory("interactions", key)  # ✅ Store in long-term memory
                react_based_on_memory()
    
    except KeyboardInterrupt:
        print("🚪 Exiting Learning Mode...")
        global_state.active_mode = "idle"  # ✅ Ensure proper shutdown state tracking
        save_memory_to_file()  # ✅ Save memory before shutdown
        print("💾 Memory saved. PiDog is ready for future learning.")

# ✅ Start Learning Mode
learning_mode()