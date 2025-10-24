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
from collections import deque

from canine_core.utils.detection import Ema, VoteWindow, Cooldown

from canine_core.core.interfaces import Behavior, BehaviorContext, Event


class SmartPatrolBehavior(Behavior):
    name = "smart_patrol"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # Scan/baseline state
        self._baseline_mm: dict[int, float] = {}
        self._approach_votes: dict[int, deque[bool]] = {}
        self._scan_dir: int = 1
        self._alert_cd: Optional[Cooldown] = None

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
    async def _move_head_and_read(self, yaw_deg: int, settle_s: float, move_speed: int) -> float:
        """Move head yaw then read distance; fall back to immediate read if motion unsupported."""
        assert self._ctx is not None
        dog = getattr(self._ctx.hardware, "dog", None)
        if dog is None:
            await asyncio.sleep(max(0.0, settle_s * 0.5))
            return 1000.0
        try:
            yaw_cmd = max(-80, min(80, int(yaw_deg)))
            dog.head_move([[yaw_cmd, 0, 0]], speed=move_speed)
            await asyncio.sleep(settle_s)
            return float(dog.read_distance() or 1000.0)
        except Exception as e:
            self._ctx.logger.warning(f"Head move/read failed: {e}")
            await asyncio.sleep(max(0.0, settle_s * 0.5))
            return 1000.0

    async def _quick_scan(self) -> Tuple[float, float, float]:
        """Scan left, right, and forward; update per-angle EMA baselines and votes.
        Returns distances in mm (fwd, left, right).
        """
        assert self._ctx is not None
        cfg = self._ctx.config
        yaw_max = int(getattr(cfg, "PATROL_SCAN_YAW_MAX_DEG", 45))
        settle_s = float(getattr(cfg, "PATROL_SCAN_SETTLE_S", 0.12))
        between_s = float(getattr(cfg, "PATROL_BETWEEN_READS_S", 0.04))
        ema_alpha = float(getattr(cfg, "PATROL_BASELINE_EMA", 0.25))
        move_speed = int(getattr(cfg, "HEAD_SCAN_SPEED", 70))

        # angles: left, right, forward
        angles = [-yaw_max, yaw_max, 0]
        out: dict[int, float] = {}
        for yaw in angles:
            dist = await self._move_head_and_read(yaw, settle_s, move_speed)
            base = self._baseline_mm.get(yaw)
            if base is None:
                self._baseline_mm[yaw] = dist
            else:
                new_base = (1.0 - ema_alpha) * base + ema_alpha * dist
                self._baseline_mm[yaw] = new_base
            out[yaw] = dist
            await asyncio.sleep(between_s)
        # center head at end (best effort)
        try:
            await self._move_head_and_read(0, max(0.05, settle_s * 0.5), move_speed)
        except Exception:
            pass
        fwd, left, right = out.get(0, 1000.0), out.get(-yaw_max, 1000.0), out.get(yaw_max, 1000.0)
        return (fwd, left, right)

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
        # cooldown for approach-triggered maneuvers
        self._alert_cd = Cooldown(float(getattr(cfg, "PATROL_ALERT_COOLDOWN_S", 2.0)))
        while self._running:
            fwd, left, right = await self._quick_scan()
            ctx.logger.info(f"Patrol scan mm fwd={fwd:.0f} left={left:.0f} right={right:.0f}")
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
                # Approach detection on forward angle using baseline
                base_fwd = self._baseline_mm.get(0, fwd)
                delta_mm = float(getattr(cfg, "PATROL_APPROACH_DEVIATION_MM", 100.0))
                delta_pct = float(getattr(cfg, "PATROL_APPROACH_DEVIATION_PCT", 0.20))
                delta = max(0.0, base_fwd - fwd)
                pct = (delta / base_fwd) if base_fwd > 1e-6 else 0.0
                approaching = (delta >= delta_mm) or (pct >= delta_pct)
                # vote window for forward-only
                vw = self._approach_votes.get(0)
                if vw is None or vw.maxlen != max(1, int(getattr(cfg, "PATROL_CONFIRM_WINDOW", 3))):
                    vw = deque(maxlen=max(1, int(getattr(cfg, "PATROL_CONFIRM_WINDOW", 3))))
                    self._approach_votes[0] = vw
                vw.append(bool(approaching))
                confirmed = sum(1 for v in vw if v) >= int(getattr(cfg, "PATROL_CONFIRM_THRESHOLD", 2))

                if action == "retreat":
                    self._led_state("obstacle")
                    dog.do_action("bark", speed=SPEED_SLOW)
                    await asyncio.sleep(0.2)
                    dog.do_action("backward", step_count=getattr(cfg, "BACKUP_STEPS", 3), speed=SPEED_EMERGENCY)
                elif confirmed and self._alert_cd and self._alert_cd.ready():
                    # micro backoff + small turn toward freer side
                    self._led_state("navigating")
                    self._alert_cd.touch()
                    turn_steps = int(getattr(cfg, "PATROL_TURN_STEPS_ON_ALERT", 1))
                    # choose freer side by comparing left/right
                    dir_name = "left" if left > right else "right"
                    dog.do_action("backward", step_count=max(1, int(getattr(cfg, "BACKUP_STEPS", 3) // 2)), speed=SPEED_EMERGENCY)
                    dog.wait_all_done()
                    dog.do_action(f"turn_{dir_name}", step_count=turn_steps, speed=SPEED_TURN_NORMAL)
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
