"""The `head` action must reach the vendor on the axis it names.

`Pidog.head_move` reads each target as `[yaw, roll, pitch]`; `head_rpy_to_angle` unpacks it in
that order. The adapter used to build `[yaw, pitch, 0]`, so a caller's `pitch` rolled the head and
the pitch channel stayed at zero (#59). `PidogHAL` takes an injected `dog`, which is how the
mapping is checked without importing `pidog` on a workstation.
"""

from __future__ import annotations

from typing import Any

from houndmind_ai.hal.vendor import PidogHAL


class RecordingDog:
    """Captures the target list `head_move` was handed, and the speed it came with."""

    def __init__(self) -> None:
        self.targets: list[Any] = []
        self.speed: int | None = None

    def head_move(self, target_yrps: Any, speed: int = 50, **kwargs: Any) -> None:
        self.targets = list(target_yrps)
        self.speed = speed

    def wait_head_done(self) -> None:
        return None


def test_pitch_reaches_the_pitch_slot() -> None:
    """`[yaw, roll, pitch]` is the vendor order: a pitch must not become a roll."""
    dog = RecordingDog()
    hal = PidogHAL(settings={}, dog=dog)

    hal.action("head", {"yaw": 30.0, "pitch": -20.0, "speed": 70})

    assert dog.targets == [[30.0, 0.0, -20.0]]


def test_yaw_only_leaves_the_head_level() -> None:
    """The shape every caller in the tree sends: yaw to look sideways, pitch level."""
    dog = RecordingDog()
    hal = PidogHAL(settings={}, dog=dog)

    hal.action("head", {"yaw": 45.0, "pitch": 0, "speed": 70, "wait": True})

    assert dog.targets == [[45.0, 0.0, 0.0]]
    assert dog.speed == 70


def test_absent_params_do_not_invent_an_angle() -> None:
    """Nothing in, nothing out: a missing key is 0.0, never a stale value."""
    dog = RecordingDog()
    hal = PidogHAL(settings={}, dog=dog)

    hal.action("head", {})

    assert dog.targets == [[0.0, 0.0, 0.0]]
