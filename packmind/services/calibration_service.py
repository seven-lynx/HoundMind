"""
CalibrationService: houses calibration routines used by PackMind.

Methods return bool for success and may update SLAM/localization components.
Orchestrator should call into this service instead of owning the logic.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
import time


class CalibrationService:
    def __init__(self, slam_system: Optional[Any], scanning_service: Optional[Any], dog: Optional[Any], logger: Optional[Any] = None) -> None:
        self.slam_system = slam_system
        self.scanning_service = scanning_service
        self.dog = dog
        self.logger = logger

    def calibrate(self, method: str = "wall_follow") -> bool:
        method = (method or "").lower()
        if method == "wall_follow":
            return self._calibrate_wall_follow()
        if method == "corner_seek":
            return self._calibrate_corner_seek()
        if method == "landmark_align":
            return self._calibrate_landmark_align()
        if self.logger:
            self.logger.warning(f"Unknown calibration method: {method}")
        return False

    # Implementations adapted from orchestrator methods with hardware-safe guards
    def _calibrate_wall_follow(self) -> bool:
        """Calibrate by detecting closest wall and aligning toward it, then approaching.

        Returns True when basic alignment and approach succeed; also raises
        SLAM position confidence when available.
        """
        dog = self.dog
        if dog is None:
            if self.logger:
                self.logger.warning("Calibration: dog not available")
            return False

        try:
            if self.logger:
                self.logger.info("🧱 Wall following calibration...")

            # Perform coarse 360° scan via head yaw to find walls
            wall_distances: Dict[int, float] = {}
            for angle in range(0, 360, 45):
                head_angle = max(-80, min(80, angle - 180))
                dog.head_move([[head_angle, 0, 0]], speed=90)
                time.sleep(0.3)
                try:
                    dist = dog.ultrasonic.read_distance()
                except Exception:
                    dist = 0
                if isinstance(dist, (int, float)) and 10 < float(dist) < 200:
                    wall_distances[angle] = float(dist)

            # Return head to center
            try:
                dog.head_move([[0, 0, 0]], speed=90)
            except Exception:
                pass

            if not wall_distances:
                if self.logger:
                    self.logger.warning("Calibration: no walls found")
                return False

            # Find closest wall
            closest_angle, wall_distance = min(wall_distances.items(), key=lambda x: x[1])
            if self.logger:
                self.logger.info(f"Closest wall at {closest_angle}°, distance {wall_distance:.1f}cm")

            # Align toward wall (rough, step-based)
            if wall_distance > 30:
                turn_direction = "turn_left" if closest_angle > 180 else "turn_right"
                turn_steps = min(3, abs(closest_angle - 180) // 45)
                if turn_steps > 0:
                    dog.do_action(turn_direction, step_count=int(turn_steps), speed=60)
                # Move closer to ~25cm
                steps_needed = max(1, int((wall_distance - 25) / 15))
                dog.do_action("forward", step_count=min(steps_needed, 3), speed=50)

            # Bump SLAM confidence when present
            if self.slam_system and hasattr(self.slam_system, 'get_position'):
                try:
                    current_pos = self.slam_system.get_position()
                    if hasattr(current_pos, 'confidence'):
                        current_pos.confidence = 0.95
                except Exception:
                    pass

            if self.logger:
                self.logger.info("✓ Wall calibration completed")
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Calibration error (wall_follow): {e}")
            return False

    def _calibrate_corner_seek(self) -> bool:
        """Calibrate by finding and aligning with room corners using a 3-way scan."""
        dog = self.dog
        if dog is None:
            if self.logger:
                self.logger.warning("Calibration: dog not available")
            return False

        try:
            if self.logger:
                self.logger.info("📐 Corner seeking calibration...")

            # Prefer ScanningService if available
            scan = None
            if self.scanning_service and hasattr(self.scanning_service, 'scan_three_way'):
                try:
                    scan = self.scanning_service.scan_three_way()
                except Exception:
                    scan = None
            if scan is None:
                # Manual three-way scan
                scan = {"forward": 0.0, "left": 0.0, "right": 0.0}
                try:
                    dog.head_move([[0, 0, 0]], speed=90)
                    time.sleep(0.3)
                    scan["forward"] = float(dog.ultrasonic.read_distance())
                except Exception:
                    pass
                try:
                    dog.head_move([[-50, 0, 0]], speed=90)
                    time.sleep(0.3)
                    scan["right"] = float(dog.ultrasonic.read_distance())
                except Exception:
                    pass
                try:
                    dog.head_move([[50, 0, 0]], speed=90)
                    time.sleep(0.3)
                    scan["left"] = float(dog.ultrasonic.read_distance())
                except Exception:
                    pass
                try:
                    dog.head_move([[0, 0, 0]], speed=90)
                except Exception:
                    pass

            corners_found = 0
            if (scan.get('forward', 999) < 50 and scan.get('left', 999) < 50 and scan.get('right', 0) > 100):
                dog.do_action("turn_left", step_count=2, speed=60)
                corners_found += 1
            elif (scan.get('forward', 999) < 50 and scan.get('right', 999) < 50 and scan.get('left', 0) > 100):
                dog.do_action("turn_right", step_count=2, speed=60)
                corners_found += 1

            if corners_found > 0 and self.slam_system and hasattr(self.slam_system, 'get_position'):
                try:
                    current_pos = self.slam_system.get_position()
                    if hasattr(current_pos, 'confidence'):
                        current_pos.confidence = 0.9
                except Exception:
                    pass

            if corners_found > 0:
                if self.logger:
                    self.logger.info(f"✓ Corner calibration completed ({corners_found} corners)")
                return True
            else:
                if self.logger:
                    self.logger.warning("❌ No clear corners found")
                return False
        except Exception as e:
            if self.logger:
                self.logger.error(f"Calibration error (corner_seek): {e}")
            return False

    def _calibrate_landmark_align(self) -> bool:
        """Calibrate using known map landmarks (anchors) from SLAM system."""
        if not self.slam_system:
            if self.logger:
                self.logger.warning("Calibration: SLAM system not available")
            return False
        try:
            anchors = getattr(self.slam_system, 'anchors', {})
            if not anchors:
                if self.logger:
                    self.logger.warning("Calibration: no anchors available")
                return False
            current_pos = self.slam_system.get_position() if hasattr(self.slam_system, 'get_position') else None
            if current_pos is None:
                if self.logger:
                    self.logger.warning("Calibration: current position not available")
                return False
            # Find nearest anchor
            min_dist = float('inf')
            closest_anchor_id: Optional[str] = None
            for anchor_id, anchor_pos in anchors.items():
                try:
                    dx = float(getattr(anchor_pos, 'x', 0.0)) - float(getattr(current_pos, 'x', 0.0))
                    dy = float(getattr(anchor_pos, 'y', 0.0)) - float(getattr(current_pos, 'y', 0.0))
                    dist = (dx * dx + dy * dy) ** 0.5
                except Exception:
                    continue
                if dist < min_dist:
                    min_dist = dist
                    closest_anchor_id = anchor_id

            if closest_anchor_id is None:
                if self.logger:
                    self.logger.warning("Calibration: no valid anchor found")
                return False

            if hasattr(self.slam_system, 'correct_position_with_anchor') and self.slam_system.correct_position_with_anchor(closest_anchor_id):
                # Optionally raise confidence
                try:
                    new_pos = self.slam_system.get_position()
                    if hasattr(new_pos, 'confidence'):
                        new_pos.confidence = max(getattr(new_pos, 'confidence', 0.0), 0.9)
                except Exception:
                    pass
                if self.logger:
                    self.logger.info("✓ Landmark calibration completed")
                return True
            else:
                if self.logger:
                    self.logger.warning("Calibration: failed to correct with anchor")
                return False
        except Exception as e:
            if self.logger:
                self.logger.error(f"Calibration error (landmark_align): {e}")
            return False
