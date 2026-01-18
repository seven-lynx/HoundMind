#!/usr/bin/env python3
import time
import cv2  # OpenCV for AI-assisted tracking
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)  # Ensure Pidog is ready
dog.wait_all_done()
time.sleep(0.5)

# Load pre-trained face detector for AI-assisted tracking
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


def detect_target():
    """Use OpenCV AI to detect a human face."""
    cap = cv2.VideoCapture(0)  # Open camera feed
    ret, frame = cap.read()

    if ret:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # Convert to grayscale
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

        cap.release()  # Release camera

        if len(faces) > 0:
            print("AI detected a human! Preparing to follow...")
            return True
        else:
            print("No target detected. Scanning...")
            return False


def follow_target():
    """Follow a moving target using AI-assisted vision."""
    print("Entering AI-Assisted Follow Mode...")

    try:
        while True:
            if detect_target():
                print("Following target...")
                dog.do_action("forward", step_count=3, speed=120)  # Move toward target
                dog.wait_all_done()
                time.sleep(0.2)

                if dog.read_distance() < 40:
                    print("Too close to target! Adjusting position...")
                    dog.do_action("stand", speed=80)
                    dog.wait_all_done()
                    time.sleep(0.5)

            else:
                print("Target lost. Searching...")
                dog.do_action("turn_right", step_count=3, speed=80)  # Rotate to search
                dog.wait_all_done()
                time.sleep(0.5)

    except KeyboardInterrupt:
        print("Exiting AI-Assisted Follow Mode...")
        dog.do_action("stand", speed=50)  # Stop movement safely
        dog.wait_all_done()
        dog.close()  # Shut down Pidog properly


# Start AI-Assisted Follow Mode
follow_target()
