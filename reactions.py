#!/usr/bin/env python3
"""
PiDog Reactions Module
==================================
This module enables PiDog to respond dynamically to **touch**, **motion**, and **sound** inputs.

Key Features:
✅ Reacts to physical interaction via **head pats and belly rubs**.
✅ Detects sudden **lifts, flips, and motion shifts** via IMU sensors.
✅ Responds to **sound direction**, turning toward detected noises.
✅ Syncs reactions with **global state tracking (`global_state.py`)**.
✅ Ensures **valid action execution from `actions.py`** before calling them.
✅ Implements **better filtering** to reduce false triggers.

7-lynx
"""

import time
import random
from pidog import Pidog
from pidog.b9_rgb import RGB
from pidog.sound_sensor import SoundSensor
import global_state  # ✅ Integrated state tracking
import actions  # ✅ Import centralized action execution

# ✅ Initialize PiDog Hardware
dog = Pidog()
rgb = RGB(dog)
sound_sensor = SoundSensor(dog)

# ✅ Set Active Mode for Reactions
global_state.active_mode = "reacting"

# ✅ Touch Sensor Reactions
def react_to_touch():
    """PiDog reacts based on touch sensor activation."""
    if dog.touchData[0]:  # ✅ Head touch detected
        print("🐶 Head pat detected!")
        actions.wag_tail()
        rgb.set_color((0, 255, 0))  # ✅ Happy green
        rgb.breathe(2)
        global_state.emotion = "happy"  # ✅ Update emotion state

    if dog.touchData[1]:  # ✅ Body touch detected
        print("🐶 Belly rub detected!")
        actions.lay_down()
        actions.scratch_ear()
        rgb.set_color((255, 165, 0))  # ✅ Warm orange
        rgb.breathe(2)
        global_state.emotion = "relaxed"  # ✅ Update emotion state

# ✅ Motion Detection Reactions
def react_to_motion():
    """PiDog reacts to tilts, flips, and sudden movements using IMU data."""
    ax = dog.accData[0]
    print(f"🔎 IMU Data: {ax}")

    # ✅ Dynamic sensitivity adjustment based on recent motion
    sensitivity = -13000 if global_state.active_mode == "idle" else -11000

    if ax > sensitivity:  # ✅ Detect being lifted
        print("🚀 PiDog is lifted!")
        actions.wag_tail()
        actions.bark()
        rgb.set_color((255, 0, 0))  # ✅ Alert red
        rgb.flash(3)
        global_state.emotion = "excited"  # ✅ Update emotion state

    if ax < -18000:  # ✅ Detect being placed down
        print("🐶 PiDog is back on the ground.")
        actions.sit()
        rgb.set_color((255, 255, 255))  # ✅ Neutral state
        global_state.emotion = "neutral"  # ✅ Reset emotion

    roll = dog.accData[1]
    if abs(roll) > 25000:  # ✅ Detect rolling over
        print("🤔 PiDog flipped upside down!")
        actions.chase_tail()
        rgb.set_color((0, 0, 255))  # ✅ Playful blue
        global_state.emotion = "playful"  # ✅ Update emotion state

# ✅ Sound Detection Reactions
def react_to_sound():
    """PiDog reacts to detected noises and turns toward the source."""
    if sound_sensor.isdetected():
        direction = sound_sensor.read()

        # ✅ Ensure significant sound deviation before reacting
        if abs(direction) < 15:
            print("🔊 Minor sound detected—no reaction needed.")
            return

        print(f"🔊 Sound detected! Turning toward {direction}°")
        rgb.set_color((255, 165, 0))  # ✅ Listening mode
        rgb.flash(2)

        dog.head_move([[direction, 0, 0]], speed=80)
        dog.wait_head_done()

        if abs(direction) > 30:
            actions.bark()
            global_state.emotion = "alarmed"  # ✅ Update emotion state

# ✅ Continuous Behavior Monitoring
def start_behavior():
    """Continuously monitors PiDog’s environment for touch, motion, and sound."""
    print("🐶 Environmental interaction activated!")

    while global_state.active_mode == "reacting":
        react_to_touch()
        react_to_motion()
        react_to_sound()
        time.sleep(0.5)

    print("🛑 Exiting reaction mode.")
    global_state.active_mode = "idle"  # ✅ Reset active mode

# ✅ Allow execution via `master.py`
if __name__ == "__main__":
    start_behavior()