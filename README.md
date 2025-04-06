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

git clone https://github.com/your-username/PiDog.git

2️⃣ Navigate to the project folder:

cd PiDog

3️⃣ Install dependencies:

pip install speech_recognition pyaudio

4️⃣ Run the voice command script:

python3 voice_command.py


AI Dream (untested)

This script introduces learning and memory functionality to the Sunfounder PiDog, allowing it to store obstacle locations, track frequently used commands, and adapt behavior over time.

Key Features:

✅ Persistent Memory Storage – Saves past interactions and obstacles in pidog_memory.json. ✅ Obstacle Tracking – Records blocked positions for future avoidance. ✅ Command Learning – Tracks user commands to prioritize the most frequently used ones. ✅ Dream Mode – Periodic self-analysis while idle, allowing PiDog to adjust movement based on past experiences. ✅ Graceful Shutdown – Ensures PiDog safely exits when Dream Mode is interrupted.

How It Works:

    PiDog initializes and stands up.

    Loads past learning data from a JSON file (or creates a new one if missing).

    Records obstacles encountered during operation to refine navigation.

    Tracks voice commands to optimize responses.

    Dream Mode activates when idle, periodically analyzing stored data.

    Adjusts behavior dynamically based on frequently issued commands and blocked paths.

    Safely exits upon interruption, ensuring PiDog stops and saves data.


AI Exploration (untested)

This script enables autonomous exploration for PiDog, allowing it to navigate and react dynamically to obstacles.

Key Features:

✅ Position Tracking – PiDog keeps track of its location using a coordinate system. ✅ Obstacle Detection – Uses distance sensors to detect blocked areas. ✅ Intelligent Route Adjustment – Changes direction when encountering obstacles. ✅ Exploration Mode – Moves forward randomly while scanning surroundings. ✅ Blocked Area Memory – Avoids repeatedly detected obstacles for smarter navigation.

How It Works:

1️⃣ PiDog initializes and starts in a standing position. 2️⃣ Tracks position as it moves. 3️⃣ Detects obstacles using its distance sensor. 4️⃣ Adjusts path by turning left or right when encountering a blocked area. 5️⃣ Continues exploring dynamically until interrupted.


AI Guard (untested)

This script implements a Guard Mode for PiDog using facial recognition to monitor its surroundings and react accordingly.

Key Features:

✅ Facial Recognition – Uses OpenCV’s Haar Cascade model to detect faces. ✅ Intruder Detection – Compares detected faces with a stored database of known individuals. ✅ Behavioral Response – Wags tail when recognizing a familiar face, barks if an unknown intruder is detected. ✅ Continuous Monitoring – Runs a loop checking for faces in real-time. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Guard Mode.

How It Works:

1️⃣ PiDog initializes and assumes a standing position. 2️⃣ Facial detection model loads, allowing real-time recognition. 3️⃣ Captures images using the camera and converts them to grayscale. 4️⃣ Compares detected faces with a set of known images. 5️⃣ Triggers different responses – tail wagging for recognized faces, barking for intruders. 6️⃣ Continuously scans until interrupted, ensuring PiDog remains on guard.

Auto Defense (incomplete)

This script enables Auto-Defense Mode for PiDog, allowing it to detect and react to fast-moving objects that may pose a threat.

Key Features:

✅ Threat Detection – PiDog monitors incoming objects using distance sensors and randomly simulated speed values. ✅ Adaptive Responses – PiDog dodges fast-moving threats or braces if an object is too close. ✅ Continuous Monitoring – Runs in a loop, scanning for threats in real-time. ✅ Emergency Evasion – Performs a quick leftward jump if a high-speed object is detected. ✅ Impact Mitigation – Lowers stance when facing a slow but dangerously close object. ✅ Graceful Shutdown – Ensures PiDog stops safely upon exiting Defense Mode.

How It Works:

1️⃣ PiDog initializes and assumes a standing position. 2️⃣ Reads distance sensor to detect potential threats. 3️⃣ Simulates speed detection for approaching objects. 4️⃣ Decides whether to "dodge" or "brace" based on object proximity and speed. 5️⃣ Continuously scans until interrupted, ensuring PiDog remains defensive.

Companion (untested)

This script enables Companion Mode for PiDog, allowing it to engage in conversational interactions with users using AI-powered speech synthesis and chatbot responses.

Key Features:

✅ Text-to-Speech Integration – Uses pyttsx3 to make PiDog verbally respond to users. ✅ AI Chatbot Responses – Leverages OpenAI’s GPT model to generate conversational replies. ✅ Real-Time Conversation – Continuously listens for user input and responds dynamically. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Companion Mode.
How It Works:

1️⃣ PiDog initializes and stands up in ready mode. 2️⃣ Text-to-Speech engine activates, allowing PiDog to speak responses aloud. 3️⃣ Captures user input, sending prompts to the chatbot API. 4️⃣ PiDog speaks the chatbot-generated response, creating a natural conversation. 5️⃣ Runs continuously until the user enters "exit" or interrupts the program.

Dance (untested)

This script enables Dance Mode for PiDog, allowing it to analyze music and synchronize movement with the beat.

Key Features:

✅ Music Beat Detection – Uses librosa to analyze the rhythm of an audio file. ✅ Dynamic Dance Response – PiDog adapts movement based on the detected BPM. ✅ Fast Beats → PiDog performs energetic wiggles. ✅ Slow Beats → PiDog sways smoothly. ✅ Continuous Dancing – Loops through the song’s beat detection until interrupted. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Dance Mode.

How It Works:

1️⃣ PiDog initializes and stands ready. 2️⃣ Loads an audio file (song.mp3) for beat analysis. 3️⃣ Detects BPM using librosa. 4️⃣ Executes dance moves based on tempo speed. 5️⃣ Continuously syncs dance movements until interrupted.

Emotion (untested)

This script enables Emotion Recognition Mode for PiDog, allowing it to detect facial expressions and respond with interactive behaviors.

Key Features:

✅ Facial Emotion Detection – Uses OpenCV’s Haar Cascade model to identify faces. ✅ Emotion-Based Responses – PiDog reacts differently based on detected expressions. ✅ Happy Face → Tail Wagging – PiDog recognizes joy and responds positively. ✅ Sad Face → Moves Closer + Soft Bark – Comforting response for distant faces. ✅ Neutral Face → Patrol Mode Continues – No strong emotion detected, PiDog resumes patrol. ✅ Continuous Monitoring – Runs in a loop, checking for faces in real-time. ✅ Graceful Shutdown – Ensures PiDog stops safely upon exiting Emotion Mode.

How It Works:

1️⃣ PiDog initializes and stands ready for interaction. 2️⃣ Captures images using the camera and converts them to grayscale. 3️⃣ Detects facial expressions based on position and size. 4️⃣ Triggers different responses – wagging tail, moving closer, barking softly. 5️⃣ Continuously monitors expressions until interrupted, creating an interactive experience.

Follow (untested)

This script enables AI-Assisted Follow Mode for PiDog, allowing it to detect and track human movement using OpenCV.

Key Features:

✅ Human Face Detection – Uses OpenCV’s Haar Cascade model to locate faces in real-time. ✅ Target Following – Moves toward detected individuals using AI-assisted tracking. ✅ Proximity Awareness – Stops or adjusts position if too close to the target. ✅ Search Mode – Rotates to look for a lost target if detection fails. ✅ Continuous Tracking – Runs in a loop, ensuring dynamic movement. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Follow Mode.

How It Works:

1️⃣ PiDog initializes and assumes a standing position. 2️⃣ Scans the environment for a human face using the camera. 3️⃣ Moves forward toward the detected person while maintaining safe distance. 4️⃣ Stops if too close to prevent collisions. 5️⃣ Rotates to search if the target is lost, ensuring continuous tracking.

Function List

This script retrieves and lists all available functions and attributes for PiDog, making it useful for understanding its capabilities.

Key Features:

✅ PiDog Initialization – Starts PiDog and sets it to a ready position. ✅ Function Discovery – Uses Python’s dir() method to list all commands PiDog supports. ✅ Filters Out Internal Methods – Displays only user-accessible functions, removing system methods. ✅ Clean Exit – Ensures PiDog shuts down properly after listing functions.

How It Works:

1️⃣ PiDog initializes and stands ready. 2️⃣ Retrieves all available methods from the PiDog instance. 3️⃣ Filters out system-defined methods, keeping only useful commands. 4️⃣ Prints the full list of user-accessible functions for reference. 5️⃣ Closes PiDog safely, ensuring proper shutdown.

Gesture (untested)

This script enables Gesture Recognition Mode for PiDog, allowing it to respond dynamically to hand movements detected through OpenCV.

Key Features:

✅ AI-Powered Hand Detection – Uses OpenCV’s Haar Cascade model to recognize gestures in real-time. ✅ Interactive Responses – PiDog reacts based on the detected hand movement:

    Wave → Moves Forward

    Raised Hand → Stops

    Thumbs Up → Wags Tail ✅ Continuous Monitoring – Runs in a loop, checking for gestures every second. ✅ Graceful Shutdown – Ensures PiDog stops safely upon exiting Gesture Mode.

How It Works:

1️⃣ PiDog initializes and stands ready. 2️⃣ Captures images using the camera and converts them to grayscale. 3️⃣ Detects hand gestures and analyzes size/movement. 4️⃣ Triggers appropriate response – movement, stopping, or tail wagging. 5️⃣ Continuously scans for gestures until interrupted, ensuring ongoing interaction.

Guard (untested)

This script enables Guard Mode for PiDog, allowing it to monitor its surroundings and react to detected movement using an ultrasonic sensor.

Key Features:

✅ Movement Detection – Uses distance sensors to detect nearby activity. ✅ Automated Response – PiDog barks when movement is detected, serving as an alert system. ✅ Scanning Behavior – PiDog turns left after detecting movement to look around. ✅ Continuous Monitoring – Runs in a loop, keeping PiDog in Guard Mode indefinitely. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Guard Mode.

How It Works:

1️⃣ PiDog initializes and stands in a ready position. 2️⃣ Reads distance sensor to detect nearby movement. 3️⃣ Triggers responses – barking and scanning the area when movement is detected. 4️⃣ Remains in Guard Mode if no movement is detected, checking continuously. 5️⃣ Stops safely upon interruption, ensuring a controlled shutdown.

Maintenance (untested)

This script enables Maintenance Mode for PiDog, allowing it to run periodic diagnostics and log potential issues.

Key Features:

✅ Battery Monitoring – Tracks battery level and warns if critically low. ✅ Motor Diagnostics – Checks PiDog's movement system for malfunctions. ✅ Sensor Health Check – Verifies ultrasonic and camera sensors for failures. ✅ Overheating Detection – Monitors processor temperature and slows movement if too hot. ✅ Connectivity Testing – Ensures stable Wi-Fi or Bluetooth communication. ✅ Automated Logging – Records detected issues in a JSON file for future tracking. ✅ Scheduled System Checks – Runs diagnostics every 5 minutes to maintain PiDog’s functionality. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Maintenance Mode.

How It Works:

1️⃣ PiDog initializes and assumes a standing position. 2️⃣ Loads past maintenance logs or creates a new tracking file. 3️⃣ Runs various system checks for battery, motors, sensors, overheating, and connectivity. 4️⃣ Updates maintenance records if issues are detected. 5️⃣ Repeats checks every 5 minutes, ensuring PiDog remains in top condition. 6️⃣ Stops safely upon interruption, preserving maintenance logs for future analysis.

Mapping

This script enables Autonomous Mapping Mode for PiDog, allowing it to explore, track its movement, detect obstacles, and intelligently navigate around blocked areas.

Key Features:

✅ Position Tracking – PiDog continuously updates its x, y coordinates to map explored areas. ✅ Obstacle Detection & Avoidance – Uses distance sensors to identify barriers and reroute. ✅ Adaptive Navigation – PiDog either retreats or turns based on obstacles detected. ✅ Smart Mapping – Stores previously visited and blocked positions for future navigation. ✅ Return to Start Function – Guides PiDog back to its starting point using stored movement history. ✅ Randomized Scanning – Occasionally triggers scanning behavior for broader mapping coverage. ✅ Graceful Shutdown – Ensures PiDog stops safely upon exiting mapping mode.

How It Works:

1️⃣ PiDog initializes and stands ready. 2️⃣ Moves forward, updating its position in a coordinate system. 3️⃣ Detects obstacles, deciding whether to retreat or find a new path. 4️⃣ Records visited locations, creating a mapped view of the environment. 5️⃣ Occasionally scans new areas, ensuring better mapping coverage. 6️⃣ Returns to start position when interrupted, retracing steps safely.

Memory (untested)

This script enables Learning Mode for PiDog, allowing it to store interactions and adjust behavior based on user feedback.

Key Features:

✅ Behavior Memory Storage – PiDog tracks how often it hears "good dog" or "bad dog". ✅ Emotion-Based Responses – If "good dog" is said more, PiDog wags its tail happily. If "bad dog" is said more, PiDog lowers its ears in sadness. ✅ Interactive Learning – Continuously listens for user input to refine future reactions. ✅ Graceful Shutdown – Ensures PiDog stops safely upon exiting Learning Mode.

How It Works:

1️⃣ PiDog initializes and assumes a ready position. 2️⃣ Tracks user feedback, storing "good dog" and "bad dog" interactions in memory. 3️⃣ Adjusts its emotional response based on past interactions. 4️⃣ Continuously listens for input, refining behavior dynamically. 5️⃣ Stops safely upon interruption, preserving learned behavior for future interactions.

Mic Test

This script tests the microphone and verifies that speech recognition is working correctly.

Key Features:

✅ Microphone Test – Captures audio input from the default microphone. ✅ Background Noise Adjustment – Reduces interference for better speech recognition. ✅ Speech-to-Text Conversion – Uses recognize_google() to process spoken words. ✅ Error Handling – Detects issues like unclear speech or recognition service failures. ✅ Audio Recording – Saves the captured voice input as mic_test.wav for playback. ✅ Standalone Execution – Runs automatically when executed (if __name__ == "__main__").

Patrol

This script enables Autonomous Exploration Mode for PiDog, allowing it to navigate, detect obstacles, and react dynamically while occasionally performing idle animations.

Key Features:

✅ Randomized Speed Variation – PiDog moves forward at different speeds for a more natural flow. ✅ Obstacle Detection & Avoidance – Uses ultrasonic sensors to identify barriers and decide between retreating or reversing direction. ✅ Smart Route Navigation – Turns left or right randomly after encountering obstacles, ensuring efficient exploration. ✅ Idle Animations – Occasionally wags its tail, tilts its head, or barks to simulate natural behavior. ✅ Environmental Scanning – Occasionally stops to scan the area before continuing. ✅ Emergency Stop Functionality – Stops immediately if obstacles are detected mid-movement. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Exploration Mode.

How It Works:

1️⃣ PiDog initializes and assumes a ready position. 2️⃣ Moves forward, adjusting speed randomly to mimic real-world movement. 3️⃣ Detects obstacles, choosing between retreating or turning to avoid collisions. 4️⃣ Occasionally performs idle behaviors, making movement more interactive. 5️⃣ Scans its environment periodically, preventing repetitive paths. 6️⃣ Continues navigating until interrupted, ensuring autonomous movement.

How It Works:

1️⃣ Captures speech using the microphone. 2️⃣ Processes and converts speech to text using Google’s recognition service. 3️⃣ Displays recognized text or reports errors if speech isn't clear. 4️⃣ Saves the recorded audio for later review. 5️⃣ Ensures proper execution when run as a standalone script.

Pet Interaction (untested)

This script enables Pet Interaction Mode for PiDog, allowing it to detect and react to pets using AI-powered pet recognition.

Key Features:

✅ Pet Detection – Uses OpenCV with a custom-trained pet recognition model to identify dogs and cats. ✅ Interactive Responses – PiDog reacts differently based on the detected pet:

    Dog Detected → Tail Wagging & Playful Movement

    Cat Detected → PiDog Stays Still & Avoids Interaction

    Unknown Pet → Cautious Behavior ✅ Simulated AI Pet Classification – Uses a placeholder function to determine pet type (can be expanded with training). ✅ Continuous Scanning – Runs in a loop, checking for pets and responding dynamically. ✅ Graceful Shutdown – Ensures PiDog stops safely upon exiting Pet Mode.

How It Works:

1️⃣ PiDog initializes and stands ready for interaction. 2️⃣ Captures images using the camera and applies pet recognition. 3️⃣ Identifies pets using a trained model (or simulated classification). 4️⃣ Triggers appropriate response – tail wagging, movement, or cautious behavior. 5️⃣ Continuously scans for pets, allowing real-time interaction.

Pidog Voice (untested)

This script enables AI Voice Personality Mode for PiDog, allowing it to listen, recognize, and respond to voice commands in an engaging and conversational manner.

Key Features:

✅ Voice Command Recognition – Uses speech_recognition to detect spoken inputs. ✅ Text-to-Speech Responses – PiDog speaks back using the pyttsx3 text-to-speech engine. ✅ Interactive Personality – Responds with friendly, playful dialogue based on user input. ✅ Emotional Feedback – Wags its tail when complimented and stops moving when told to wait. ✅ Joke-Telling Capability – Has built-in humor to enhance interaction. ✅ Continuous Listening Mode – Runs in an endless loop, awaiting user interactions. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Voice Personality Mode.

How It Works:

1️⃣ PiDog initializes and assumes a standing position. 2️⃣ Uses speech recognition to detect spoken commands. 3️⃣ Processes commands and generates appropriate verbal responses. 4️⃣ Executes physical actions based on recognized phrases (e.g., tail wagging, stopping movement). 5️⃣ Continuously listens for new commands, ensuring dynamic engagement. 6️⃣ Stops safely upon interruption, preserving its state for future use.

Random Action

This script enables automated execution of random Python files within the current directory.

Key Features:

✅ File Scanning – Searches the current directory for .py files. ✅ Random Selection – Chooses a Python script randomly from the available files. ✅ Automated Execution – Runs the selected script using os.system(). ✅ Looping Behavior – Continuously executes a new random script every 30 seconds. ✅ Failsafe Handling – Displays a message if no Python files are found.

How It Works:

1️⃣ Scans the current directory for Python scripts. 2️⃣ Randomly picks one and executes it. 3️⃣ Waits 30 seconds before selecting the next script. 4️⃣ Loops indefinitely, ensuring ongoing script execution. 5️⃣ Stops safely if interrupted, preventing unexpected errors.

This script is useful for automating script testing or cycling through multiple Python programs without manual intervention. 

Smart Patrol

This script enables Autonomous Patrol Mode with collision detection, manual controls, and intelligent movement adjustments for PiDog.

Key Features:

✅ IMU-Based Collision Detection – Uses accelerometer and gyroscope data to identify sudden impacts or excessive tilting. ✅ Evasive Actions – Stops movement and retreats when a collision is detected. ✅ Patrol Mode – Moves forward while actively scanning for obstacles and blocked areas. ✅ Manual Override – Allows the user to control PiDog with terminal commands (left, right, stop, resume). ✅ Real-Time IMU Monitoring – Runs continuously in a background thread for instant collision response. ✅ Adaptive Terrain Handling – Adjusts movement based on detected imbalance using IMU data. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Patrol Mode.

How It Works:

1️⃣ PiDog initializes and stands ready. 2️⃣ Patrol Mode starts, guiding PiDog forward with obstacle detection and avoidance. 3️⃣ IMU Collision Detection actively runs, monitoring for sudden impacts or excessive tilt. 4️⃣ Evasive actions trigger automatically if a collision is detected. 5️⃣ Manual Controls allow user intervention, enabling real-time adjustments. 6️⃣ Continues patrolling until interrupted, ensuring dynamic exploration.

Smarter Patrol

This script enables Autonomous Patrol Mode with IMU-based collision detection, manual control, and intelligent navigation adjustments for PiDog.

Key Features:

✅ IMU-Based Collision Detection – Uses accelerometer and gyroscope data to identify sudden impacts or excessive tilt, triggering evasive actions. ✅ Adaptive Patrol Mode – PiDog continuously moves forward while scanning for obstacles and blocked paths. ✅ Obstacle Avoidance – Dynamically chooses whether to retreat, turn left, or turn right based on obstacle detection. ✅ Manual Override – Users can control PiDog via terminal commands (left, right, stop, resume) for direct intervention. ✅ Real-Time IMU Monitoring – Runs collision checks in a background thread for immediate reaction. ✅ Recalibration Mechanism – Adjusts PiDog’s position based on motion data for accurate tracking. ✅ Emotion-Based Feedback – Uses RGB LED indicators to visually communicate patrol, scanning, blocking, and avoidance behaviors. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Patrol Mode.

How It Works:

1️⃣ PiDog initializes and assumes a standing position. 2️⃣ Patrol Mode activates, guiding PiDog forward with obstacle detection and avoidance. 3️⃣ IMU Collision Detection actively runs, monitoring for sudden impacts or excessive tilt. 4️⃣ Evasive actions trigger automatically if a collision is detected. 5️⃣ Manual control overrides autonomous movement, allowing real-time navigation. 6️⃣ Patrolling continues until interrupted, ensuring dynamic exploration and obstacle adaptation.

Voice Command

This script enables Voice Command Mode for PiDog, allowing it to recognize and execute spoken commands in real-time.

Key Features:

✅ Speech Recognition – Uses Google’s speech recognition engine to process voice commands. ✅ Continuous Listening – Runs indefinitely, awaiting user input via microphone. ✅ Command Execution – PiDog responds dynamically to various voice commands, including movement and interactions. ✅ Emergency Stop Function – Ensures PiDog halts immediately when the user commands it to stop. ✅ Multithreading Support – Runs the voice recognition in a separate thread, allowing PiDog to remain responsive. ✅ Graceful Shutdown – Ensures PiDog stops safely when exiting Voice Mode.

How It Works:

1️⃣ PiDog initializes and stands ready. 2️⃣ Continuously listens for voice input, filtering ambient noise. 3️⃣ Detects spoken commands and matches them to predefined actions. 4️⃣ Executes movement or interactions (e.g., forward, backward, bark, tail wag). 5️⃣ Allows user intervention to manually override autonomous behavior. 6️⃣ Stops safely upon interruption, ensuring PiDog remains controlled.

Voice Patrol

This script enables Autonomous Patrol Mode with Voice Commands for PiDog, allowing it to navigate dynamically while responding to user instructions.

Key Features:

✅ Speech Recognition – Uses speech_recognition to process voice commands. ✅ Autonomous Patrol Mode – PiDog continuously moves while scanning for obstacles. ✅ IMU-Based Position Recalibration – Adjusts PiDog’s location using gyroscope and acceleration data. ✅ Obstacle Detection & Avoidance – Monitors distance sensors to react to obstacles dynamically. ✅ Manual Override – Users can control PiDog via voice or terminal commands (left, right, stop, resume). ✅ Interactive Voice Commands – Recognizes phrases like "come here", "bark", "sit", and "good dog" for engaging interactions. ✅ Real-Time IMU Monitoring – Continuously runs background collision detection and movement adjustments. ✅ Emotion-Based Feedback – Uses RGB LEDs to signal different patrol modes and reactions. ✅ Graceful Shutdown – Ensures PiDog stops safely upon exiting Voice Mode.

How It Works:

1️⃣ PiDog initializes and starts patrolling autonomously. 2️⃣ Scans for obstacles, updating its position dynamically and avoiding blocked areas. 3️⃣ Listens for voice commands, processing speech input in real time. 4️⃣ Executes movement or interactions (e.g., forward, backward, sit, bark). 5️⃣ Uses IMU data to adjust terrain handling, making movement more stable. 6️⃣ Stops safely upon interruption, ensuring controlled shutdown.

More to come!

Contributing

Interested in improving PiDog’s capabilities? Feel free to submit pull requests, add new features, or refine existing functions. Many of these scripts are still untested, and we'd appreciate your feedback as we continue refining.

License

This project is released under the GNU Public License, making it available for the PiDog community to modify and expand upon.
