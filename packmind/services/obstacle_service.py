from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import time
import random

from packmind.core.context import AIContext
from packmind.core.types import BehaviorState


class ObstacleService:
    """
    Threat analysis and avoidance strategies consuming scanning outputs.
    Holds short-term state (avoidance history, stuck detection) to inform decisions.
    """

    def __init__(self) -> None:
        self.avoidance_history: List[Tuple[float, str, float]] = []  # (timestamp, direction, fwd_dist)
        self.avoidance_strategies: List[str] = [
            "turn_smart",
            "backup_turn",
            "zigzag",
            "reverse_escape",
        ]
        self.current_strategy_index: int = 0
        self.movement_history: List[Tuple[float, float]] = []  # (t, magnitude)
        self.stuck_counter: int = 0

    def analyze_scan(self, scan: Dict[str, float], config) -> Optional[str]:
        """
        Return threat level: 'IMMEDIATE', 'APPROACHING', or None (clear forward).
        """
        fwd = scan.get("forward", 0.0)
        if fwd <= 0:
            return "IMMEDIATE"
        if fwd < config.OBSTACLE_IMMEDIATE_THREAT:
            return "IMMEDIATE"
        if fwd < config.OBSTACLE_APPROACHING_THREAT:
            return "APPROACHING"
        return None

    def maybe_avoid(self, context: AIContext, scan: Dict[str, float], config, turn_speed: int) -> None:
        """Execute avoidance if needed based on scan data and history."""
        threat = self.analyze_scan(scan, config)
        if threat is None:
            return
        if threat == "IMMEDIATE":
            self._execute_intelligent_avoidance(context, scan, config, turn_speed)
        elif threat == "APPROACHING":
            # Let caller reduce speed; no immediate action here
            pass

    def _execute_intelligent_avoidance(self, context: AIContext, scan: Dict[str, float], config, turn_speed: int) -> None:
        now = time.time()
        forward_dist = scan.get("forward", 0.0)
        left_dist = scan.get("left", 0.0)
        right_dist = scan.get("right", 0.0)

        # Use a local explicitly-typed slice to keep analyzers happy
        recent_hist = list(self.avoidance_history)
        recent = [a for a in recent_hist if now - a[0] < 10.0]
        if len(recent) >= 3:
            self._execute_advanced_avoidance_strategy(context, config)
        else:
            self._execute_smart_turn_avoidance(context, left_dist, right_dist, config, turn_speed)

        best_dir = "left" if left_dist > right_dist else "right"
        self.avoidance_history.append((now, best_dir, forward_dist))
        # keep last 30s
        self.avoidance_history = [a for a in self.avoidance_history if now - a[0] < 30.0]

    def _execute_smart_turn_avoidance(self, context: AIContext, left_dist: float, right_dist: float, config, turn_speed: int) -> None:
        clearance_threshold = 10.0
        dog = context.dog
        if left_dist > right_dist + clearance_threshold:
            direction = "turn_left"
            steps = config.TURN_STEPS_NORMAL if left_dist > 50 else config.TURN_STEPS_SMALL
        elif right_dist > left_dist + clearance_threshold:
            direction = "turn_right"
            steps = config.TURN_STEPS_NORMAL if right_dist > 50 else config.TURN_STEPS_SMALL
        else:
            last_three: list[tuple[float, str, float]] = list(self.avoidance_history[-3:])
            recent_lefts = sum(1 for _, d, _ in last_three if d == "left")
            recent_rights = sum(1 for _, d, _ in last_three if d == "right")
            if recent_lefts > recent_rights:
                direction = "turn_right"
            else:
                direction = "turn_left"
            steps = config.TURN_STEPS_NORMAL
        dog.body_stop()
        # If orientation integration is enabled and heading is available, perform precise turn by angle
        use_imu_turn = bool(getattr(config, "ENABLE_ORIENTATION_SERVICE", True)) and hasattr(context, "current_heading")
        if use_imu_turn:
            try:
                degrees_per_step = float(getattr(config, "TURN_DEGREES_PER_STEP", 15.0))
            except Exception:
                degrees_per_step = 15.0
            target_deg = float(steps) * degrees_per_step
            if direction == "turn_right":
                target_deg = -target_deg
            tol = float(getattr(config, "ORIENTATION_TURN_TOLERANCE_DEG", 5.0))
            timeout_s = float(getattr(config, "ORIENTATION_MAX_TURN_TIME_S", 3.0))
            self._turn_by_angle(context, target_deg, speed=turn_speed, tolerance_deg=tol, timeout_s=timeout_s)
        else:
            dog.do_action(direction, step_count=steps, speed=turn_speed)
            dog.wait_all_done()

    def _execute_advanced_avoidance_strategy(self, context: AIContext, config) -> None:
        dog = context.dog
        strategy = self.avoidance_strategies[self.current_strategy_index]
        if strategy == "backup_turn":
            dog.body_stop()
            dog.do_action("backward", step_count=config.BACKUP_STEPS, speed=config.SPEED_EMERGENCY)
            dog.wait_all_done()
            turn_dir = "turn_left" if random.random() > 0.5 else "turn_right"
            dog.do_action(turn_dir, step_count=config.TURN_STEPS_LARGE, speed=config.SPEED_TURN_NORMAL)
        elif strategy == "zigzag":
            for direction in ["turn_left", "turn_right", "turn_left", "turn_right"]:
                dog.do_action(direction, step_count=config.TURN_STEPS_SMALL, speed=config.SPEED_FAST)
                dog.wait_all_done()
                dog.do_action("forward", step_count=config.WALK_STEPS_SHORT, speed=config.SPEED_EMERGENCY)
                dog.wait_all_done()
        elif strategy == "reverse_escape":
            dog.body_stop()
            dog.do_action("backward", step_count=config.BACKUP_STEPS + 2, speed=config.SPEED_NORMAL)
            dog.wait_all_done()
            turn_amount = random.randint(config.TURN_STEPS_NORMAL, config.TURN_STEPS_LARGE + 2)
            turn_dir = "turn_left" if random.random() > 0.5 else "turn_right"
            dog.do_action(turn_dir, step_count=turn_amount, speed=config.SPEED_TURN_FAST)
        else:
            dog.do_action("backward", step_count=1, speed=50)
            dog.wait_all_done()
            # Caller should trigger a fresh scan after this
        self.current_strategy_index = (self.current_strategy_index + 1) % len(self.avoidance_strategies)
        self.avoidance_history = []

    def track_movement(self, context: AIContext, config) -> None:
        ax, ay, az = context.dog.accData
        mag = abs(ax) + abs(ay) + abs(az)
        now = time.time()
        self.movement_history.append((now, mag))
        # Keep only recent movement samples within configured window
        try:
            window_s = float(getattr(config, "STUCK_TIME_WINDOW", 5.0))
        except Exception:
            window_s = 5.0
        self.movement_history = [(t, m) for t, m in self.movement_history if now - t < window_s]

    def check_if_stuck(self, context: AIContext, config) -> None:
        if context.behavior_state not in [BehaviorState.PATROLLING, BehaviorState.EXPLORING]:
            self.stuck_counter = 0
            return
        if len(self.movement_history) <= 10:
            return
        last_moves: list[tuple[float, float]] = list(self.movement_history[-10:])
        recent = [m for _, m in last_moves]
        avg = sum(recent) / len(recent)
        try:
            movement_threshold = float(getattr(config, "STUCK_MOVEMENT_THRESHOLD", 1000.0))
        except Exception:
            movement_threshold = 1000.0
        try:
            limit = int(getattr(config, "STUCK_AVOIDANCE_LIMIT", 5))
        except Exception:
            limit = 5
        if avg < movement_threshold:
            self.stuck_counter += 1
            if self.stuck_counter > limit:
                self._execute_advanced_avoidance_strategy(context, config)
                self.stuck_counter = 0
        else:
            self.stuck_counter = 0

    def _turn_by_angle(self, context: AIContext, degrees: float, speed: int, tolerance_deg: float = 5.0, timeout_s: float = 3.0) -> None:
        """Rotate by target degrees using context.current_heading feedback (if available)."""
        dog = context.dog
        if dog is None:
            return
        try:
            start = float(getattr(context, "current_heading", 0.0))
            def ang_diff(a: float, b: float) -> float:
                d = (a - b + 180.0) % 360.0 - 180.0
                return d
            end_time = time.time() + float(timeout_s)
            while time.time() < end_time:
                current = float(getattr(context, "current_heading", 0.0))
                delta = ang_diff(current, start)
                remaining = float(degrees) - delta
                if abs(remaining) <= float(tolerance_deg):
                    break
                step_dir = "turn_left" if remaining > 0 else "turn_right"
                try:
                    dog.do_action(step_dir, step_count=1, speed=int(speed))
                except Exception:
                    pass
                time.sleep(0.1)
        except Exception:
            pass
