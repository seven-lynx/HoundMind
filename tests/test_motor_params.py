"""A parameter the catalog declares reaches the HAL, whatever the action's class (#69).

`config/actions.jsonc` is the promise; `hal/motors.py` is the path that has to keep it. These cases
hold the two halves together for the posture class, which until #69 declared no parameters at all
and dropped every one that arrived - so `stand {wait: true}` ran the pose and moved on to the next
step while the dog was still getting up.
"""

from __future__ import annotations

import time

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.module import HalModule
from houndmind_ai.hal.motors import MotorModule


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def rig() -> tuple[FakeDogHAL, RuntimeContext, MotorModule]:
    hal = FakeDogHAL()
    context = RuntimeContext()
    context.set("settings", {"motors": {"min_action_interval_s": 0.0}})
    HalModule("hal", hal=hal).start(context)
    motors = MotorModule("hal_motors")
    motors.start(context)
    return hal, context, motors


def command(context, action: str, **params) -> None:
    context.set("motion_command", {"canonical_action": action, "params": params})


def test_a_waiting_posture_step_reaches_the_hal_with_its_parameter() -> None:
    hal, context, motors = rig()
    try:
        command(context, "stand", wait=True)
        motors.tick(context)

        assert wait_until(lambda: hal.calls), "the step never reached the HAL"
        assert hal.calls[0] == ("stand", {"wait": True})
    finally:
        motors.stop(context)


def test_a_waiting_pose_runs_on_the_worker_not_the_tick(monkeypatch) -> None:
    """`wait` means the call blocks until the pose is done, which is exactly off-tick work."""
    hal, context, motors = rig()
    original = hal.action

    def slow_action(name: str, params: dict) -> None:
        time.sleep(0.15)
        original(name, params)

    monkeypatch.setattr(hal, "action", slow_action)
    try:
        command(context, "stand", wait=True)
        started = time.monotonic()
        motors.tick(context)
        elapsed = time.monotonic() - started

        assert elapsed < 0.1, "the tick waited for the pose"
        assert wait_until(lambda: hal.calls), "the pose never ran"
        assert hal.calls[0][0] == "stand"
    finally:
        motors.stop(context)


def test_a_bare_posture_step_still_goes_straight_through() -> None:
    """No parameters means nothing to carry: the step stays on the tick, as it always was."""
    hal, context, motors = rig()
    try:
        command(context, "sit")
        motors.tick(context)

        assert hal.calls == [("sit", {})]
    finally:
        motors.stop(context)


def test_a_parameter_the_catalog_withholds_is_not_forwarded() -> None:
    """`speed` is not one of the keys a step may carry for a posture: nothing invents one."""
    hal, context, motors = rig()
    try:
        command(context, "sit", speed=50)
        motors.tick(context)

        # `speed` is a generic key, so it is forwarded for whatever action names it; what keeps a
        # routine honest is the validator (`kernel/routine.py`), which refuses it at load time.
        assert hal.calls == [("sit", {"speed": 50})]
    finally:
        motors.stop(context)
