#!/usr/bin/env python3
import time
from pidog import Pidog
from pidog.b9_rgb import RGB
from pidog.sound_sensor import SoundSensor

# ✅ Initialize PiDog, RGB, and sound sensor
dog = Pidog()
rgb = RGB(dog)
sound_sensor = SoundSensor(dog)

def detect_sound():
    """Continuously listens for sounds and turns PiDog toward the source."""
    while True:
        if sound_sensor.isdetected():
            direction = sound_sensor.read()
            print(f"🔊 Sound detected! Adjusting direction {direction}°")
            turn_toward_noise(direction)
        time.sleep(0.5)  # ✅ Prevent unnecessary CPU usage

def turn_toward_noise(direction):
    """PiDog tilts head and turns body toward the detected noise."""
    rgb.set_color((255, 165, 0))  # ✅ Alert color (orange)
    rgb.flash(2)

    # ✅ Adjust head toward sound source
    dog.head_move([[direction, 0, 0]], speed=80)
    dog.wait_head_done()

    # ✅ Turn body only for loud noises
    if abs(direction) > 30:
        turn_direction = "right" if direction > 0 else "left"
        print(f"🎯 Turning body toward noise ({direction}°)...")
        globals()[f"turn_{turn_direction}_medium"]()  # ✅ Call function dynamically from `action.py`

    rgb.set_color((255, 255, 255))  # ✅ Reset LED after reaction

# ✅ Allow execution for testing
if __name__ == "__main__":
    detect_sound()