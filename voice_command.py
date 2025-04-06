#!/usr/bin/env python3
import speech_recognition as sr  # Speech recognition library
import threading
import time
from pidog import Pidog

# Initialize PiDog
dog = Pidog()
dog.do_action("stand", speed=80)  # Ensure PiDog is ready
dog.wait_all_done()
time.sleep(0.5)

def listen_for_command():
    """Continuously listen for voice commands."""
    recognizer = sr.Recognizer()

    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source)
        print("Listening for commands...")

        while True:
            try:
                audio = recognizer.listen(source)  # Remove timeout for continuous listening
                command = recognizer.recognize_google(audio).lower()
                print(f"Detected speech: {command}")
                process_command(command)  # Execute detected command
                    
            except sr.UnknownValueError:
                print("Could not understand speech.")
            except sr.RequestError:
                print("Speech recognition service error.")

def stop_movement():
    """Stops PiDog immediately, ensuring it's in a ready state for further commands."""
    print("Emergency stop activated! PiDog is standing and awaiting commands.")
    dog.do_action("stand", speed=120)  # Stand up immediately
    dog.wait_all_done()

def process_command(command):
    """Interpret and execute voice commands"""
    if not command:
        return

    if command in ["come here", "come", "go forward"]:
        print("PiDog heard you! Moving forward...")
        dog.do_action("forward", step_count=5, speed=120)

    elif command in ["backward", "move back", "go back"]:
        print("PiDog moving backward...")
        dog.do_action("backward", step_count=5, speed=120)

    elif command in ["stop", "halt", "freeze", "stop moving"]:
        stop_movement()

    elif command in ["bark", "speak"]:
        print("PiDog barking!")
        dog.do_action("bark", speed=100)

    elif command in ["turn left", "go left"]:
        print("PiDog turning left!")
        dog.do_action("turn_left", step_count=5, speed=200)

    elif command in ["turn right", "go right"]:
        print("PiDog turning right!")
        dog.do_action("turn_right", step_count=5, speed=200)

    elif command in ["lay down", "lie down"]:
        print("PiDog lying down...")
        dog.do_action("lay_down", speed=80)

    elif command in ["good dog", "great job"]:
        print("PiDog wags its tail in excitement!")
        dog.do_action("tail_wag", speed=50)

    elif command in ["turn around"]:
        print("PiDog turns to face the opposite direction")
        dog.do_action("turn_right", step_count=12, speed=200)

    else:
        print("Unknown command. Try again.")

# Run voice command detection in a separate thread
voice_thread = threading.Thread(target=listen_for_command, daemon=True)
voice_thread.start()

# Keep PiDog active while listening
try:
    while True:
        time.sleep(1)  # Keep the main thread alive

except KeyboardInterrupt:
    print("Exiting Voice Command Mode...")
    stop_movement()  # Ensures PiDog stops safely before exiting
    dog.close()  # Shut down PiDog properly