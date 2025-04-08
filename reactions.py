#!/usr/bin/env python3
import time
import random
from pidog import Pidog
from pidog.b9_rgb import RGB
from pidog.sound_sensor import SoundSensor
from action import wag_tail, bark, lay_down, sit, tilting_head, scratch_ear, chase_tail, tremble

# ✅ Initialize PiDog
dog = Pidog()
rgb = RGB(dog)
sound_sensor = SoundSensor(dog)

def react_to_touch():
    """PiDog reacts based on touch sensor activation."""
    if dog.touchData[0]:  # ✅ Head touch detected
        print("🐶 Head pat detected!")
        wag_tail()
        rgb.set_color((0, 255, 0))  # ✅ Happy green
        rgb.breathe(2)
    
    if dog.touchData[1]:  # ✅ Body touch detected
        print("🐶 Belly rub detected!")
        lay_down()
        scratch_ear()
        rgb.set_color((255, 165, 0))  # ✅ Warm orange
        rgb.breathe(2)

def react_to_motion():
    """PiDog reacts to tilts, flips, and sudden movements using IMU data."""
    ax = dog.accData[0]
    print(f"🔎 IMU Data: {ax}")

    if ax > -13000:  # ✅ Detect being lifted
        print("🚀 PiDog is lifted!")
        wag_tail()
        bark()
        rgb.set_color((255, 0, 0))  # ✅ Alert red
        rgb.flash(3)

    if ax < -18000:  # ✅ Detect being placed down
        print("🐶 PiDog is back on the ground.")
        sit()
        rgb.set_color((255, 255, 255))  # ✅ Neutral state

    roll = dog.accData[1]
    if abs(roll) > 25000:  # ✅ Detect rolling over
        print("🤔 PiDog flipped upside down!")
        chase_tail()
        rgb.set_color((0, 0, 255))  # ✅ Playful blue

def react_to_sound():
    """PiDog reacts to detected noises and turns toward the source."""
    if sound_sensor.isdetected():
        direction = sound_sensor.read()
        print(f"🔊 Sound detected! Turning toward {direction}°")
        rgb.set_color((255, 165, 0))  # ✅ Listening mode
        rgb.flash(2)

        dog.head_move([[direction, 0, 0]], speed=80)
        dog.wait_head_done()

        if abs(direction) > 30:
            bark()

def start_behavior():
    """Continuously monitors PiDog’s environment for touch, motion, and sound."""
    print("🐶 Environmental interaction activated!")

    while True:
        react_to_touch()
        react_to_motion()
        react_to_sound()
        time.sleep(0.5)

# ✅ Allow execution via `master.py`
if __name__ == "__main__":
    start_behavior()