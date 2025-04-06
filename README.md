PiDog Enhanced Functionality Project 🚀🐶
Expanding the capabilities of the Sunfounder PiDog through custom Python scripts.
Overview

This repository contains an assortment of Python scripts designed to enhance the functionality of the Sunfounder PiDog, transforming it into a smarter, voice-controlled robotic companion capable of autonomous movement, obstacle avoidance, and interactive commands.

Our work includes:

    Voice Command System – Control PiDog using spoken instructions.

    Autonomous Patrol Mode – PiDog explores and navigates while avoiding obstacles.

    Obstacle Detection & Avoidance – Uses distance sensors to intelligently maneuver.

    Gait & Stability Adjustments – Adapts movement based on terrain using IMU data.

    Real-Time Position Tracking – Keeps track of PiDog's movement for structured navigation.

Features
🗣️ Voice Command System

PiDog listens for spoken commands and executes actions such as:

    "move forward" / "go back" – Basic movement controls.

    "turn left" / "turn right" – Rotational commands for direction changes.

    "stop" – Emergency stop that cancels ongoing actions.

    "bark" / "wag tail" – Interactive responses.

    "resume patrol" – Re-engages autonomous movement mode.

🚶 Autonomous Patrol Mode

PiDog patrols its environment while:

    Continuously scanning for obstacles.

    Adjusting movement dynamically based on detected barriers.

    Automatically retreating and re-routing when paths are blocked.

    Logging frequently obstructed positions to improve navigation.

🔎 Obstacle Detection & Avoidance

PiDog's patrol mode includes real-time scanning:

    Forward, left, and right obstacle detection using distance sensors.

    Marked blocked locations where multiple obstacles were detected.

    Smart avoidance maneuvers – PiDog autonomously turns in the safest direction.

🏞️ Gait & Stability Adjustments

PiDog reads IMU sensor data to:

    Detect unstable terrain.

    Slow down movement when imbalance is detected.

    Recalibrate its position dynamically for smoother navigation.

Installation

To use these scripts on your Sunfounder PiDog, follow these steps:

1️⃣ Clone the repository:

git clone https://github.com/your-username/PiDog-Enhanced.git

2️⃣ Navigate to the project folder:

cd PiDog

3️⃣ Install dependencies:

pip install speech_recognition pyaudio

4️⃣ Run the voice command script:

python3 voice_command.py


Usage

    Run voice_command.py to control PiDog using speech recognition.

    Start patrol mode to allow PiDog to autonomously explore its environment:

python3 patrol_script.py

Observe position tracking to ensure accurate movement logging.

More to come!

Contributing

Interested in improving PiDog’s capabilities? Feel free to submit pull requests, add new features, or refine existing functions. Many of these scripts are still untested, and we'd appreciate your feedback as we continue refining.

License

This project is released under the GNU Public License, making it available for the PiDog community to modify and expand upon.
