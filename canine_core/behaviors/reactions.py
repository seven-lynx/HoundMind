#!/usr/bin/env python3
"""
CanineCore Reactions Behavior (Converted)

Combines touch, IMU, and sound reactions into a cooperative Behavior.
- Touch → wag/scratch + emotion cues
- IMU (lift/flip) → safe responses + emotion updates
- Sound → turn head; body turn only if above threshold

Hardware-safe: works in simulation when hardware/sensors are unavailable.
"""
from __future__ import annotations
import asyncio
import random
import time
from typing import Optional

from canine_core.core.interfaces import Behavior, BehaviorContext, Event

# Optional sound sensor import
try:
    from pidog.sound_sensor import SoundSensor  # type: ignore
except Exception:  # pragma: no cover - dev hosts
    SoundSensor = None  # type: ignore


class ReactionsBehavior(Behavior):
    name = "reactions"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sound: Optional[object] = None
        # Debounce/cooldown trackers
        self._last_touch_ts: float = 0.0
        self._last_imu_ts: float = 0.0
        self._last_sound_turn_ts: float = 0.0

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        self._running = True
        try:
            ctx.state.set("active_mode", "reacting")
        except Exception:
            pass
        # Try to set neutral LED
        rgb = getattr(ctx.hardware, "rgb", None)
        try:
            if rgb is not None and getattr(ctx.config, "ENABLE_EMOTIONAL_SYSTEM", getattr(ctx.config, "enable_emotional_system", False)):
                rgb.set_color((255, 255, 255))
        except Exception:
            pass
        # Attempt to create sound sensor
        try:
            if SoundSensor is not None and getattr(ctx.hardware, "dog", None) is not None:
                self._sound = SoundSensor(ctx.hardware.dog)
        except Exception:
            self._sound = None
        ctx.logger.info("Reactions starting")
        self._task = asyncio.create_task(self._loop())

    async def on_event(self, event: Event) -> None:
        # Future: react to bus events (voice command, external triggers)
        return

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                pass
        if self._ctx:
            # Reset to idle color and posture if available
            rgb = getattr(self._ctx.hardware, "rgb", None)
            dog = getattr(self._ctx.hardware, "dog", None)
            try:
                if rgb is not None:
                    rgb.set_color((255, 255, 255))
            except Exception:
                pass
            try:
                if dog is not None:
                    dog.do_action("stand", speed=getattr(self._ctx.config, "SPEED_SLOW", 80))
                    dog.wait_all_done()
            except Exception:
                pass
            self._ctx.logger.info("Reactions stopped")

    # --- reaction primitives ---
    def _emotion(self, color: tuple[int, int, int], effect: str | None = None) -> None:
        assert self._ctx is not None
        rgb = getattr(self._ctx.hardware, "rgb", None)
        enable = getattr(self._ctx.config, "ENABLE_EMOTIONAL_SYSTEM", getattr(self._ctx.config, "enable_emotional_system", False))
        if rgb is None or not enable:
            return
        try:
            rgb.set_color(color)
            if effect and hasattr(rgb, effect):
                getattr(rgb, effect)(1)
        except Exception:
            pass

    def _touch(self) -> None:
        assert self._ctx is not None
        dog = getattr(self._ctx.hardware, "dog", None)
        if dog is None:
            return
        try:
            td = getattr(dog, "touchData", None)
            if not td:
                return
            # Debounce
            debounce = float(getattr(self._ctx.config, "TOUCH_DEBOUNCE_S", 0.1))
            now = time.monotonic()
            if now - self._last_touch_ts < max(0.0, debounce):
                return
            # Head touch
            if td[0]:
                self._emotion((0, 255, 0), "breathe")
                try:
                    dog.do_action("tail_wag", speed=90)
                    dog.wait_all_done()
                except Exception:
                    pass
                # learning: record head touch
                try:
                    if getattr(self._ctx, "learning", None) is not None:
                        self._ctx.learning.record_interaction("touch_head")
                except Exception:
                    pass
            # Body touch
            if len(td) > 1 and td[1]:
                self._emotion((255, 165, 0), "breathe")
                try:
                    dog.do_action("lay_down", speed=70)
                    dog.wait_all_done()
                except Exception:
                    pass
                # learning: record body touch
                try:
                    if getattr(self._ctx, "learning", None) is not None:
                        self._ctx.learning.record_interaction("touch_body")
                except Exception:
                    pass
            self._last_touch_ts = now
        except Exception:
            return

    def _imu(self) -> None:
        assert self._ctx is not None
        dog = getattr(self._ctx.hardware, "dog", None)
        if dog is None:
            return
        try:
            acc = getattr(dog, "accData", None)
            if not acc:
                return
            ax, ay, az = acc[0], acc[1], acc[2]
            # Config thresholds
            lift_thr = int(getattr(self._ctx.config, "REACTIONS_LIFT_THRESHOLD", 25000))
            place_thr = int(getattr(self._ctx.config, "REACTIONS_PLACE_THRESHOLD", -25000))
            flip_thr = int(getattr(self._ctx.config, "REACTIONS_FLIP_ROLL_THRESHOLD", 30000))
            cd = float(getattr(self._ctx.config, "REACTION_COOLDOWN_S", 1.0))
            now = time.monotonic()
            if now - self._last_imu_ts < max(0.0, cd):
                return
            # Lift/placement heuristics (config-driven)
            if ax and ax > lift_thr:  # lifted
                self._emotion((255, 0, 0), "flash")
                try:
                    dog.do_action("bark", speed=80)
                    dog.wait_all_done()
                except Exception:
                    pass
                try:
                    if getattr(self._ctx, "learning", None) is not None:
                        self._ctx.learning.record_interaction("imu_lift")
                except Exception:
                    pass
                self._last_imu_ts = now
            elif ax and ax < place_thr:  # placed down
                self._emotion((255, 255, 255))
                try:
                    dog.do_action("sit", speed=60)
                    dog.wait_all_done()
                except Exception:
                    pass
                try:
                    if getattr(self._ctx, "learning", None) is not None:
                        self._ctx.learning.record_interaction("imu_place")
                except Exception:
                    pass
                self._last_imu_ts = now
            # Flip detection via roll magnitude
            roll = ay
            if roll and abs(roll) > flip_thr:
                self._emotion((0, 0, 255), "breathe")
                try:
                    dog.do_action("head_tilt", speed=70)
                    dog.wait_all_done()
                except Exception:
                    pass
                try:
                    if getattr(self._ctx, "learning", None) is not None:
                        self._ctx.learning.record_interaction("imu_flip")
                except Exception:
                    pass
                self._last_imu_ts = now
        except Exception:
            return

    def _sound_react(self) -> None:
        assert self._ctx is not None
        dog = getattr(self._ctx.hardware, "dog", None)
        if dog is None or self._sound is None:
            return
        try:
            if self._sound.isdetected():  # type: ignore[attr-defined]
                direction = int(self._sound.read())  # type: ignore[attr-defined]
                # Head look toward the sound
                dog.head_move([[direction, 0, 0]], speed=getattr(self._ctx.config, "HEAD_SCAN_SPEED", 70))
                dog.wait_head_done()
                # Body turn if significant
                threshold = getattr(self._ctx.config, "SOUND_BODY_TURN_THRESHOLD", 45)
                scd = float(getattr(self._ctx.config, "SOUND_COOLDOWN_S", 1.5))
                now = time.monotonic()
                if abs(direction) >= threshold and (now - self._last_sound_turn_ts) >= max(0.0, scd):
                    self._emotion((255, 165, 0), "flash")
                    if direction > 0:
                        dog.do_action("turn_right", step_count=1, speed=getattr(self._ctx.config, "SPEED_TURN_NORMAL", 200))
                    else:
                        dog.do_action("turn_left", step_count=1, speed=getattr(self._ctx.config, "SPEED_TURN_NORMAL", 200))
                    dog.wait_all_done()
                    self._last_sound_turn_ts = now
                    # learning: record sound-induced turn
                    try:
                        if getattr(self._ctx, "learning", None) is not None:
                            label = "sound_turn_right" if direction > 0 else "sound_turn_left"
                            self._ctx.learning.record_interaction(label)
                    except Exception:
                        pass
        except Exception:
            return

    async def _loop(self) -> None:
        assert self._ctx is not None
        interval = float(getattr(self._ctx.config, "REACTIONS_INTERVAL", 0.5))
        while self._running:
            self._touch()
            self._imu()
            self._sound_react()
            await asyncio.sleep(interval)


BEHAVIOR_CLASS = ReactionsBehavior
