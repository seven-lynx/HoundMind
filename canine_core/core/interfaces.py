"""
Behavior and Event interfaces for CanineCore.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable, Optional

@dataclass
class Event:
    type: str
    data: dict

class Logger(Protocol):
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...

@dataclass
class BehaviorContext:
    hardware: Any
    sensors: Any
    emotions: Any
    motion: Any
    voice: Any
    memory: Any
    state: Any
    logger: Logger
    config: Any
    publish: Any  # callable[[Event], None]
    # Optional services (may be None if disabled)
    safety: Any | None = None
    battery: Any | None = None
    imu: Any | None = None
    telemetry: Any | None = None
    sensors_facade: Any | None = None

@runtime_checkable
class Behavior(Protocol):
    name: str
    async def start(self, ctx: BehaviorContext) -> None: ...
    async def on_event(self, event: Event) -> None: ...
    async def stop(self) -> None: ...
