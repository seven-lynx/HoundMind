#!/usr/bin/env python3
"""
PiDog Emotion Module
==================================
This module manages PiDog’s emotional state, adjusting its behavior dynamically through **color changes, movement, and state tracking**.

Key Features:
✅ Expresses emotions using **color-coded LED feedback and movement**.
✅ Ensures **valid action execution** before running commands.
✅ Updates **global state (`global_state.py`) for emotion tracking**.
✅ Implements **fallback action selection for missing behavior commands**.
✅ Tracks **previous emotions** to maintain response continuity.

7-lynx
"""

import time
import random
from pidog import Pidog
from pidog.b9_rgb import RGB
import global_state  # ✅ Integrated state tracking
import actions  # ✅ Import centralized action execution

# ✅ Initialize PiDog hardware
dog = Pidog()
rgb = RGB(dog)

# ✅ Define emotional states and effects
emotions = {
    "happy": {"color": (0, 255, 0), "action": "wag_tail", "head_tilt": 20},
    "sad": {"color": (0, 0, 255), "action": "lay_down", "head_tilt": -30},
    "excited": {"color": (255, 165, 0), "action": "jump_and_wag", "head_tilt": 10},
    "confused": {"color": (255, 255, 0), "action": "tilting_head", "head_tilt": 0},
    "scared": {"color": (255, 0, 0), "action": "tremble", "head_tilt": -20},
    "sleepy": {"color": (75, 0, 130), "action": "snooze", "head_tilt": -40},
    "playful": {"color": (0, 255, 255), "action": "chase_tail", "head_tilt": 15},
    "alarmed": {"color": (255, 0, 0), "action": "bark", "head_tilt": -20},
    "listening": {"color": (255, 165, 0), "action": "tilting_head", "head_tilt": 0},
    "neutral": {"color": (255, 255, 255), "action": "stop_and_stand", "head_tilt": 0}  # ✅ Added neutral state
}

# ✅ Emotion Expression Function (Now Updates `global_state.py`)
def express_emotion(emotion):
    """PiDog displays emotional response through movement and lighting."""
    
    if emotion in emotions:
        print(f"🐶 Expressing emotion: {emotion}")

        # ✅ Update emotion and active mode tracking
        global_state.emotion = emotion
        global_state.active_mode = "expressing_emotion"

        # ✅ Set RGB color based on emotion
        rgb.set_color(emotions[emotion]["color"])
        rgb.breathe(2)

        # ✅ Tilt head based on emotion
        dog.head_move([[emotions[emotion]["head_tilt"], 0, 0]], speed=80)
        dog.wait_head_done()

        # ✅ Execute associated body action
        action_name = emotions[emotion]["action"]
        
        # ✅ Ensure action exists before execution
        if hasattr(actions, action_name):
            getattr(actions, action_name)()
        else:
            print(f"❌ Action `{action_name}` not found in `actions.py`! Selecting a fallback.")
            fallback_action()

        time.sleep(1)

        # ✅ Reset LED to neutral and update transition history
        rgb.set_color((255, 255, 255))
        global_state.interaction_history.append({"timestamp": time.time(), "emotion": emotion})

    else:
        print(f"❌ Unknown emotion `{emotion}`. Try again.")

# ✅ Fallback Action Selection (Now Ensures Only Valid Actions Execute)
def fallback_action():
    """Defines a safe fallback behavior when an emotion’s associated action is missing."""
    default_action = "wag_tail" if global_state.emotion == "happy" else "stop_and_stand"
    print(f"⚠️ Using fallback action: `{default_action}`")

    if hasattr(actions, default_action):
        getattr(actions, default_action)()
    else:
        print("❌ Fallback action missing! Defaulting to standing.")
        actions.stop_and_stand()

# ✅ Allow direct execution for testing
if __name__ == "__main__":
    test_emotions = ["happy", "sad", "excited", "confused", "scared", "sleepy", "playful", "alarmed", "listening", "neutral"]
    for emotion in test_emotions:
        express_emotion(emotion)
        time.sleep(2)