#!/usr/bin/env python3
import time
import threading
import keyboard
from pidog import Pidog
from pidog.b9_rgb import RGB  # ✅ Import RGB LED Control

class PatrolMode:
    """Class-based patrol system for PiDog with AI-powered mapping, speed profiles, obstacle memory, emotional states, keyboard control, and RGB effects."""

    def __init__(self):
        self.dog = Pidog()
        self.rgb = RGB(self.dog)  # ✅ Initialize RGB LED
        self.exit_flag = False
        self.position = {"x": 0, "y": 0}  # PiDog's current position
        self.obstacle_map = {}  # ✅ Stores past obstacles with probability weights
        self.current_state = "patrolling"

        # ✅ Define speed profiles
        self.speed_profiles = {
            "walking": {"walk_speed": 80, "turn_speed": 120},
            "trotting": {"walk_speed": 120, "turn_speed": 200},
            "running": {"walk_speed": 200, "turn_speed": 220}
        }

        self.current_profile = "trotting"  # ✅ Default speed profile
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

    def update_position(self, direction):
        """Track PiDog’s position in the mapped space."""
        step_size = 1

        if direction == "forward":
            self.position["y"] += step_size
        elif direction == "backward":
            self.position["y"] -= step_size
        elif direction == "left":
            self.position["x"] -= step_size
        elif direction == "right":
            self.position["x"] += step_size

        print(f"📍 Updated Position: {self.position}")

    def scan_surroundings(self):
        """Continuously scan surroundings while walking forward."""
        self.dog.head_move([[-50, 0, 0]], immediately=True, speed=self.current_speed["walk_speed"])  # Look left
        self.dog.wait_head_done()
        left_distance = self.dog.read_distance()

        self.dog.head_move([[50, 0, 0]], immediately=True, speed=self.current_speed["walk_speed"])  # Look right
        self.dog.wait_head_done()
        right_distance = self.dog.read_distance()

        self.dog.head_move([[0, 0, 0]], immediately=True, speed=self.current_speed["walk_speed"])  # Reset head position
        forward_distance = self.dog.read_distance()

        print(f"🔎 Forward: {forward_distance}, Left: {left_distance}, Right: {right_distance}")
        return forward_distance, left_distance, right_distance

    def detect_obstacle(self):
        """Detect obstacles and adjust movement dynamically based on proximity."""
        forward_distance, left_distance, right_distance = self.scan_surroundings()
        current_position = (self.position["x"], self.position["y"])

        # ✅ Update obstacle map with probability tracking
        if forward_distance < 80:
            self.obstacle_map[current_position] = self.obstacle_map.get(current_position, 0) + 1
            print(f"📌 Memory Map Updated: {self.obstacle_map}")

        # ✅ Predict best direction using stored obstacle memory
        if forward_distance < 80 and forward_distance > 40:
            print("⚠️ Predicting the best direction based on obstacle memory.")
            left_obstacle_count = self.obstacle_map.get((self.position["x"] - 1, self.position["y"]), 0)
            right_obstacle_count = self.obstacle_map.get((self.position["x"] + 1, self.position["y"]), 0)

            direction = "left" if left_obstacle_count < right_obstacle_count else "right"
            self.current_state = "navigating"
            self.update_led()
            self.turn_with_head(direction, full_turn=False)  # ✅ Use partial turn
            return True

        # ✅ If obstacle detected **to the side**, determine turn size
        if left_distance < 35 or right_distance < 35:
            direction = "right" if left_distance < right_distance else "left"
            turn_size = "big" if min(left_distance, right_distance) < 20 else "small"

            print(f"🛑 Side obstacle detected! Making a {turn_size} turn to the {direction}.")
            self.current_state = "avoiding_zone"
            self.update_led()
            self.turn_with_head(direction, full_turn=(turn_size == "big"))  # ✅ Small or full turn based on proximity
            return True

        # ✅ Retreat if obstacle is **too close**
        if forward_distance < 40:
            print("🚨 Obstacle ahead! Retreating...")
            self.current_state = "obstacle_detected"
            self.update_led()

            self.dog.head_move([[0, 50, 0]], immediately=True, speed=self.current_speed["walk_speed"])
            self.dog.wait_head_done()
            self.dog.do_action("bark", speed=80)  # ✅ Barking when startled
            time.sleep(0.5)

            self.dog.do_action("backward", step_count=2, speed=self.current_speed["walk_speed"])
            self.dog.wait_all_done()

            direction = "left" if left_distance > right_distance else "right"
            self.turn_with_head(direction)
            return True

        self.current_state = "patrolling"
        self.update_led()
        return False

    def turn_with_head(self, direction, full_turn=True):
        """Synchronize PiDog’s head movement with turns, adjusting turn size dynamically."""
        turn_steps = 3 if full_turn else 1  # ✅ Use partial turns when needed

        if direction == "left":
            self.dog.head_move([[-50, 0, 0]], immediately=True, speed=self.current_speed["walk_speed"])
        elif direction == "right":
            self.dog.head_move([[50, 0, 0]], immediately=True, speed=self.current_speed["walk_speed"])

        self.dog.wait_head_done()
        self.dog.do_action(f"turn_{direction}", step_count=turn_steps, speed=self.current_speed["turn_speed"])
        self.dog.head_move([[0, 0, 0]], immediately=True, speed=self.current_speed["walk_speed"])
        self.dog.wait_head_done()

    def start_behavior(self):
        """PiDog continuously patrols while scanning and updating obstacle memory."""
        print(f"🐶 Patrol Mode Activated! Default Speed: {self.current_profile}")
        self.update_led()

        while not self.exit_flag:
            obstacle_detected = self.detect_obstacle()

            if not obstacle_detected:
                self.update_position("forward")
                self.dog.do_action("forward", step_count=2, speed=self.current_speed["walk_speed"])

            self.dog.wait_all_done()
            time.sleep(0.5)

        print("🚪 Exiting Patrol Mode!")
        self.rgb.set_color((255, 255, 255))  # ✅ Reset LED before shutting down
        self.dog.close()