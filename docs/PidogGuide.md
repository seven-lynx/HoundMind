# The Ultimate PiDog Programming Guide

> A comprehensive programming reference for the SunFounder PiDog robotic dog. This guide focuses on Python coding with detailed examples and complete API documentation.

- Last updated: 2025-10-22
- Target audience: Python developers and robotics enthusiasts
- Focus: Complete programming reference with working code examples
- References: Official documentation and GitHub repository (see Resources)

---

## Table of Contents

- [1. Introduction](#1-introduction)
  - [1.1 What is PiDog?](#11-what-is-pidog)
  - [1.2 Standard vs V2: Key Differences](#12-standard-vs-v2-key-differences)
  - [1.3 Capabilities at a Glance](#13-capabilities-at-a-glance)
  - [1.4 Who This Guide Is For](#14-who-this-guide-is-for)
- [2. What’s in the Box](#2-whats-in-the-box)
  - [2.1 Parts Checklist](#21-parts-checklist)
  - [2.2 Tools You’ll Need](#22-tools-youll-need)
- [3. Before You Start](#3-before-you-start)
  - [3.1 Compatibility Matrix (RPi 3/4/5, Zero 2W)](#31-compatibility-matrix-rpi-345-zero-2w)
  - [3.2 Workspace, Safety, and ESD](#32-workspace-safety-and-esd)
  - [3.3 Battery, Power, and Runtime Notes](#33-battery-power-and-runtime-notes)
- [4. Assembly](#4-assembly)
  - [4.1 Assembly Videos (Watch First)](#41-assembly-videos-watch-first)
  - [4.2 Mechanical Assembly Overview](#42-mechanical-assembly-overview)
  - [4.3 Cable Management and Servo Routing](#43-cable-management-and-servo-routing)
  - [4.4 Final Checks Before Power-On](#44-final-checks-before-power-on)
- [5. First Boot and OS Setup](#5-first-boot-and-os-setup)
  - [5.1 Flash Raspberry Pi OS](#51-flash-raspberry-pi-os)
  - [5.2 Headless Setup (Wi‑Fi, SSH)](#52-headless-setup-wi-fi-ssh)
  - [5.3 Enable Interfaces (I2C, Camera, Audio)](#53-enable-interfaces-i2c-camera-audio)
  - [5.4 Audio Driver / I2S AMP](#54-audio-driver--i2s-amp)
- [6. Install Software](#6-install-software)
  - [6.1 System Packages](#61-system-packages)
  - [6.2 robot-hat Library](#62-robot-hat-library)
  - [6.3 vilib (Picamera2)](#63-vilib-picamera2)
  - [6.4 pidog Python Library](#64-pidog-python-library)
  - [6.5 i2samp Script](#65-i2samp-script)
  - [6.6 Verify Installation](#66-verify-installation)
- [7. Calibration and Checks](#7-calibration-and-checks)
  - [7.1 Servo Zeroing and ID Map](#71-servo-zeroing-and-id-map)
  - [7.2 IMU Orientation and Leveling](#72-imu-orientation-and-leveling)
  - [7.3 Sensors Test (Touch, Ultrasonic, Sound Direction)](#73-sensors-test-touch-ultrasonic-sound-direction)
  - [7.4 RGB Light Board Test](#74-rgb-light-board-test)
- [8. First Run](#8-first-run)
  - [8.1 Run the First Demo](#81-run-the-first-demo)
  - [8.2 Built‑in Actions and Sounds](#82-built-in-actions-and-sounds)
- [9. Python SDK Essentials](#9-python-sdk-essentials)
  - [9.1 Project Structure and Examples](#91-project-structure-and-examples)
  - [9.2 Pidog Class: Lifecycle and Patterns](#92-pidog-class-lifecycle-and-patterns)
  - [9.3 Motion API: Pose, Gaits, and Balance](#93-motion-api-pose-gaits-and-balance)
  - [9.4 LEDs and Expressions](#94-leds-and-expressions)
  - [9.5 Audio Playback and Tones](#95-audio-playback-and-tones)
  - [9.6 Sensors API (Camera, IMU, Touch, Ultrasonic, Sound Direction)](#96-sensors-api-camera-imu-touch-ultrasonic-sound-direction)
  - [9.7 Event Loops, Timing, and Cleanup](#97-event-loops-timing-and-cleanup)
  - [9.8 Error Handling and Safety Stops](#98-error-handling-and-safety-stops)
  - [9.9 Coding the PiDog: Overview](#99-coding-the-pidog-overview)
  - [9.10 Project Template](#910-project-template)
  - [9.11 Running Official Examples](#911-running-official-examples)
  - [9.12 Patterns, Safety, and Shutdown](#912-patterns-safety-and-shutdown)
- [10. Vision and Perception](#10-vision-and-perception)
  - [10.1 Camera Setup with Picamera2/Vilib](#101-camera-setup-with-picamera2vilib)
  - [10.2 Color/Object Tracking](#102-colorobject-tracking)
  - [10.3 Face Detection](#103-face-detection)
- [11. Speech and Audio](#11-speech-and-audio)
  - [11.1 TTS Engines: eSpeak, pico2wave, Piper, OpenAI](#111-tts-engines-espeak-pico2wave-piper-openai)
  - [11.2 STT Engines: Vosk (Offline)](#112-stt-engines-vosk-offline)
  - [11.3 Microphone and Speaker Diagnostics](#113-microphone-and-speaker-diagnostics)
- [12. AI Integrations and Agents](#12-ai-integrations-and-agents)
  - [12.1 Local LLM with Ollama](#121-local-llm-with-ollama)
  - [12.2 Connecting to Online LLMs](#122-connecting-to-online-llms)
  - [12.3 Local Voice Chatbot](#123-local-voice-chatbot)
  - [12.4 AI Voice Assistant Dog (E2E)](#124-ai-voice-assistant-dog-e2e)
- [13. Example Projects](#13-example-projects)
  - [13.1 Fun Python Projects](#131-fun-python-projects)
  - [13.2 Easy Coding Recipes](#132-easy-coding-recipes)
  - [13.3 GPT/LLM Sample Apps](#133-gptllm-sample-apps)
  - [13.4 Easy Coding (13 scripts)](#134-easy-coding-13-scripts)
    - [13.4.1 Initialization](#1341-initialization)
    - [13.4.2 Leg Move](#1342-leg-move)
    - [13.4.3 Head Move](#1343-head-move)
    - [13.4.4 Tail Move](#1344-tail-move)
    - [13.4.5 Stop All Actions](#1345-stop-all-actions)
    - [13.4.6 Do Preset Action](#1346-do-preset-action)
    - [13.4.7 Speak](#1347-speak)
    - [13.4.8 Read Distance](#1348-read-distance)
    - [13.4.9 RGB Strip](#1349-rgb-strip)
    - [13.4.10 IMU Read](#13410-imu-read)
    - [13.4.11 Sound Direction Detect](#13411-sound-direction-detect)
    - [13.4.12 Dual Touch (Pat Head)](#13412-dual-touch-pat-head)
    - [13.4.13 More](#13413-more)
- [14. Hardware Reference](#14-hardware-reference)
  - [14.1 Robot HAT: Power, Audio, I/O](#141-robot-hat-power-audio-io)
  - [14.2 Servo Layout (12 DOF) and IDs](#142-servo-layout-12-dof-and-ids)
  - [14.3 Camera Module](#143-camera-module)
  - [14.4 Sound Direction Sensor](#144-sound-direction-sensor)
  - [14.5 6‑DOF IMU](#145-6-dof-imu)
  - [14.6 Dual Touch Sensor](#146-dual-touch-sensor)
  - [14.7 11‑Channel RGB Light Board](#147-11-channel-rgb-light-board)
  - [14.8 Ultrasonic Module](#148-ultrasonic-module)
  - [14.9 3‑Pin Battery and Power](#149-3-pin-battery-and-power)
- [15. Power, Care, and Maintenance](#15-power-care-and-maintenance)
  - [15.1 Charging and Power Cycling](#151-charging-and-power-cycling)
  - [15.2 Firmware/HAT Updates (If Applicable)](#152-firmwarehat-updates-if-applicable)
  - [15.3 Storage, Transport, and Cleaning](#153-storage-transport-and-cleaning)
- [16. Troubleshooting and FAQ](#16-troubleshooting-and-faq)
  - [16.1 Installation/Dependency Issues](#161-installationdependency-issues)
  - [16.2 Walking or Balance Problems](#162-walking-or-balance-problems)
  - [16.3 Camera Not Working](#163-camera-not-working)
  - [16.4 Speaker or Microphone Issues](#164-speaker-or-microphone-issues)
  - [16.5 Sensors Not Responding](#165-sensors-not-responding)
  - [16.6 LED Board Not Lighting or Syncing](#166-led-board-not-lighting-or-syncing)
  - [16.7 Power and Battery Questions](#167-power-and-battery-questions)
- [17. Networking and Remote Access (Appendix)](#17-networking-and-remote-access-appendix)
  - [17.1 Find the Pi’s IP Address](#171-find-the-pis-ip-address)
  - [17.2 OpenSSH on Windows PowerShell](#172-openssh-on-windows-powershell)
  - [17.3 PuTTY](#173-putty)
  - [17.4 File Transfer with FileZilla](#174-file-transfer-with-filezilla)
- [18. Development Tips](#18-development-tips)
  - [18.1 Project Layout and Virtual Envs](#181-project-layout-and-virtual-envs)
  - [18.2 Logging and Debugging](#182-logging-and-debugging)
  - [18.3 Minimal Testing Strategy](#183-minimal-testing-strategy)
- [19. Community and Support](#19-community-and-support)
  - [19.1 Official Docs](#191-official-docs)
  - [19.2 GitHub Repository](#192-github-repository)
  - [19.3 Forum and Social Channels](#193-forum-and-social-channels)
  - [19.4 Email Support](#194-email-support)
- [20. Changelog (for Your Notes)](#20-changelog-for-your-notes)
- [21. License and Credits](#21-license-and-credits)
- [22. Glossary](#22-glossary)
- [23. Index](#23-index)
- [23. Index](#23-index)
- [24. Pidog API Reference (Master List)](#24-pidog-api-reference-master-list)

---

## 1. Introduction

### 1.1 What is PiDog?

### 1.2 Standard vs V2: Key Differences

### 1.3 Capabilities at a Glance

### 1.4 Who This Guide Is For

## 2. What’s in the Box

### 2.1 Parts Checklist

### 2.2 Tools You’ll Need

## 3. Before You Start

### 3.1 Compatibility Matrix (RPi 3/4/5, Zero 2W)

### 3.2 Workspace, Safety, and ESD

### 3.3 Battery, Power, and Runtime Notes

## 4. Assembly

### 4.1 Assembly Videos (Watch First)

### 4.2 Mechanical Assembly Overview

### 4.3 Cable Management and Servo Routing

### 4.4 Final Checks Before Power-On

## 5. First Boot and OS Setup

### 5.1 Flash Raspberry Pi OS

### 5.2 Headless Setup (Wi‑Fi, SSH)

### 5.3 Enable Interfaces (I2C, Camera, Audio)

### 5.4 Audio Driver / I2S AMP

## 6. Install Software

### 6.1 System Packages

### 6.2 robot-hat Library

### 6.3 vilib (Picamera2)

### 6.4 pidog Python Library

### 6.5 i2samp Script

### 6.6 Verify Installation

## 7. Calibration and Checks

### 7.1 Servo Zeroing and ID Map

### 7.2 IMU Orientation and Leveling

### 7.3 Sensors Test (Touch, Ultrasonic, Sound Direction)

### 7.4 RGB Light Board Test

## 8. First Run

### 8.1 Run the First Demo

### 8.2 Built‑in Actions and Sounds

## 9. Python Programming

> **� Complete Programming Guide:** All programming content has been moved to the dedicated **[`PIDOG_PROGRAMMING_GUIDE.md`](./PIDOG_PROGRAMMING_GUIDE.md)**

This comprehensive programming guide includes:

- ✅ **Complete API Coverage** - Every method, parameter, and usage pattern
- ✅ **Working Code Examples** - Copy-paste ready code for all features
- ✅ **Safety & Error Handling** - Production-ready patterns and best practices  
- ✅ **Advanced Patterns** - Event loops, state machines, sensor fusion
- ✅ **Project Templates** - Get started quickly with proven structures
- ✅ **Debugging Tools** - Monitor and troubleshoot your PiDog programs

### Quick Programming Resources

| Resource | Description | Best For |
|----------|-------------|----------|
| **[`pidog_programming_examples.py`](../examples/pidog_programming_examples.py)** | Interactive examples with menu system | Learning by running code |
| **[`api_reference.md`](./api_reference.md)** | Complete API documentation | Reference during development |
| **[`packmind/orchestrator.py`](../packmind/orchestrator.py)** | Advanced AI behavior demo | Understanding complex patterns |
| **[`PIDOG_PROGRAMMING_GUIDE.md`](./PIDOG_PROGRAMMING_GUIDE.md)** | Complete programming guide | Comprehensive learning |

### Programming Topics Covered

The dedicated programming guide includes detailed coverage of:

- **Complete API Reference** - Every method, parameter, return value, and usage pattern
- **Movement Control** - Preset actions, low-level servo control, and coordinated movement
- **Sensor Integration** - IMU, ultrasonic, sound direction, and touch sensors with working examples
- **Audio & LED Systems** - Sound effects, RGB LED control, and synchronized behaviors
- **Advanced Patterns** - Event loops, state machines, sensor fusion, and AI behaviors  
- **Safety & Error Handling** - Production-ready error handling and emergency stop patterns
- **Project Templates** - Copy-paste templates for different types of PiDog projects
- **Debugging Tools** - Status monitoring, performance measurement, and troubleshooting

### Quick Code Example

```python
from pidog import Pidog

def basic_pet_behavior():
    dog = Pidog()
    try:
        # Stand up and greet
        dog.do_action("stand", speed=60)
        dog.speak("woohoo", volume=80)
        dog.rgb_strip.set_mode("breath", "green", brightness=0.8)
        
        # Interactive behavior loop
        while True:
            touch = dog.dual_touch.read()
            if touch == "L":
                dog.do_action("wag_tail", step_count=5, speed=90)
            elif touch == "R": 
                dog.speak("pant", volume=70)
                
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        dog.close()

if __name__ == "__main__":
    basic_pet_behavior()
```

> **💡 Pro Tip:** Start with the programming guide's project templates - they include proper error handling and safety patterns that will save you debugging time!

## 10. Vision and Perception

### 10.1 Camera Setup with Picamera2/Vilib

### 10.2 Color/Object Tracking

### 10.3 Face Detection

## 11. Speech and Audio

### 11.1 TTS Engines: eSpeak, pico2wave, Piper, OpenAI

### 11.2 STT Engines: Vosk (Offline)

### 11.3 Microphone and Speaker Diagnostics

## 12. AI Integrations and Agents

### 12.1 Local LLM with Ollama

### 12.2 Connecting to Online LLMs

### 12.3 Local Voice Chatbot

### 12.4 AI Voice Assistant Dog (E2E)

## 13. Example Projects

### 13.1 Fun Python Projects

### 13.2 Easy Coding Recipes

### 13.3 GPT/LLM Sample Apps

### 13.4 Easy Coding (13 scripts)

Below are placeholders for each quick recipe from the "Easy Coding" track. Fill each with steps to run, expected behavior, and variations.

Official tutorials with reference code (verbatim in the links):
- 1. PiDog Initialization — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b1_init.html
- 2. Leg Move — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b2_leg_move.html
- 3. Head Move — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b3_head_move.html
- 4. Tail Move — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b4_tail_move.html
- 5. Stop All Actions — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b5_stop_action.html
- 6. Do Preset Action — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b6_preset_action.html
- 7. PiDog Speak — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b7_speak.html
- 8. Read Distance — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b8_read_distance.html
- 9. PiDog RGB Strip — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b9_rgb.html
- 10. IMU Read — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b10_imu.html
- 11. Sound Direction Detect — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b11_sound_direction.html
- 12. Pat the PiDog’s Head — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b12_dual_touch.html
- 13. More — https://docs.sunfounder.com/projects/pidog/en/latest/python/py_b13_more.html

#### 13.4.1 Initialization
Minimal program that brings PiDog to life, shows a few poses, then exits safely.

```python
from pidog import Pidog
import time


def main():
  dog = Pidog()
  try:
    # Default power-up state, then try a few poses
    dog.do_action("stand", speed=60)
    dog.wait_all_done()
    time.sleep(0.5)

    dog.do_action("half_sit", speed=50)
    dog.wait_all_done()
    time.sleep(0.5)

    dog.do_action("sit", speed=50)
    dog.wait_all_done()
    time.sleep(0.5)
  finally:
    dog.stop_and_lie()
    dog.close()


if __name__ == "__main__":
  main()
```

Variations:
- Provide custom initial angles at construction for unique stances.
- Set an LED mood on start (see RGB section).

#### 13.4.2 Leg Move
Demonstrates immediate vs queued leg actions, waiting, and stopping.

```python
from pidog import Pidog
import time


HALF_STAND = [[45, 10, -45, -10, 45, 10, -45, -10]]
PUSHUP_PREP = [[45, 35, -45, -35, 80, 70, -80, -70]]
PUSHUP_CYCLE = [
  [90, -30, -90, 30, 80, 70, -80, -70],
  [45, 35, -45, -35, 80, 70, -80, -70],
]


def main():
  dog = Pidog()
  try:
    # Immediate action
    dog.legs_move(HALF_STAND, speed=50)
    dog.wait_legs_done()
    time.sleep(0.3)

    # Queue multiple angle groups (non-blocking fill)
    dog.legs_move(PUSHUP_PREP, immediately=False, speed=30)
    for _ in range(10):
      dog.legs_move(PUSHUP_CYCLE, immediately=False, speed=40)

    # Let it run for a short period
    time.sleep(5)

    # Stop legs and return to a neutral pose
    dog.legs_stop()
    dog.legs_move(HALF_STAND, speed=50)
    dog.wait_legs_done()
  finally:
    dog.stop_and_lie()
    dog.close()


if __name__ == "__main__":
  main()
```

Tips:
- Keep angles within safe bounds to prevent servo strain.
- Use wait_legs_done() to coordinate head/tail with gait phases.

#### 13.4.3 Head Move
Nod, shake, and keep the head level using pitch compensation.

```python
from pidog import Pidog
import time


SHAKE = [[30, 0, 0], [-30, 0, 0]]      # yaw left/right
NOD = [[0, 0, 30], [0, 0, -30]]         # pitch up/down


def main():
  dog = Pidog()
  try:
    # Nod a few times
    for _ in range(3):
      dog.head_move(NOD, speed=80)
      dog.wait_head_done()
      time.sleep(0.3)

    # Gentle head shake queued
    for _ in range(5):
      dog.head_move(SHAKE, immediately=False, speed=40)
    dog.wait_head_done()

    # Return to center
    dog.head_move([[0, 0, 0]], immediately=True, speed=80)
    dog.wait_head_done()
  finally:
    dog.close()


if __name__ == "__main__":
  main()
```

Bonus: combine with IMU pitch compensation to keep eyes level while the body moves.

#### 13.4.4 Tail Move
Wag tail using the tail buffer, then stop.

```python
from pidog import Pidog
import time


def main():
  dog = Pidog()
  try:
    for _ in range(20):
      dog.tail_move([[30], [-30]], immediately=False, speed=50)
    time.sleep(3)
    dog.tail_stop()
  finally:
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.5 Stop All Actions
Demonstrates coordinated actions and global stopping.

```python
from pidog import Pidog
import time


def main():
  dog = Pidog()
  try:
    # Fill buffers for legs and head concurrently
    for _ in range(30):
      dog.legs_move([[45, 35, -45, -35, 80, 70, -80, -70],
               [90, -30, -90, 30, 80, 70, -80, -70]],
              immediately=False, speed=50)
      dog.head_move([[0, 0, -30], [0, 0, 20]],
              pitch_comp=-10, immediately=False, speed=50)

    # Let it move for a few seconds
    time.sleep(3)

    # Stop everything and lie down
    dog.stop_and_lie()
    dog.wait_all_done()
  finally:
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.6 Do Preset Action
Use built-in poses and gaits. Chain them to create routines.

```python
from pidog import Pidog


ROUTINE = [
  ("stand", 1, 60),
  ("trot", 10, 80),
  ("turn_left", 2, 70),
  ("turn_right", 2, 70),
  ("push_up", 6, 60),
  ("sit", 1, 60),
  ("wag_tail", 30, 90),
  ("tilting_head", 4, 30),
]


def main():
  dog = Pidog()
  try:
    for name, steps, speed in ROUTINE:
      dog.do_action(name, step_count=steps, speed=speed)
    dog.wait_all_done()
    dog.stop_and_lie()
  finally:
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.7 Speak
Play built-in sound effects. On some setups, audio may require elevated permissions.

```python
from pidog import Pidog
import time


SOUNDS = ["single_bark_1", "single_bark_2", "pant", "howling", "woohoo", "angry"]


def main():
  dog = Pidog()
  try:
    for name in SOUNDS:
      print(f"Playing: {name}")
      dog.speak(name, volume=80)
      time.sleep(2)
  finally:
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.8 Read Distance
Poll ultrasonic distance and react to obstacles.

```python
from pidog import Pidog
import time


def main():
  dog = Pidog()
  try:
    while True:
      dist_cm = round(dog.ultrasonic.read_distance(), 2)
      print(f"Distance: {dist_cm} cm")
      if dist_cm and dist_cm < 20.0:
        # Back off and bark if too close
        dog.do_action("backward", step_count=2, speed=70)
        dog.speak("single_bark_1")
      time.sleep(0.3)
  except KeyboardInterrupt:
    pass
  finally:
    dog.stop_and_lie()
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.9 RGB Strip
Cycle through a few styles and colors.

```python
from pidog import Pidog
import time


def main():
  dog = Pidog()
  try:
    dog.rgb_strip.set_mode(style="breath", color="pink", brightness=0.6)
    time.sleep(3)

    dog.rgb_strip.set_mode(style="bark", color="#a10a0a", brightness=1.0)
    time.sleep(3)

    dog.rgb_strip.set_mode(style="boom", color="cyan", bps=2.0, brightness=0.5)
    time.sleep(3)

    dog.rgb_strip.close()
  finally:
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.10 IMU Read
Read accelerometer and gyro, compute a tilt estimate, and keep head level.

```python
from pidog import Pidog
import time
import math


def main():
  dog = Pidog()
  try:
    dog.do_action("stand", speed=50)
    while True:
      ax, ay, az = dog.accData
      gx, gy, gz = dog.gyroData
      pitch_deg = math.atan2(ay, ax) / math.pi * 180.0 % 360.0 - 180.0

      print(
        f"acc: {(ax/16384):.2f}g {(ay/16384):.2f}g {(az/16384):.2f}g | "
        f"gyro: {gx} {gy} {gz} dps | pitch: {pitch_deg:.1f}°"
      )

      # Keep eyes level via pitch compensation
      dog.head_move([[0, 0, 0]], pitch_comp=-pitch_deg, speed=80)
      time.sleep(0.2)
  except KeyboardInterrupt:
    pass
  finally:
    dog.stop_and_lie()
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.11 Sound Direction Detect
Turn head toward clap direction using the sound direction sensor.

```python
from pidog import Pidog
import time


def direction_to_yaw(deg: int) -> int:
  # Map 0..359° (0: front, 90: right) to safe head yaw range ~[-45, 45]
  yaw = int((deg - 180) / 4)  # crude mapping
  return max(-45, min(45, yaw))


def main():
  dog = Pidog()
  try:
    while True:
      if dog.ears.isdetected():
        deg = dog.ears.read()
        yaw = direction_to_yaw(deg)
        dog.head_move([[yaw, 0, 0]], speed=60)
        dog.wait_head_done()
        print(f"Sound at {deg}°, yaw -> {yaw}")
      time.sleep(0.05)
  except KeyboardInterrupt:
    pass
  finally:
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.12 Dual Touch (Pat Head)
React to touches with actions and expressions.

```python
from pidog import Pidog
import time


def on_touch(dog: Pidog, status: str) -> None:
  if status == "L":
    dog.speak("single_bark_2")
    dog.rgb_strip.set_mode(style="bark", color="yellow")
  elif status == "R":
    dog.do_action("wag_tail", step_count=10, speed=90)
  elif status == "LS":  # left-to-right swipe
    dog.do_action("turn_right", step_count=2, speed=70)
  elif status == "RS":  # right-to-left swipe
    dog.do_action("turn_left", step_count=2, speed=70)
  # "N" means no touch; ignore


def main():
  dog = Pidog()
  try:
    while True:
      s = dog.dual_touch.read()
      if s != "N":
        print(f"Touch: {s}")
        on_touch(dog, s)
      time.sleep(0.05)
  except KeyboardInterrupt:
    pass
  finally:
    dog.rgb_strip.close()
    dog.stop_and_lie()
    dog.close()


if __name__ == "__main__":
  main()
```

#### 13.4.13 More
Combine motion, LEDs, audio, and sensors into richer behaviors. For camera-based projects (tracking, face detection), explore the Vilib documentation listed in Resources and adapt your event loop pattern: initialize camera, enable detection(s), then poll results to drive `head_move`, `do_action`, and `rgb_strip` effects.

## 14. Hardware Reference

### 14.1 Robot HAT: Power, Audio, I/O

### 14.2 Servo Layout (12 DOF) and IDs

### 14.3 Camera Module

### 14.4 Sound Direction Sensor

### 14.5 6‑DOF IMU

### 14.6 Dual Touch Sensor

### 14.7 11‑Channel RGB Light Board

### 14.8 Ultrasonic Module

### 14.9 3‑Pin Battery and Power

## 15. Power, Care, and Maintenance

### 15.1 Charging and Power Cycling

### 15.2 Firmware/HAT Updates (If Applicable)

### 15.3 Storage, Transport, and Cleaning

## 16. Troubleshooting and FAQ

### 16.1 Installation/Dependency Issues

### 16.2 Walking or Balance Problems

### 16.3 Camera Not Working

### 16.4 Speaker or Microphone Issues

### 16.5 Sensors Not Responding

### 16.6 LED Board Not Lighting or Syncing

### 16.7 Power and Battery Questions

## 17. Networking and Remote Access (Appendix)

### 17.1 Find the Pi’s IP Address

### 17.2 OpenSSH on Windows PowerShell

### 17.3 PuTTY

### 17.4 File Transfer with FileZilla

## 18. Development Tips

### 18.1 Project Layout and Virtual Envs

### 18.2 Logging and Debugging

### 18.3 Minimal Testing Strategy

## 19. Community and Support

### 19.1 Official Docs

### 19.2 GitHub Repository

### 19.3 Forum and Social Channels

### 19.4 Email Support

## 20. Changelog (for Your Notes)

## 21. License and Credits

## 22. Glossary

## 23. Index

---

## Resources

- Official docs hub: https://docs.sunfounder.com/projects/pidog/en/latest/
- Official Python library: https://github.com/sunfounder/pidog
- Community forum: https://forum.sunfounder.com/
- Support: service@sunfounder.com

> Note: This outline is derived from publicly available product features and API areas. It intentionally avoids copying proprietary wording; use it as a scaffold for your original content.

---

## 24. Pidog API Reference (Master List)

This section catalogs Pidog’s primary Python APIs so you can discover features quickly. Items are paraphrased and grouped by subsystem; some names are factual strings (action/style identifiers). Where the library exposes properties or nested objects, they’re shown with their methods.

Important notes:
- Method signatures below reflect common usage seen in docs and examples; exact defaults may vary by release.
- For the most authoritative behavior, refer to the installed package’s help() output on your Pi.
- Some helpers or buffers may be present depending on version.

### Core class

- class Pidog(
  leg_pins=DEFAULT_LEGS_PINS,
  head_pins=DEFAULT_HEAD_PINS,
  tail_pin=DEFAULT_TAIL_PIN,
  leg_init_angles=None,
  head_init_angles=None,
  tail_init_angle=None
  )
- do_action(action_name: str, step_count: int = 1, speed: int = 50)
- wait_all_done()
- body_stop()
- stop_and_lie()
- close()

### Legs (8 servos)

- legs_move(target_angles: list[list[int]], immediately: bool = True, speed: int = 50)
- is_legs_done() -> bool
- wait_legs_done()
- legs_stop()
- legs_action_buffer  (queue of pending leg angle groups; read-only usage varies)

### Head (yaw, roll, pitch; 3 servos)

- head_move(
  target_angles: list[list[int]],
  roll_comp: float = 0,
  pitch_comp: float = 0,
  immediately: bool = True,
  speed: int = 50
  )
- is_head_done() -> bool
- wait_head_done()
- head_stop()

### Tail (1 servo)

- tail_move(target_angles: list[list[int]], immediately: bool = True, speed: int = 50)
- is_tail_done() -> bool
- wait_tail_done()
- tail_stop()

### Audio

- speak(name: str, volume: int = 100)
  - name is a sound effect id (without extension) included in the package’s sounds directory.

### RGB Light Board

- rgb_strip.set_mode(
    style: str = 'breath',
    color: str = 'white' | '#RRGGBB',
    bps: float = 1.0,
    brightness: float = 1.0
  )
- rgb_strip.close()

Known styles: 'breath', 'boom', 'bark'.

### Ultrasonic (distance)

- ultrasonic.read_distance() -> float  (centimeters)

### IMU (6‑DOF)

- accData -> tuple[int, int, int]   (raw accel x, y, z)
- gyroData -> tuple[int, int, int]  (raw gyro x, y, z)

### Sound Direction Sensor

- ears.isdetected() -> bool
- ears.read() -> int  (direction 0–359, 0 front, 90 right)

### Dual Touch Sensor (head)

- dual_touch.read() -> str  (one of 'L', 'R', 'LS', 'RS', 'N')

### Preset action names for do_action()

These are the canonical strings you can pass to do_action; availability can vary with versions:

- 'sit'
- 'half_sit'
- 'stand'
- 'lie'
- 'lie_with_hands_out'
- 'forward'
- 'backward'
- 'turn_left'
- 'turn_right'
- 'trot'
- 'stretch'
- 'push_up'
- 'doze_off'
- 'nod_lethargy'
- 'shake_head'
- 'tilting_head_left'
- 'tilting_head_right'
- 'tilting_head'
- 'head_bark'
- 'head_up_down'
- 'wag_tail'

### Practical introspection helpers (run on your Pi)

Use these snippets to list what your installed version exposes, so you never miss new capabilities.

List callable attributes on Pidog:

```python
from pidog import Pidog
import inspect

methods = [
    (name, obj) for name, obj in inspect.getmembers(Pidog)
    if inspect.isfunction(obj) or inspect.ismethod(obj)
]
for name, _ in methods:
    print(name)
```

Enumerate available sound effect ids from the package:

```python
import os, pkgutil
import pidog

base = os.path.join(os.path.dirname(pidog.__file__), 'sounds')
if os.path.isdir(base):
    for f in sorted(os.listdir(base)):
        if f.lower().endswith(('.wav', '.mp3', '.ogg')):
            print(os.path.splitext(f)[0])
```

Probe for action names by attempting a dry run (no-op speed and single step); wrap with try/except to skip invalid ones:

```python
from pidog import Pidog

candidates = [
  'sit','half_sit','stand','lie','lie_with_hands_out','forward','backward',
  'turn_left','turn_right','trot','stretch','push_up','doze_off','nod_lethargy',
  'shake_head','tilting_head_left','tilting_head_right','tilting_head','head_bark',
  'head_up_down','wag_tail'
]

dog = Pidog()
ok = []
for name in candidates:
    try:
        dog.do_action(name, step_count=1, speed=1)
        ok.append(name)
    except Exception:
        pass
dog.stop_and_lie(); dog.close()
print('Supported actions:', ok)
```

For official reference examples (verbatim), see the links in Resources and in section 13.4 entries.
