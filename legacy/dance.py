#!/usr/bin/env python3
import librosa  # Audio processing for music beat detection
import time
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)
dog.wait_all_done()
time.sleep(0.5)


def detect_beat(file_path):
    """Analyze audio to detect beats."""
    y, sr = librosa.load(file_path)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    print(f"Detected BPM: {tempo}")
    return tempo


def dance_to_music():
    """Sync PiDog's movement to detected music beat."""
    print("Entering Dance Mode...")

    try:
        while True:
            bpm = detect_beat("song.mp3")  # Load song

            if bpm > 120:
                print("Fast beat detected! PiDog dances energetically.")
                dog.do_action("wiggle", speed=100)
            else:
                print("Slow beat detected! PiDog sways smoothly.")
                dog.do_action("sway", speed=80)

            dog.wait_all_done()
            time.sleep(2)

    except KeyboardInterrupt:
        print("Exiting Dance Mode...")
        dog.do_action("stand", speed=50)
        dog.wait_all_done()
        dog.close()


# Start Dance Mode
dance_to_music()
