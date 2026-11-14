"""The navigation retreat: once, on the worker, and never on a stale payload.

`obstacle_avoidance` writes `navigation_followup` and nothing cleared it, so `hal_motors` re-ran the
same retreat after every later command. The sequence also ran inline, and the closed-loop turn it
ends with waits on the servos for up to `orientation.turn_timeout_s` against a 200 ms tick (#120).
"""

from __future__ import annotations

import time

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.motors import MotorModule


class SlowTurnDog(FakeDogHAL):
    """A dog whose turn takes real time, so "did this block the tick" is measurable."""

    def action(self, name: str, params: dict) -> None:
        if name in ("turn_left", "turn_right"):
            time.sleep(0.15)
        super().action(name, params)


def build(followup: dict | None = None, hal: FakeDogHAL | None = None):
    dog = hal or FakeDogHAL()
    context = RuntimeContext()
    context.set("hal", dog)
    context.set("settings", {"movement": {"followup_ttl_s": 1.0}})
    if followup is not None:
        context.set("navigation_followup", followup)
    module = MotorModule("hal_motors")
    module.start(context)
    return module, context, dog


def ask(context, action: str = "forward") -> None:
    context.set("motion_command", {"canonical_action": action, "params": {}})


def settle(module: MotorModule, timeout: float = 2.0) -> None:
    """Wait for the motor worker to finish, without asserting on wall-clock timing."""
    deadline = time.time() + timeout
    while module.worker is not None and module.worker.busy and time.time() < deadline:
        time.sleep(0.01)


def retreat(**overrides) -> dict:
    payload = {
        "timestamp": time.time(),
        "type": "retreat_turn",
        "backup_steps": 2,
        "direction": "left",
    }
    payload.update(overrides)
    return payload


def count(dog: FakeDogHAL, action: str) -> int:
    return sum(1 for name, _params in dog.calls if name == action)


def test_the_retreat_runs_and_is_then_retracted() -> None:
    module, context, dog = build(retreat())

    ask(context)
    module.tick(context)
    settle(module)

    assert count(dog, "backward") == 2
    assert context.get("navigation_followup") is None


def test_a_later_command_does_not_re_run_the_retreat() -> None:
    """The defect #120 reported: the key stayed set, so every command retreated again."""
    module, context, dog = build(retreat())
    ask(context)
    module.tick(context)
    settle(module)

    ask(context, "sit")
    module.tick(context)
    settle(module)
    ask(context, "stretch")
    module.tick(context)
    settle(module)

    assert count(dog, "backward") == 2
    assert count(dog, "turn_left") == 2


def test_a_stale_followup_is_dropped_not_run_late() -> None:
    module, context, dog = build(retreat(timestamp=time.time() - 30.0))

    ask(context)
    module.tick(context)
    settle(module)

    assert count(dog, "backward") == 0
    assert context.get("navigation_followup") is None


def test_the_retreat_runs_off_the_tick() -> None:
    """A turn waits on the servos; the decision loop must not wait with it."""
    module, context, dog = build(retreat(backup_steps=1), hal=SlowTurnDog())
    ask(context)

    started = time.perf_counter()
    module.tick(context)
    elapsed = time.perf_counter() - started

    settle(module)
    assert elapsed < 0.1, f"the tick blocked for {elapsed:.3f} s"
    assert count(dog, "turn_left") == 1


def test_a_sequence_followup_runs_its_steps_in_order() -> None:
    module, context, dog = build(
        {
            "timestamp": time.time(),
            "type": "sequence",
            "actions": ["backward", "turn left", "forward"],
        }
    )

    ask(context)
    module.tick(context)
    settle(module)

    assert [name for name, _params in dog.calls] == ["forward", "backward", "turn_left", "forward"]
