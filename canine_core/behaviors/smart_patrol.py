#!/usr/bin/env python3
"""
CanineCore Smart Patrol (Converted)

An event-friendly, cooperative patrol behavior that scans surroundings and
avoids obstacles using the CanineCore Behavior interface. It reads distances
by sweeping the head left/right/forward and chooses a move accordingly.

Hardware-safe: falls back to simulated logs if Pidog hardware isn't present.
Configuration-driven: uses speeds and thresholds from CanineConfig.
"""
from __future__ import annotations
import asyncio
from typing import Optional, Tuple

from canine_core.core.interfaces import Behavior, BehaviorContext, Event


class SmartPatrolBehavior(Behavior):
    name = "smart_patrol"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        self._running = True
        try:
            ctx.state.set("active_mode", "patrol")
        except Exception:
            pass
        # Gentle ready posture and LED if available
        dog = getattr(ctx.hardware, "dog", None)
        rgb = getattr(ctx.hardware, "rgb", None)
        if dog is not None:
            try:
                speed_normal = getattr(ctx.config, "SPEED_NORMAL", 120)
                dog.do_action("stand", speed=speed_normal)
                dog.wait_all_done()
            except Exception:
                pass
        enable_emotions = getattr(ctx.config, "ENABLE_EMOTIONAL_SYSTEM", getattr(ctx.config, "enable_emotional_system", False))
        if rgb is not None and enable_emotions:
            try:
                rgb.set_color((0, 255, 0))  # patrolling: green
                if hasattr(rgb, "breathe"):
                    rgb.breathe(1)
            except Exception:
                pass
        ctx.logger.info("SmartPatrol starting")
        self._task = asyncio.create_task(self._loop())

    async def on_event(self, event: Event) -> None:
        # Future: react to voice/stop events
        return

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.5)
            except asyncio.TimeoutError:
                pass
        if self._ctx and getattr(self._ctx.hardware, "dog", None):
            try:
                self._ctx.hardware.dog.do_action("stand", speed=self._ctx.config.SPEED_SLOW)
                self._ctx.hardware.dog.wait_all_done()
            except Exception:
                pass
        if self._ctx and getattr(self._ctx.hardware, "rgb", None):
            try:
                self._ctx.hardware.rgb.set_color((255, 255, 255))
            except Exception:
                pass
        if self._ctx:
            self._ctx.logger.info("SmartPatrol stopped")

    # --- internal helpers ---
    def _scan(self) -> Tuple[float, float, float]:
        """Return (forward_mm, left_mm, right_mm). If no hardware, return large distances.
        """
        assert self._ctx is not None
        dog = getattr(self._ctx.hardware, "dog", None)
        if dog is None:
            return (1000.0, 1000.0, 1000.0)
        try:
            # look left
            head_range = getattr(self._ctx.config, "HEAD_SCAN_RANGE", 45)
            head_speed = getattr(self._ctx.config, "HEAD_SCAN_SPEED", 70)
            dog.head_move([[-head_range, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            left = float(dog.read_distance() or 1000.0)
            # look right
            dog.head_move([[head_range, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            right = float(dog.read_distance() or 1000.0)
            # reset forward and read
            dog.head_move([[0, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            fwd = float(dog.read_distance() or 1000.0)
            return (fwd, left, right)
        except Exception as e:
            self._ctx.logger.warning(f"Scan failed: {e}")
            return (1000.0, 1000.0, 1000.0)

    def _decide(self, fwd: float, left: float, right: float) -> tuple[str, dict]:
        """Decide next action.
        Returns (action, params) where action in {"forward","turn_left","turn_right","retreat"}.
        """
        assert self._ctx is not None
        cfg = self._ctx.config
        # Pull config with safe fallbacks
        OBSTACLE_EMERGENCY_STOP = getattr(cfg, "OBSTACLE_EMERGENCY_STOP", 15.0)
        OBSTACLE_SAFE_DISTANCE = getattr(cfg, "OBSTACLE_SAFE_DISTANCE", 40.0)
        OBSTACLE_APPROACHING_THREAT = getattr(cfg, "OBSTACLE_APPROACHING_THREAT", 35.0)
        TURN_STEPS_SMALL = getattr(cfg, "TURN_STEPS_SMALL", 1)
        TURN_STEPS_NORMAL = getattr(cfg, "TURN_STEPS_NORMAL", 2)
        # Emergency retreat
        if fwd < OBSTACLE_EMERGENCY_STOP:
            return ("retreat", {})
        # Approaching obstacle: steer to freer side
        if fwd < OBSTACLE_SAFE_DISTANCE:
            if left > right:
                return ("turn_left", {"steps": TURN_STEPS_NORMAL})
            else:
                return ("turn_right", {"steps": TURN_STEPS_NORMAL})
        # Side close? Bias away
        side_close = OBSTACLE_APPROACHING_THREAT
        if left < side_close and right >= left:
            return ("turn_right", {"steps": TURN_STEPS_SMALL})
        if right < side_close and left >= right:
            return ("turn_left", {"steps": TURN_STEPS_SMALL})
        # Clear path
        WALK_STEPS_NORMAL = getattr(cfg, "WALK_STEPS_NORMAL", 2)
        return ("forward", {"steps": WALK_STEPS_NORMAL})

    def _led_state(self, mode: str) -> None:
        """Set LED for mode if hardware/emotions enabled."""
        assert self._ctx is not None
        rgb = getattr(self._ctx.hardware, "rgb", None)
        enable = getattr(self._ctx.config, "ENABLE_EMOTIONAL_SYSTEM", getattr(self._ctx.config, "enable_emotional_system", False))
        if rgb is None or not enable:
            return
        try:
            if mode == "patrolling":
                rgb.set_color((0, 255, 0)); getattr(rgb, "breathe", lambda x: None)(1)
            elif mode == "obstacle":
                rgb.set_color((255, 0, 0)); getattr(rgb, "flash", lambda x: None)(1)
            elif mode == "navigating":
                rgb.set_color((255, 165, 0)); getattr(rgb, "breathe", lambda x: None)(1)
        except Exception:
            pass

    async def _loop(self) -> None:
        assert self._ctx is not None
        ctx = self._ctx
        dog = getattr(ctx.hardware, "dog", None)
        cfg = ctx.config
        scan_delay = max(0.2, float(getattr(cfg, "OBSTACLE_SCAN_INTERVAL", 0.5)))
        while self._running:
            fwd, left, right = self._scan()
            ctx.logger.info(f"Scan mm fwd={fwd:.0f} left={left:.0f} right={right:.0f}")
            action, params = self._decide(fwd, left, right)
            if dog is None:
                ctx.logger.info(f"[Sim] patrol action: {action} {params}")
                await asyncio.sleep(scan_delay)
                continue
            try:
                SPEED_SLOW = getattr(cfg, "SPEED_SLOW", 80)
                SPEED_EMERGENCY = getattr(cfg, "SPEED_EMERGENCY", 100)
                SPEED_TURN_NORMAL = getattr(cfg, "SPEED_TURN_NORMAL", 200)
                WALK_STEPS_NORMAL = getattr(cfg, "WALK_STEPS_NORMAL", 2)
                SPEED_NORMAL = getattr(cfg, "SPEED_NORMAL", 120)
                if action == "retreat":
                    self._led_state("obstacle")
                    dog.do_action("bark", speed=SPEED_SLOW)
                    await asyncio.sleep(0.2)
                    dog.do_action("backward", step_count=getattr(cfg, "BACKUP_STEPS", 3), speed=SPEED_EMERGENCY)
                elif action.startswith("turn_"):
                    self._led_state("navigating")
                    dir_name = action.replace("turn_", "")
                    dog.do_action(f"turn_{dir_name}", step_count=int(params.get("steps", getattr(cfg, "TURN_STEPS_SMALL", 1))), speed=SPEED_TURN_NORMAL)
                else:
                    self._led_state("patrolling")
                    dog.do_action("forward", step_count=WALK_STEPS_NORMAL, speed=SPEED_NORMAL)
                dog.wait_all_done()
            except Exception as e:
                ctx.logger.warning(f"Move failed: {e}")
            await asyncio.sleep(scan_delay)


# Expose class for orchestrator auto-detection
BEHAVIOR_CLASS = SmartPatrolBehavior
