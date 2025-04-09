#!/usr/bin/env python3
"""
PiDog Smarter Patrol Mode (Optimized)
==================================
This module controls PiDog’s patrol behavior, adapting based on **obstacle memory**, **speed profiles**, and **emotional states**.

Key Features:
✅ **Dynamically tracks patrol state (`global_state.active_mode`)**.
✅ **Stores obstacle memory persistently (`global_state.obstacle_memory`)** for smarter future navigation.
✅ **Syncs patrol speed with `global_state.speed`** for consistency.
✅ **Uses RGB LED effects to visually represent emotional states**.
✅ **Ensures safe thread execution when monitoring keyboard interruptions**.

7-lynx
"""

import time
import threading
import keyboard
import global_state  # ✅ Integrated state tracking
from pidog import Pidog
from pidog.b9_rgb import RGB  # ✅ Import RGB LED Control

class PatrolMode:
    """Class-based patrol system for PiDog with AI-powered mapping, emotional states, obstacle learning, and thread-safe execution."""

    def __init__(self):
        global_state.active_mode = "patrolling"  # ✅ Track patrol state globally

        self.dog = Pidog()
        self.rgb = RGB(self.dog)  # ✅ Initialize RGB LED
        self.exit_flag = False
        self.position = global_state.position  # ✅ Sync position globally
        self.obstacle_map = global_state.obstacle_memory  # ✅ Use persistent obstacle memory
        self.current_state = "patrolling"

        # ✅ Define speed profiles (now synced with `global_state.speed`)
        self.speed_profiles = {
            "walking": {"walk_speed": 80, "turn_speed": 120},
            "trotting": {"walk_speed": 120, "turn_speed": 200},
            "running": {"walk_speed": 200, "turn_speed": 220}
        }

        self.current_profile = "trotting"
        global_state.speed = self.speed_profiles[self.current_profile]["walk_speed"]  # ✅ Sync patrol speed globally
        self.current_speed = self.speed_profiles[self.current_profile]

        # ✅ Emotional States with RGB Effects
        self.EMOTIONAL_STATES = {
            "patrolling": ("🌟 Curious", (0, 255, 0), self.rgb.breathe),  # 🟢 Green Breathing
            "obstacle_detected": ("😨 Startled", (255, 0, 0), self.rgb.flash),  # 🔴 Red Flash
            "avoiding_zone": ("🤔 Cautious", (0, 0, 255), self.rgb.fade),  # 🔵 Blue Fade
            "navigating": ("🔄 Decision-Making", (255, 255, 0), self.rgb.pulse),  # 🟡 Yellow Pulse
        }

        threading.Thread(target=self.monitor_keyboard, daemon=True).start()

    def update_led(self):
        """Update LED based on PiDog’s emotional state."""
        emotion, color, effect = self.EMOTIONAL_STATES.get(self.current_state, ("😶 Neutral", (255, 255, 255), self.rgb.breathe))
        self.rgb.set_color(color)
        effect(1)  # Apply selected LED effect
        print(f"💡 LED updated: {emotion} -> {color}")

    def scan_surroundings(self):
        """Continuously scan surroundings while walking forward."""
        self.dog.head_move([[-50, 0, 0]], speed=self.current_speed["walk_speed"])  # Look left
        self.dog.wait_head_done()
        left_distance = self.dog.read_distance()

        self.dog.head_move([[50, 0, 0]], speed=self.current_speed["walk_speed"])  # Look right
        self.dog.wait_head_done()
        right_distance = self.dog.read_distance()

        self.dog.head_move([[0, 0, 0]], speed=self.current_speed["walk_speed"])  # Reset head position
        forward_distance = self.dog.read_distance()

        print(f"🔎 Forward: {forward_distance}, Left: {left_distance}, Right: {right_distance}")
        return forward_distance, left_distance, right_distance

    def detect_obstacle(self):
        """Detect obstacles and adjust movement dynamically."""
        forward_distance, left_distance, right_distance = self.scan_surroundings()
        current_position = (self.position["x"], self.position["y"])

        # ✅ Store obstacles in persistent memory
        if forward_distance < 80:
            global_state.obstacle_memory[current_position] = global_state.obstacle_memory.get(current_position, 0) + 1
            print(f"📌 Memory Map Updated: {global_state.obstacle_memory}")

        # ✅ Predict best direction using stored obstacle memory
        if forward_distance < 80 and forward_distance > 40:
            left_obstacle_count = global_state.obstacle_memory.get((self.position["x"] - 1, self.position["y"]), 0)
            right_obstacle_count = global_state.obstacle_memory.get((self.position["x"] + 1, self.position["y"]), 0)
            direction = "left" if left_obstacle_count < right_obstacle_count else "right"

            self.current_state = "navigating"
            self.update_led()
            self.turn_with_head(direction, full_turn=False)
            return True

        # ✅ If side obstacle detected, determine turn size
        if left_distance < 35 or right_distance < 35:
            direction = "right" if left_distance < right_distance else "left"
            turn_size = "big" if min(left_distance, right_distance) < 20 else "small"

            self.current_state = "avoiding_zone"
            self.update_led()
            self.turn_with_head(direction, full_turn=(turn_size == "big"))
            return True

        # ✅ Retreat if obstacle is **too close**
        if forward_distance < 40:
            self.current_state = "obstacle_detected"
            self.update_led()

            self.dog.do_action("bark", speed=80)
            time.sleep(0.5)

            self.dog.do_action("backward", step_count=2, speed=self.current_speed["walk_speed"])
            self.dog.wait_all_done()

            direction = "left" if left_distance > right_distance else "right"
            self.turn_with_head(direction)
            return True

        self.current_state = "patrolling"
        self.update_led()
        return False

    def start_behavior(self):
        """PiDog continuously patrols while scanning and updating obstacle memory."""
        print(f"🐶 Patrol Mode Activated! Default Speed: {self.current_profile}")
        self.update_led()

        while not self.exit_flag:
            obstacle_detected = self.detect_obstacle()

            if not obstacle_detected:
                self.dog.do_action("forward", step_count=2, speed=self.current_speed["walk_speed"])

            self.dog.wait_all_done()
            time.sleep(0.5)

        print("🚪 Exiting Patrol Mode!")
        global_state.active_mode = "idle"  # ✅ Reset patrol state globally
        self.rgb.set_color((255, 255, 255))  # ✅ Reset LED before shutting down
        self.dog.close()

