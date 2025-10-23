#!/usr/bin/env python3
"""
Whisper Voice Control Behavior

Separate voice control mode that uses the same VoiceService but treats wake word
as optional for more free-form control. Provides a different UX than Voice Patrol.
"""
from __future__ import annotations
import asyncio
from typing import Optional

from canine_core.core.interfaces import Behavior, BehaviorContext, Event


class WhisperVoiceControlBehavior(Behavior):
    name = "whisper_voice_control"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        self._running = True
        try:
            ctx.state.set("active_mode", "whisper_voice")
        except Exception:
            pass
        # In this mode, we accept commands without the wake word (if voice service supports it)
        voice = getattr(ctx, 'voice', None)
        if voice is not None:
            voice.wake_word = ""  # optional
        ctx.logger.info("WhisperVoiceControl starting")
        self._task = asyncio.create_task(self._loop())

    async def on_event(self, event: Event) -> None:
        return

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                pass
        if self._ctx:
            self._ctx.logger.info("WhisperVoiceControl stopped")

    def _execute(self, cmd: str) -> None:
        assert self._ctx is not None
        dog = getattr(self._ctx.hardware, "dog", None)
        if dog is None:
            self._ctx.logger.info(f"[Sim] whisper command: {cmd}")
            return
        cfg = self._ctx.config
        try:
            if cmd.startswith("left") or cmd.startswith("turn left"):
                dog.do_action("turn_left", step_count=getattr(cfg, "TURN_STEPS_SMALL", 1), speed=getattr(cfg, "SPEED_TURN_NORMAL", 200))
            elif cmd.startswith("right") or cmd.startswith("turn right"):
                dog.do_action("turn_right", step_count=getattr(cfg, "TURN_STEPS_SMALL", 1), speed=getattr(cfg, "SPEED_TURN_NORMAL", 200))
            elif cmd.startswith("forward") or cmd.startswith("go"):
                dog.do_action("forward", step_count=getattr(cfg, "WALK_STEPS_SHORT", 1), speed=getattr(cfg, "SPEED_NORMAL", 120))
            elif cmd.startswith("back"):
                dog.do_action("backward", step_count=getattr(cfg, "WALK_STEPS_SHORT", 1), speed=getattr(cfg, "SPEED_NORMAL", 120))
            elif cmd.startswith("sit"):
                dog.do_action("sit", speed=getattr(cfg, "SPEED_SLOW", 80))
            elif cmd.startswith("stand"):
                dog.do_action("stand", speed=getattr(cfg, "SPEED_SLOW", 80))
            elif cmd.startswith("stop"):
                dog.do_action("stand", speed=getattr(cfg, "SPEED_SLOW", 80))
            else:
                self._ctx.logger.info(f"[Whisper] Unknown command: {cmd}")
                return
            dog.wait_all_done()
        except Exception as e:
            self._ctx.logger.warning(f"Whisper command failed: {e}")

    async def _loop(self) -> None:
        assert self._ctx is not None
        ctx = self._ctx
        voice = getattr(ctx, 'voice', None)
        if not voice or not getattr(voice, 'enabled', False):
            ctx.logger.info("Voice service disabled or unavailable; idle")
            while self._running:
                await asyncio.sleep(0.5)
            return
        async for cmd in voice.listen_commands():
            if not self._running:
                break
            if not cmd:
                continue
            self._execute(cmd)


BEHAVIOR_CLASS = WhisperVoiceControlBehavior
