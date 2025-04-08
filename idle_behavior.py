#!/usr/bin/env python3
import time
import threading
import random
import importlib
from action import snooze, lay_down, bark, wag_tail, jump_and_wag, jump, sit, scratch_ear, push_up, tilting_head
from pidog import Pidog
from pidog.b9_rgb import RGB
from pidog.sound_sensor import SoundSensor

# ✅ Initialize PiDog, RGB, and sound sensor
dog = Pidog()
rgb = RGB(dog)
sound_sensor = SoundSensor(dog)

exit_flag = False  # ✅ Allows controlled exit when needed

# ✅ Fixed rotation list from `action.py`
idle_actions = [snooze, lay_down, bark, wag_tail, jump_and_wag, jump, sit, scratch_ear, push_up, tilting_head]

def listen_for_sound():
    """Continuously listen for incoming sounds and react based on direction."""
    while not exit_flag:
        if sound_sensor.isdetected():
            direction = sound_sensor.read()
            print(f"🔊 Sound detected! Adjusting direction {direction}°")
            react_to_sound(direction)
        time.sleep(0.5)  # ✅ Prevent unnecessary CPU usage

def react_to_sound(direction):
    """PiDog reacts by barking and turning toward sound."""
    rgb.set_color((255, 0, 0))  # ✅ Red flash effect for alertness
    rgb.flash(2)

    dog.head_move([[direction, 0, 0]], speed=80)
    dog.wait_head_done()

    # ✅ Bark if the sound is loud
    if abs(direction) > 30:
        print("🔊 Loud sound detected—PiDog is barking!")
        bark()
        time.sleep(0.5)

    # ✅ Turn toward sound direction using `action.py`
    turn_direction = "right" if direction > 0 else "left"
    globals()[f"turn_{turn_direction}_medium"]()  # ✅ Dynamic function call
    rgb.set_color((255, 255, 255))  # ✅ Reset LED after reaction

def execute_idle_action(action):
    """Safely execute an idle action, retrying with a random action if not found."""
    if action in idle_actions:
        try:
            action()  # ✅ Attempt to execute action
        except Exception as e:
            print(f"❌ Error executing {action.__name__}: {e}")
            new_action = random.choice(idle_actions)
            print(f"🔄 Choosing a new action: {new_action.__name__}")
            new_action()  # ✅ Retry with a different action
    else:
        print(f"❌ Action `{action.__name__}` not found in `action.py`. Selecting a new one.")
        random.choice(idle_actions)()

def start_behavior():
    """PiDog cycles through idle behaviors dynamically."""
    print("🐶 PiDog is entering idle mode...")
    threading.Thread(target=listen_for_sound, daemon=True).start()  # ✅ Start sound listener

    while not exit_flag:
        action = random.choice(idle_actions)
        execute_idle_action(action)  # ✅ Check and execute behavior safely
        time.sleep(random.randint(3, 6))

    print("🔴 Exiting Idle Mode...")
    rgb.set_color((255, 255, 255))
    dog.close()

# ✅ Allow execution via `master.py`
if __name__ == "__main__":
    start_behavior()