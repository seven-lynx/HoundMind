"""The record names the autonomy behind a tick, and says when nothing could win (#270).

`driver` already named *which* autonomy source shaped the tick. Two questions a reader still could
not answer: what mode autonomy was in when it shaped it, and whether a run of ticks where nobody won
was a decision or a hang. Both are fields now — `autonomy_mode`/`autonomy_weight` and `status` — and
each test here pins one of them against the gateway that writes them, or against the FSM that
publishes the choice.
"""

from __future__ import annotations

import logging

from houndmind_ai.act.gateway import UNDECIDED_ALERT_TICKS, MotionGatewayModule
from houndmind_ai.act.interlock import Interlock
from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.decisions import DECISION_STATUSES, DecisionRecord
from houndmind_ai.kernel.intents import IntentBoard
from houndmind_ai.services.state import build_state


class Clock:
    """A clock that only moves when a test moves it, shared with the board."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def build(reading: SensorReading | None = None) -> tuple[MotionGatewayModule, RuntimeContext]:
    clock = Clock()
    gateway = MotionGatewayModule(
        "motion_gateway",
        interlock=Interlock(now=clock),
        clock=clock,
        board=IntentBoard(clock=clock),
    )
    context = RuntimeContext()
    gateway.start(context)
    if reading is not None:
        context.set("sensor_reading", reading)
    return gateway, context


def reading(distance_cm: float) -> SensorReading:
    return SensorReading(
        distance_cm=distance_cm,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=(0.0, 0.0, 9.8),
        gyro=(0.0, 0.0, 0.0),
        timestamp=1000.0,
        distance_valid=True,
        touch_valid=True,
        sound_valid=True,
        imu_valid=True,
    )


def record(context) -> DecisionRecord:
    published = context.get("decision_record")
    assert isinstance(published, DecisionRecord)
    return published


# ------------------------------------------------------------------ the autonomy pair


def test_an_autonomy_tick_names_the_mode_and_the_weight() -> None:
    gateway, context = build()
    context.set("autonomy_choice", {"mode": "patrol", "weight": 1.5})
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)

    published = record(context)
    assert published.driver == "navigation"
    assert published.autonomy_mode == "patrol"
    assert published.autonomy_weight == 1.5


def test_a_weight_the_fsm_did_not_compute_stays_absent() -> None:
    """An energy gate picks a mode without a draw, so there is no weight to name."""
    gateway, context = build()
    context.set("autonomy_choice", {"mode": "rest", "weight": None})
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)

    assert record(context).autonomy_mode == "rest"
    assert record(context).autonomy_weight is None


def test_a_hand_driven_tick_inherits_no_mode() -> None:
    """The key outlives the tick that wrote it, so only a tick autonomy shaped may name it."""
    gateway, context = build()
    context.set("autonomy_choice", {"mode": "patrol", "weight": 1.5})
    context.get("intent_board").publish("lie", Source.SYSTEM)
    gateway.tick(context)

    published = record(context)
    assert published.source == "system"
    assert published.driver is None
    assert published.autonomy_mode is None
    assert published.autonomy_weight is None


def test_a_junk_choice_is_not_repeated() -> None:
    gateway, context = build()
    context.set("autonomy_choice", {"mode": "", "weight": "heavy"})
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)

    published = record(context)
    assert published.autonomy_mode is None
    assert published.autonomy_weight is None


def test_a_choice_that_is_not_a_mapping_is_ignored() -> None:
    gateway, context = build()
    context.set("autonomy_choice", "patrol")
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)

    assert record(context).autonomy_mode is None


# ------------------------------------------------------------------ the status word


def test_a_silent_tick_is_recorded_as_silent() -> None:
    gateway, context = build()
    gateway.tick(context)

    assert record(context).status == "silent"
    assert record(context).status in DECISION_STATUSES


def test_a_tick_that_refused_everything_is_recorded_as_undecided() -> None:
    """Nothing won, but something asked: the tick a parked dog and a hang used to share (#270)."""
    gateway, context = build()
    context.set("runtime_mode", "rest")
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)

    published = record(context)
    assert published.intent is None
    # Autonomy was on the board and was overruled, which `driver` names even without a winner.
    assert published.driver == "navigation"
    assert published.status == "undecided"
    assert context.get("motion_verdict")["status"] == published.status


def test_an_accepted_tick_and_a_refused_one_name_their_outcome() -> None:
    gateway, context = build(reading=reading(100.0))
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)
    assert record(context).status == "accepted"

    gateway, context = build(reading=reading(10.0))
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)

    published = record(context)
    assert published.status == "refused"
    assert published.vetoes[0].reason == "obstacle"
    assert context.get("motion_verdict")["status"] == published.status


def test_the_state_snapshot_carries_the_status_and_the_autonomy_pair() -> None:
    gateway, context = build()
    context.set("autonomy_choice", {"mode": "play", "weight": 3.0})
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)

    decision = build_state(context, now=1001.0)["decision"]

    assert isinstance(decision, dict)
    assert decision["status"] == "accepted"
    assert decision["autonomy_mode"] == "play"
    assert decision["autonomy_weight"] == 3.0


# ------------------------------------------------------------------ the undecided alert


def _undecided_tick(gateway, context) -> None:
    context.get("intent_board").publish("forward", Source.NAVIGATION)
    gateway.tick(context)


def test_a_long_undecided_run_warns_once(caplog) -> None:
    gateway, context = build()
    context.set("runtime_mode", "rest")

    with caplog.at_level(logging.WARNING, logger="houndmind_ai.act.gateway"):
        for _ in range(UNDECIDED_ALERT_TICKS - 1):
            _undecided_tick(gateway, context)
        assert not [item for item in caplog.records if "in a row" in item.getMessage()]
        _undecided_tick(gateway, context)

    warnings = [item for item in caplog.records if "in a row" in item.getMessage()]
    assert len(warnings) == 1
    assert f"{UNDECIDED_ALERT_TICKS} ticks" in warnings[0].getMessage()
    assert "navigation:mode" in warnings[0].getMessage()


def test_a_decided_tick_resets_the_undecided_run(caplog) -> None:
    """The alert is about a *run*, so one tick that decided hides the log line entirely."""
    gateway, context = build()
    context.set("runtime_mode", "rest")

    with caplog.at_level(logging.WARNING, logger="houndmind_ai.act.gateway"):
        for _ in range(UNDECIDED_ALERT_TICKS - 1):
            _undecided_tick(gateway, context)
        # `stop` passes the mode gate, so this tick decided and the run is broken.
        context.get("intent_board").publish("stop", Source.SYSTEM)
        gateway.tick(context)
        for _ in range(UNDECIDED_ALERT_TICKS - 1):
            _undecided_tick(gateway, context)

    assert not [item for item in caplog.records if "in a row" in item.getMessage()]


# ------------------------------------------------------------------ the FSM publishes it


class PickModeStub:
    """Stands in for `BehaviorRegistry`: keeps what it was offered, picks what it is told."""

    def __init__(self, choice: str | None) -> None:
        self.choice = choice
        self.offered: tuple[list[str], dict[str, float]] | None = None

    def pick_mode(self, modes, weights) -> str | None:
        self.offered = (list(modes), dict(weights))
        return self.choice


def test_the_fsm_publishes_the_weight_it_drew_with() -> None:
    module = BehaviorModule("behavior")
    stub = PickModeStub("patrol")
    module.registry = stub  # type: ignore[assignment]
    context = RuntimeContext()
    settings = {
        "autonomy_modes": ["idle", "patrol"],
        "autonomy_weights": {"idle": 1.0, "patrol": 2.0},
        "autonomy_interval_s": 0,
    }

    assert module._select_autonomy_mode(settings, context) == "patrol"

    published = context.get("autonomy_choice")
    assert published["mode"] == "patrol"
    # The weight the draw actually used, not a recomputation that could drift from it.
    assert stub.offered is not None
    assert published["weight"] == stub.offered[1]["patrol"]


def test_an_energy_gate_publishes_a_mode_without_a_weight() -> None:
    module = BehaviorModule("behavior")
    module.registry = PickModeStub("patrol")  # type: ignore[assignment]
    context = RuntimeContext()
    context.set("energy_level", 0.1)
    settings = {"autonomy_modes": ["idle", "patrol"], "autonomy_interval_s": 0}

    assert module._select_autonomy_mode(settings, context) == "rest"

    assert context.get("autonomy_choice") == {"mode": "rest", "weight": None}


def test_a_fallback_mode_carries_no_weight() -> None:
    """A draw that returned nothing is not a draw: the `idle` weight is not what chose it."""
    module = BehaviorModule("behavior")
    module.registry = PickModeStub(None)  # type: ignore[assignment]
    context = RuntimeContext()
    settings = {
        "autonomy_modes": ["idle"],
        "autonomy_weights": {"idle": 1.0},
        "autonomy_interval_s": 0,
    }

    assert module._select_autonomy_mode(settings, context) == "idle"

    assert context.get("autonomy_choice") == {"mode": "idle", "weight": None}
