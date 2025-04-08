#!/usr/bin/env python3
import time
import random
from pidog import Pidog
from pidog.b9_rgb import RGB

# ✅ Initialize PiDog and RGB system
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

def express_emotion(emotion):
    """PiDog displays emotional response through movement and lighting."""
    if emotion in emotions:
        print(f"🐶 Expressing emotion: {emotion}")

        # ✅ Set RGB color based on emotion
        rgb.set_color(emotions[emotion]["color"])
        rgb.breathe(2)

        # ✅ Tilt head based on emotion
        dog.head_move([[emotions[emotion]["head_tilt"], 0, 0]], speed=80)
        dog.wait_head_done()

        # ✅ Perform body action
        action_name = emotions[emotion]["action"]
        action_function = globals().get(action_name)  # ✅ Call function dynamically from `action.py`
        
        if action_function:
            action_function()
        else:
            print(f"❌ Action `{action_name}` not found in `action.py`! Selecting a random action.")
            random.choice(list(emotions.values()))["action"]()  # ✅ Pick a random fallback action
        
        time.sleep(1)
        rgb.set_color((255, 255, 255))  # ✅ Reset LED to neutral
    else:
        print(f"❌ Unknown emotion `{emotion}`. Try again.")

# ✅ Allow direct execution for testing
if __name__ == "__main__":
    test_emotions = ["happy", "sad", "excited", "confused", "scared", "sleepy", "playful", "alarmed", "listening", "neutral"]
    for emotion in test_emotions:
        express_emotion(emotion)
        time.sleep(2)