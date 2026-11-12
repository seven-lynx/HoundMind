"""The gateway is where precedence and the interlock meet.

Both directions matter. A test suite that only checks "the safety action wins" would pass on a
gateway that never lets anything else through, and one that only checks "navigation moves the
dog" would pass on a gateway that ignores its input.
"""

from __future__ import annotations

from typing import Any

from houndmind_ai.act.gateway import MotionGatewayModule, canonical_action, legacy_action
from houndmind_ai.act.interlock import Interlock, InterlockLimits
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.kernel.actions import build_repertoire
from houndmind_ai.kernel.commands import DEFAULT_MODE, Command, CommandBus, Source
from houndmind_ai.kernel.decisions import DecisionRecord
from houndmind_ai.kernel.intents import IntentBoard


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def build(
    reading: SensorReading | None = None,
    clock: Clock | None = None,
    repertoire: dict | None = None,
    bus: CommandBus | None = None,
    **limits: Any,
) -> tuple[MotionGatewayModule, RuntimeContext]:
    clock = clock or Clock()
    interlock = Interlock(
        limits=InterlockLimits(**limits) if limits else None,
        now=clock,
        repertoire=build_repertoire(repertoire),
    )
    gateway = MotionGatewayModule(
        "motion_gateway",
        interlock=interlock,
        clock=clock,
        bus=bus,
        # The board shares the fake clock, or an intent would be stamped with wall-clock time
        # and look decades old to the gateway.
        board=IntentBoard(clock=clock),
    )
    context = RuntimeContext()
    if repertoire is not None:
        # The runtime publishes the loaded classification in `settings`, and the gateway reads it
        # at start. A test that wants a catalog action does what the runtime does.
        context.set("settings", {"behavior": {"action_classes": repertoire}})
    # `start` publishes `intent_board`, which is how a real producer finds it.
    gateway.start(context)
    if reading is not None:
        context.set("sensor_reading", reading)
    return gateway, context


def ask(context, action: str, source: Source = Source.NAVIGATION) -> None:
    """Stand in for a producer: publish an intent for this tick."""
    context.get("intent_board").publish(action, source)


def drop(context, source: Source = Source.NAVIGATION) -> None:
    context.get("intent_board").retract(source)


def reading(distance_cm: float | None, valid: bool = True) -> SensorReading:
    return SensorReading(
        distance_cm=distance_cm,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=(0.0, 0.0, 9.8),
        gyro=(0.0, 0.0, 0.0),
        timestamp=1000.0,
        distance_valid=valid,
        touch_valid=True,
        sound_valid=True,
        imu_valid=True,
    )


# ------------------------------------------------------------------ resolution


def test_no_producer_publishes_nothing() -> None:
    gateway, context = build()
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict") is None


def test_navigation_alone_wins() -> None:
    gateway, context = build()
    ask(context, "forward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"


def test_safety_overrides_navigation() -> None:
    gateway, context = build()
    ask(context, "forward")
    ask(context, "backward", Source.SYSTEM)
    gateway.tick(context)
    command = context.get("motion_command")
    assert command["action"] == "backward"
    assert command["source"] == "system"


def test_watchdog_overrides_navigation() -> None:
    gateway, context = build()
    ask(context, "forward")
    ask(context, "stop", Source.WATCHDOG)
    gateway.tick(context)
    assert context.get("motion_command")["source"] == "watchdog"


def test_a_stop_outranks_even_a_higher_source() -> None:
    """A supervisor's stop must not lose a tick to a safety retreat.

    `stop` is the one action that exists to end motion, so it is ranked above every other
    intent whatever its source. Without this, a watchdog hold would be overwritten by the
    higher-priority safety module within the same tick.
    """
    gateway, context = build()
    ask(context, "stop", Source.WATCHDOG)
    ask(context, "backward", Source.SYSTEM)
    gateway.tick(context)
    command = context.get("motion_command")
    assert command["action"] == "stop"
    assert command["source"] == "watchdog"


def test_a_routine_outranks_behaviour() -> None:
    gateway, context = build()
    ask(context, "sit", Source.BEHAVIOUR)
    ask(context, "stand", Source.ROUTINE)
    gateway.tick(context)
    assert context.get("motion_command")["source"] == "routine"


def test_navigation_outranks_a_routine() -> None:
    """A routine must never walk the dog into what the navigator is avoiding."""
    gateway, context = build()
    ask(context, "forward", Source.ROUTINE)
    ask(context, "turn_left", Source.NAVIGATION)
    gateway.tick(context)
    assert context.get("motion_command")["source"] == "navigation"


def test_a_watchdog_hold_still_outranks_a_routine() -> None:
    gateway, context = build()
    ask(context, "forward", Source.ROUTINE)
    ask(context, "stop", Source.WATCHDOG)
    gateway.tick(context)
    command = context.get("motion_command")
    assert command["action"] == "stop"
    assert command["source"] == "watchdog"


def test_behaviour_is_lowest_priority() -> None:
    gateway, context = build()
    ask(context, "sit", Source.BEHAVIOUR)
    ask(context, "forward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"


def test_same_upstream_intent_is_not_reissued_every_tick() -> None:
    """Re-issuing would bypass the motor cooldown and flood the action queue."""
    gateway, context = build()
    ask(context, "forward")
    gateway.tick(context)
    first = context.get("motion_command")
    gateway.tick(context)
    gateway.tick(context)
    assert context.get("motion_command") == first


def test_a_new_intent_is_issued() -> None:
    gateway, context = build()
    ask(context, "forward")
    gateway.tick(context)
    first_id = context.get("motion_command")["id"]
    ask(context, "turn left")
    gateway.tick(context)
    command = context.get("motion_command")
    assert command["id"] != first_id
    # pidog's spelling is what reaches the motors.
    assert command["action"] == "turn left"
    assert command["canonical_action"] == "turn_left"


def test_a_retracted_producer_stops_the_dog() -> None:
    """A producer that withdraws its intent must stop the dog on the next tick."""
    gateway, context = build()
    ask(context, "forward")
    gateway.tick(context)
    drop(context)
    gateway.tick(context)
    assert context.get("motion_command") is None


def test_an_intent_that_is_not_refreshed_expires() -> None:
    """The deadman used to protect clients only.

    An internal intent was re-stamped by the gateway on every tick, so a producer that wedged
    mid-action kept the dog walking forever (P3-1). Now silence is expiry.
    """
    clock = Clock()
    gateway, context = build(clock=clock)
    ask(context, "forward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"

    clock.advance(5.0)
    gateway.tick(context)
    assert context.get("motion_command") is None


def test_a_refreshed_intent_keeps_running() -> None:
    """Expiry must not stop a producer that is doing its job."""
    clock = Clock()
    gateway, context = build(clock=clock)
    for _ in range(5):
        ask(context, "forward")
        gateway.tick(context)
        clock.advance(0.2)
    assert context.get("motion_command")["action"] == "forward"


def test_a_displaced_intent_is_reported() -> None:
    """"The dog ignored me" is the question; a cancellation list is the answer."""
    gateway, context = build()
    ask(context, "forward")
    ask(context, "backward", Source.SYSTEM)
    gateway.tick(context)
    assert context.get("motion_command")["source"] == "system"
    cancelled = context.get("motion_cancel")
    assert [entry["action"] for entry in cancelled] == ["forward"]


def test_a_new_speed_is_a_new_command() -> None:
    """Dedupe on `(action, source)` alone dropped a genuine change of parameters."""
    gateway, context = build()
    board = context.get("intent_board")
    board.publish("forward", Source.NAVIGATION, params={"speed": 100})
    gateway.tick(context)
    first = context.get("motion_command")["id"]

    board.publish("forward", Source.NAVIGATION, params={"speed": 150})
    gateway.tick(context)
    assert context.get("motion_command")["id"] != first


# ------------------------------------------------------------------ the mode policy


def test_rest_mode_stops_autonomy() -> None:
    """`rest` used to veto clients only, while the navigator kept walking the dog (P3-3)."""
    gateway, context = build()
    context.set("runtime_mode", "rest")
    ask(context, "forward")
    gateway.tick(context)
    assert context.get("motion_command") is None


def test_rest_mode_still_lets_the_system_move_the_dog() -> None:
    """Parking the dog must not disarm the thing that parks it."""
    gateway, context = build()
    context.set("runtime_mode", "rest")
    ask(context, "lie", Source.SYSTEM)
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "lie"


def test_manual_mode_leaves_autonomy_out() -> None:
    """A hand on the wheel: a client may drive, the FSM may not."""
    gateway, context = build()
    context.set("runtime_mode", "manual")
    ask(context, "forward", Source.NAVIGATION)
    gateway.tick(context)
    assert context.get("motion_command") is None

    ask(context, "forward", Source.CLIENT)
    gateway.tick(context)
    assert context.get("motion_command")["source"] == "client"


def test_stop_is_never_refused_by_a_mode() -> None:
    """An escape hatch a mode can refuse is not an escape hatch."""
    gateway, context = build()
    context.set("runtime_mode", "rest")
    ask(context, "stop", Source.CLIENT)
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "stop"


# ------------------------------------------------------------------ the interlock


def test_obstacle_vetoes_forward_and_says_why() -> None:
    gateway, context = build(reading(8.0), emergency_stop_cm=12.0)
    ask(context, "forward")
    gateway.tick(context)
    assert context.get("motion_command") is None
    verdict = context.get("motion_verdict")
    assert verdict["accepted"] is False
    assert verdict["veto"] == "obstacle"
    assert "8.0 cm" in verdict["detail"]


def test_obstacle_blocks_forward_but_not_backward() -> None:
    gateway, context = build(reading(8.0), emergency_stop_cm=12.0)
    ask(context, "backward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "backward"


def test_an_invalid_reading_does_not_veto() -> None:
    """A dead sensor must not pin the dog in place forever."""
    gateway, context = build(reading(3.0, valid=False), emergency_stop_cm=12.0)
    ask(context, "forward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"


def test_a_high_priority_command_is_still_vetoed_by_the_interlock() -> None:
    """Precedence decides who is heard; the interlock decides whether anyone moves."""
    gateway, context = build(reading(5.0), emergency_stop_cm=12.0)
    ask(context, "forward", Source.SYSTEM)
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict")["veto"] == "obstacle"


def test_stop_is_never_vetoed() -> None:
    gateway, context = build(reading(5.0), emergency_stop_cm=12.0)
    ask(context, "stop", Source.SYSTEM)
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "stop"


def test_tilt_latches_motion_until_cleared() -> None:
    gateway, context = build()
    context.set("tilt_warning", {"pitch": 60.0, "roll": 0.0})
    ask(context, "forward")
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("tilt_latched") is True

    # Righting the dog does not clear the latch; a human decides that.
    context.set("tilt_warning", {"pitch": 0.0, "roll": 0.0})
    gateway.tick(context)
    assert context.get("motion_command") is None

    gateway.interlock.clear_tilt()
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"


def test_tilt_blocks_posture_but_not_non_motion() -> None:
    """A tilted dog must not sit or bark. It can still move its head and say so.

    Posture and expression move servos, so they answer to the tilt latch; `head` is `non_motion`
    and stays available, which is what lets the dog look at the human who is about to right it.
    """
    gateway, context = build()
    context.set("tilt_warning", {"pitch": 60.0, "roll": 0.0})
    ask(context, "sit", Source.BEHAVIOUR)
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict")["veto"] == "tilt"

    ask(context, "head", Source.BEHAVIOUR)
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "head"


def test_low_voltage_blocks_motion_and_posture_but_not_non_motion() -> None:
    gateway, context = build(min_battery_v=6.4)
    context.set("battery_voltage", 5.9)
    ask(context, "forward")
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict")["veto"] == "low_voltage"

    drop(context)
    ask(context, "sit", Source.BEHAVIOUR)
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict")["veto"] == "low_voltage"

    # The dog has to be able to complain about the battery it is running on.
    ask(context, "sound", Source.BEHAVIOUR)
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "sound"


def test_a_classified_catalog_action_is_not_refused() -> None:
    """`high five` is a catalog posture. Once the classification says so, the gateway runs it.

    The classification is read from the settings the runtime publishes, which is how an action a
    user adds to `config/actions.jsonc` starts working without a code change.
    """
    gateway, context = build(repertoire={"high five": {"class": "posture"}})
    ask(context, "high five", Source.BEHAVIOUR)
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "high five"


def test_an_unclassified_action_is_vetoed_with_a_reason() -> None:
    """The catalog is the vocabulary: a name nothing classifies does not reach a servo silently."""
    gateway, context = build()
    ask(context, "moonwalk", Source.BEHAVIOUR)
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict")["veto"] == "unknown_action"


def test_a_stale_non_motion_command_still_expires() -> None:
    """The deadman covers every class: an RGB request that sat in a queue does not run late."""
    clock = Clock()
    bus = CommandBus()
    gateway, context = build(clock=clock, bus=bus)
    command = Command("rgb", source=Source.CLIENT, params={"style": "breath"}, issued_at=clock.now)
    assert bus.submit(command) is True
    clock.advance(0.4)
    gateway.tick(context)

    verdict = bus.wait(command.id, timeout=0.1)
    assert verdict is not None
    assert verdict.accepted is False
    assert verdict.veto == "expired"
    assert context.get("motion_command") is None


# ------------------------------------------------------------------ spelling


def test_legacy_and_canonical_spellings_round_trip() -> None:
    assert canonical_action("Turn Left") == "turn_left"
    assert canonical_action("forward") == "forward"
    assert legacy_action("turn_left") == "turn left"
    assert legacy_action("wag_tail") == "wag tail"


# ------------------------------------------------------------------ decision record


def published(context) -> dict[str, Any]:
    """The record this tick published, as a client would receive it."""
    record = context.get("decision_record")
    assert isinstance(record, DecisionRecord), "every tick publishes a record"
    # The context holds the record; serializing is what `/decisions`, the socket and the JSONL
    # each do at their own boundary (and what this helper checks here).
    return record.to_dict()


def test_every_tick_publishes_a_record_even_when_nobody_asks() -> None:
    """An unexplained pet is indistinguishable from a broken one, so silence is a decision."""
    gateway, context = build()
    gateway.tick(context)

    record = published(context)
    assert set(record) == {
        "schema_version",
        "ts",
        "trace_id",
        "mode",
        "state",
        "intent",
        "source",
        "vetoes",
        "inputs",
        "confidence",
    }
    assert record["intent"] is None
    assert record["source"] is None
    assert record["vetoes"] == []
    assert record["ts"] == 1000.0
    assert record["mode"] == DEFAULT_MODE


def test_the_record_names_the_winner_and_where_it_came_from() -> None:
    gateway, context = build(reading=reading(100.0))
    ask(context, "forward", Source.NAVIGATION)
    gateway.tick(context)

    record = published(context)
    assert record["intent"] == "forward"
    assert record["source"] == "navigation"


def test_a_displaced_intent_is_recorded_with_its_reason() -> None:
    """`motion_cancel` said an intent lost; the record has to say what beat it."""
    gateway, context = build(reading=reading(100.0))
    ask(context, "sit", Source.BEHAVIOUR)
    ask(context, "forward", Source.NAVIGATION)
    gateway.tick(context)

    record = published(context)
    assert record["intent"] == "forward"
    assert len(record["vetoes"]) == 1
    refusal = record["vetoes"][0]
    assert refusal["action"] == "sit"
    assert refusal["source"] == "behaviour"
    assert refusal["reason"] == "precedence"
    assert "forward" in refusal["detail"]


def test_a_mode_refused_intent_is_recorded_instead_of_dropped() -> None:
    """The mode gate used to `continue` without a trace: the intent simply vanished."""
    gateway, context = build(reading=reading(100.0))
    context.set("runtime_mode", "rest")
    ask(context, "forward", Source.NAVIGATION)
    gateway.tick(context)

    assert context.get("motion_command") is None
    record = published(context)
    assert record["mode"] == "rest"
    assert record["intent"] is None
    assert record["vetoes"][0]["reason"] == "mode"
    assert record["vetoes"][0]["source"] == "navigation"
    assert "rest" in record["vetoes"][0]["detail"]


def test_a_refused_client_command_keeps_the_interlock_reason() -> None:
    bus = CommandBus()
    gateway, context = build(bus=bus, min_battery_v=6.4)
    context.set("battery_voltage", 5.9)
    assert bus.submit(Command("forward", source=Source.CLIENT, issued_at=1000.0)) is True
    gateway.tick(context)

    record = published(context)
    assert record["intent"] is None
    assert record["vetoes"][0]["reason"] == "low_voltage"
    assert record["vetoes"][0]["source"] == "client"


def test_the_record_carries_validity_flags_and_absent_readings_stay_absent() -> None:
    gateway, context = build()
    gateway.tick(context)
    inputs = published(context)["inputs"]
    assert inputs["distance_cm"] is None
    assert inputs["distance_valid"] is False
    assert inputs["battery_v"] is None
    assert inputs["battery_valid"] is False

    gateway, context = build(reading=reading(42.0))
    context.set("battery_voltage", 7.4)
    gateway.tick(context)
    inputs = published(context)["inputs"]
    assert inputs["distance_cm"] == 42.0
    assert inputs["distance_valid"] is True
    assert inputs["battery_v"] == 7.4
    assert inputs["battery_valid"] is True


def test_confidence_is_absent_unless_a_producer_measured_it() -> None:
    """`0.0` is a measurement; `None` is not zero, and a bool is not a confidence."""
    gateway, context = build()
    gateway.tick(context)
    assert published(context)["confidence"] is None

    context.set("navigation_decision", {"confidence": 0.0})
    gateway.tick(context)
    assert published(context)["confidence"] == 0.0

    context.set("navigation_decision", {"confidence": True})
    gateway.tick(context)
    assert published(context)["confidence"] is None


def test_the_behavior_state_is_carried_once_the_fsm_publishes_it() -> None:
    gateway, context = build()
    gateway.tick(context)
    assert published(context)["state"] is None

    context.set("behavior_state", "walking")
    gateway.tick(context)
    assert published(context)["state"] == "walking"


def test_the_record_joins_the_run_by_trace_id() -> None:
    gateway, context = build()
    context.set("trace_id", "run-1")
    gateway.tick(context)
    assert published(context)["trace_id"] == "run-1"


def test_a_deduplicated_tick_still_publishes_a_fresh_record() -> None:
    """The dedupe path returns early, so this is what keeps a single publish site honest."""
    clock = Clock()
    gateway, context = build(clock=clock, reading=reading(100.0))
    ask(context, "forward", Source.NAVIGATION)
    gateway.tick(context)
    first = published(context)["ts"]

    # Under the intent TTL, so the same intent is still asking and takes the dedupe path.
    clock.advance(0.1)
    gateway.tick(context)
    second = published(context)
    assert second["ts"] == 1000.1
    assert second["ts"] != first
    assert second["intent"] == "forward"