#!/usr/bin/env python3
import cv2  # OpenCV for facial recognition
import time
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)  # Set Guard Mode position
dog.wait_all_done()
time.sleep(0.5)

# Load facial detection model
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# Store known faces
known_faces = {"owner_face.jpg"}  # Add known face images for recognition

def detect_intruder():
    """Detect faces and compare with known individuals."""
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()

    if ret:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

        cap.release()

        if len(faces) > 0:
            print("Face detected! Checking identity...")
            for (x, y, w, h) in faces:
                face_region = frame[y:y+h, x:x+w]

                # Compare detected face with known faces
                is_known = any(cv2.matchTemplate(face_region, cv2.imread(face), cv2.TM_CCOEFF_NORMED).max() > 0.8 for face in known_faces)

                if is_known:
                    print("Known person detected. PiDog remains calm.")
                    dog.do_action("tail_wag", speed=80)
                else:
                    print("Unknown intruder detected! Sounding alarm!")
                    dog.do_action("bark", speed=100)

        else:
            print("No face detected. PiDog is monitoring.")

def guard_mode():
    """Monitor surroundings and react accordingly."""
    print("Entering AI-Powered Guard Mode...")

    try:
        while True:
            detect_intruder()
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("Exiting Guard Mode...")
        dog.do_action("stand", speed=50)
        dog.wait_all_done()
        dog.close()

# Start Guard Mode
guard_mode()
