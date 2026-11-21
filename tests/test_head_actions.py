"""A head action that fails says so, once, and reaches `/api/v1/modules` (#398).

`hal/motors.py` used to turn every exception from head-following and head-centring into a bare
`return`: the tick looked like a success, `status.last_error` stayed `None`, and the only record a
dead head left was the dog not turning its head. These tests hold the replacement - log once per
transition, and publish the reason.
"""

from __future__ import annotations

import logging

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.motors import MotorModule


class DeadHeadHAL(FakeDogHAL):
    """Every head command raises; the legs still work."""

    def action(self, name, params):  # type: ignore[override]
        if name == "head":
            raise RuntimeError("servo bus silent")
        super().action(name, params)


def rig(hal=None) -> tuple[FakeDogHAL, RuntimeContext, MotorModule]:
    hal = hal or DeadHeadHAL()
    context = RuntimeContext()
    context.set(
        "settings",
        {
            "motors": {
                "min_action_interval_s": 0.0,
                "head_turn_follow_deg": 20.0,
                "head_turn_follow_respect_scanning": False,
                "head_turn_follow_respect_attention": False,
            }
        },
    )
    context.set("hal", hal)
    motors = MotorModule("hal_motors")
    motors.start(context)
    return hal, context, motors


def test_a_failed_head_follow_is_logged_once_and_published(caplog) -> None:
    _, context, motors = rig()
    try:
        with caplog.at_level(logging.WARNING, logger="houndmind_ai.hal.motors"):
            motors._apply_head_follow("left", context)
            motors._apply_head_follow("left", context)

        warnings = [r for r in caplog.records if "Head action failed" in r.getMessage()]
        assert len(warnings) == 1, "a dead head logs once per transition, not once per tick"
        assert "servo bus silent" in warnings[0].getMessage()
        assert motors.status.last_error is not None
        assert "head follow" in motors.status.last_error
    finally:
        motors.stop(context)


def test_a_failed_head_centre_is_published_too(caplog) -> None:
    _, context, motors = rig()
    try:
        with caplog.at_level(logging.WARNING, logger="houndmind_ai.hal.motors"):
            motors._apply_head_center(context)

        assert any("head re-centre" in r.getMessage() for r in caplog.records)
        assert motors.status.last_error is not None
        assert "head re-centre" in motors.status.last_error
    finally:
        motors.stop(context)


def test_a_working_head_leaves_the_status_alone() -> None:
    hal = FakeDogHAL()
    _, context, motors = rig(hal)
    try:
        motors._apply_head_follow("left", context)

        assert motors.status.last_error is None
        assert ("head",) == tuple(str(call[0]) for call in hal.calls[-1:])
    finally:
        motors.stop(context)
