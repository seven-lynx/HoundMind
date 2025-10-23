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

        recent = [a for a in self.avoidance_history if now - a[0] < 10.0]
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
            recent_lefts = sum(1 for _, d, _ in self.avoidance_history[-3:] if d == "left")
            recent_rights = sum(1 for _, d, _ in self.avoidance_history[-3:] if d == "right")
            if recent_lefts > recent_rights:
                direction = "turn_right"
            else:
                direction = "turn_left"
            steps = config.TURN_STEPS_NORMAL
        dog.body_stop()
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

    def track_movement(self, context: AIContext) -> None:
        ax, ay, az = context.dog.accData
        mag = abs(ax) + abs(ay) + abs(az)
        now = time.time()
        self.movement_history.append((now, mag))
        self.movement_history = [(t, m) for t, m in self.movement_history if now - t < 5.0]

    def check_if_stuck(self, context: AIContext, config) -> None:
        if context.behavior_state not in [BehaviorState.PATROLLING, BehaviorState.EXPLORING]:
            self.stuck_counter = 0
            return
        if len(self.movement_history) <= 10:
            return
        recent = [m for _, m in self.movement_history[-10:]]
        avg = sum(recent) / len(recent)
        if avg < 1000:
            self.stuck_counter += 1
            if self.stuck_counter > 5:
                self._execute_advanced_avoidance_strategy(context, config)
                self.stuck_counter = 0
        else:
            self.stuck_counter = 0
