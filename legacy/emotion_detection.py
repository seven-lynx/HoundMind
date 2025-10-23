#!/usr/bin/env python3
import cv2  # OpenCV for emotion recognition
import time
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)  # Ensure PiDog is ready
dog.wait_all_done()
time.sleep(0.5)

# Load facial emotion detection model (OpenCV default)
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

def detect_emotion():
    """Use AI to analyze facial expressions and respond emotionally."""
    cap = cv2.VideoCapture(0)  # Open camera feed
    ret, frame = cap.read()

    if ret:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # Convert to grayscale
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

        cap.release()  # Release camera

        if len(faces) > 0:
            # Simulated emotion analysis based on face position/size
            face_x, face_y, face_w, face_h = faces[0]

            if face_w > 150:  # Large face = closer = likely happy
                print("Detected happy face! Wagging tail...")
                dog.do_action("tail_wag", speed=100)

            elif face_w < 100:  # Smaller face = distant = likely sad
                print("Detected sad face! Moving closer to comfort...")
                dog.do_action("forward", step_count=3, speed=80)
                dog.wait_all_done()
                dog.do_action("bark", speed=50)  # Soft comforting sound

            else:  # Neutral face
                print("Neutral expression detected. Continuing patrol.")

        else:
            print("No face detected. Waiting for interaction.")

def emotion_mode():
    """Continuously detect emotions and respond."""
    print("Entering AI Emotional Recognition Mode...")

    try:
        while True:
            detect_emotion()
            time.sleep(1)  # Small delay between scans
    
    except KeyboardInterrupt:
        print("Exiting Emotion Mode...")
        dog.do_action("stand", speed=50)  # Stop movement safely
        dog.wait_all_done()
        dog.close()  # Shut down Pidog properly

# Start AI Emotional Mode
emotion_mode()
