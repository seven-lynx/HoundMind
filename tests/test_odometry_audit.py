"""The range-aided audit: predicted against actual, logged and never applied (#300).

`step_cm` is one number standing behind every place anchor and every map dot, and a 10 % error in it
compounds over a room. This audit compares each forward step with what the sonar saw, records the
comparison, and changes nothing: the constant moves only through `step_calibrate --apply`.

The reading is a stand-in with the two attributes the module reads, which is the whole contract
between odometry and the sensor module.
"""

from __future__ import annotations

from types import SimpleNamespace

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.navigation.odometry import (
    AUDIT_MAX_CM,
    AUDIT_TIMEOUT_S,
    OdometryModule,
)


class _Clock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _setup(**settings: object) -> tuple[OdometryModule, RuntimeContext, _Clock]:
    clock = _Clock()
    module = OdometryModule("odometry", enabled=True)
    module._clock = clock
    context = RuntimeContext()
    context.set("settings", {"odometry": {"step_cm": 8.0, **settings}})
    context.set("current_heading", 0.0)
    return module, context, clock


def _reading(context: RuntimeContext, cm: float, valid: bool = True) -> None:
    context.set(
        "sensor_reading",
        SimpleNamespace(distance_cm=cm, distance_valid=valid, touch_valid=False),
    )


def _command(context: RuntimeContext, seq: int, action: str = "forward") -> None:
    context.set(
        "motion_command",
        {"seq": seq, "canonical_action": action, "action": action},
    )


def _audit(context: RuntimeContext) -> dict | None:
    return (context.get("odometry") or {}).get("audit")


def test_a_forward_step_is_audited_against_the_next_reading() -> None:
    module, context, _ = _setup(step_cm=8.0, surface="hardwood")
    _reading(context, 120.0)
    _command(context, seq=1)
    module.tick(context)

    _reading(context, 112.0)
    module.tick(context)

    audit = _audit(context)
    assert audit["surface"] == "hardwood"
    assert audit["predicted_cm"] == 8.0
    assert audit["actual_cm"] == 8.0
    assert audit["ratio"] == 1.0


def test_a_reading_beyond_the_audit_range_teaches_nothing() -> None:
    """Past 250 cm the sonar's own error is larger than a gait cycle, so it is not evidence."""
    module, context, _ = _setup()
    _reading(context, AUDIT_MAX_CM + 5.0)
    _command(context, seq=1)
    module.tick(context)

    _reading(context, AUDIT_MAX_CM - 5.0)
    module.tick(context)

    assert _audit(context) is None


def test_an_invalid_reading_is_never_a_measurement() -> None:
    module, context, _ = _setup()
    _reading(context, 120.0, valid=False)
    _command(context, seq=1)
    module.tick(context)

    _reading(context, 100.0, valid=True)
    module.tick(context)

    assert _audit(context) is None


def test_the_same_echo_is_not_a_step() -> None:
    """The reading has to move: an unchanged one means the sensor has not caught up, not zero travel."""
    module, context, _ = _setup()
    _reading(context, 120.0)
    _command(context, seq=1)
    module.tick(context)

    module.tick(context)  # same reading, no step
    assert _audit(context) is None

    _reading(context, 112.0)
    module.tick(context)
    assert _audit(context) is not None


def test_a_step_whose_reading_never_arrives_expires() -> None:
    module, context, clock = _setup()
    _reading(context, 120.0)
    _command(context, seq=1)
    module.tick(context)

    clock.advance(AUDIT_TIMEOUT_S + 0.5)
    _reading(context, 100.0)
    module.tick(context)

    assert _audit(context) is None, "past the deadline the reading is no longer about this step"


def test_a_backward_step_is_not_audited() -> None:
    """Only a forward step closes on a wall; a retreat has no surface to measure against."""
    module, context, _ = _setup()
    _reading(context, 120.0)
    _command(context, seq=1, action="backward")
    module.tick(context)

    _reading(context, 140.0)
    module.tick(context)

    assert _audit(context) is None


def test_the_audit_changes_no_constant() -> None:
    """#300 is log-only: the settings the module read are the settings it leaves."""
    module, context, _ = _setup(step_cm=8.0, surface="hardwood")
    settings_before = dict(context.get("settings")["odometry"])
    _reading(context, 120.0)
    _command(context, seq=1)
    module.tick(context)
    _reading(context, 108.0)
    module.tick(context)

    assert context.get("settings")["odometry"] == settings_before
    assert context.get("odometry")["step_cm"] == 8.0
