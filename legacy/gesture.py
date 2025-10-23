#!/usr/bin/env python3
import cv2  # OpenCV for gesture recognition
import time
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)
dog.wait_all_done()
time.sleep(0.5)

# Load hand detection model
hand_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_hand.xml")

def detect_gesture():
    """Use AI to recognize hand gestures."""
    cap = cv2.VideoCapture(0)  # Open camera feed
    ret, frame = cap.read()

    if ret:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hands = hand_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

        cap.release()

        if len(hands) > 0:
            hand_x, hand_y, hand_w, hand_h = hands[0]

            if hand_h > 100:
                print("Wave detected! PiDog is following...")
                dog.do_action("forward", step_count=5, speed=100)
            elif hand_h < 50:
                print("Hand raised! PiDog stops.")
                dog.do_action("stand", speed=80)
            else:
                print("Thumbs up detected! PiDog wags its tail.")
                dog.do_action("tail_wag", speed=80)

        else:
            print("No gesture detected. Waiting for interaction.")

def gesture_mode():
    """Continuously detect hand gestures and respond."""
    print("Entering Gesture Recognition Mode...")

    try:
        while True:
            detect_gesture()
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("Exiting Gesture Mode...")
        dog.do_action("stand", speed=50)
        dog.wait_all_done()
        dog.close()

# Start Gesture Mode
gesture_mode()
