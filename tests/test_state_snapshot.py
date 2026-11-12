"""The client-facing snapshot says who is driving and what the watchdog is doing.

`GET /api/v1/state` and the WS `state` message are the only things a phone renders, so the fields
that answer "why did the dog do that" belong here, not in a log the client cannot read.
"""

from __future__ import annotations

from houndmind_ai.behavior.routine_runner import RoutineRun
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.decisions import DecisionRecord
from houndmind_ai.services.state import build_state


def test_actuators_name_the_source_that_won_the_tick() -> None:
    context = RuntimeContext()
    context.set(
        "motion_command",
        {
            "action": "forward",
            "canonical_action": "forward",
            "source": "watchdog",
            "issued_at": 10.0,
        },
    )
    context.set("motion_verdict", {"accepted": True})

    state = build_state(context, now=11.0)

    assert state["actuators"]["last_command"] == "forward"
    assert state["actuators"]["source"] == "watchdog"
    assert state["actuators"]["since_s"] == 1.0


def test_a_veto_is_reported_with_its_reason() -> None:
    context = RuntimeContext()
    context.set("motion_verdict", {"accepted": False, "veto": "obstacle", "detail": "8.0 cm"})

    actuators = build_state(context, now=0.0)["actuators"]

    assert actuators["vetoed"] is True
    assert actuators["veto"] == "obstacle"


def test_displaced_counts_the_intents_that_lost() -> None:
    context = RuntimeContext()
    context.set("motion_cancel", [{"action": "forward"}, {"action": "sit"}])

    assert build_state(context, now=0.0)["actuators"]["displaced"] == 2


def test_the_supervisor_block_is_quiet_by_default() -> None:
    supervisor = build_state(RuntimeContext(), now=0.0)["supervisor"]

    assert supervisor == {"holding": False, "reason": None, "restarts": [], "failed": []}


def test_the_supervisor_block_reports_a_hold_and_a_restart() -> None:
    context = RuntimeContext()
    context.set("watchdog_hold", {"reason": "sensor stale", "timestamp": 5.0})
    context.set("watchdog_status", {"restart": ["scanning"], "failed": ["api"]})

    supervisor = build_state(context, now=6.0)["supervisor"]

    assert supervisor["holding"] is True
    assert supervisor["reason"] == "sensor stale"
    assert supervisor["restarts"] == ["scanning"]
    assert supervisor["failed"] == ["api"]


def test_the_snapshot_carries_the_decision_record() -> None:
    """One record, four surfaces: this is the one a client renders without a socket."""
    context = RuntimeContext()
    context.set(
        "decision_record",
        DecisionRecord(ts=7.0, mode="patrol", intent="forward", source="navigation"),
    )

    decision = build_state(context, now=8.0)["decision"]

    assert decision["ts"] == 7.0
    assert decision["intent"] == "forward"
    assert decision["confidence"] is None, "unmeasured is null, never 0.0"


def test_no_decision_yet_is_null_not_an_empty_record() -> None:
    """Before the first tick the dog has decided nothing; an empty object would claim it had."""
    assert build_state(RuntimeContext(), now=0.0)["decision"] is None


def test_the_snapshot_carries_the_running_routine() -> None:
    """One object, three surfaces: `GET /routines`' `current`, this block, and the `routine` event.

    A client that was told `202` by `POST /routines/{id}/run` needs to see whether the run actually
    started and how far it got, without a second route in the loop.
    """
    context = RuntimeContext()
    context.set(
        "routine_run",
        RoutineRun(
            routine_id="morning",
            name="Morning greeting",
            total=3,
            index=1,
            action="sit",
            started_at=5.0,
        ),
    )

    routines = build_state(context, now=6.0)["routines"]

    assert routines["id"] == "morning"
    assert routines["name"] == "Morning greeting"
    assert routines["index"] == 1
    assert routines["total"] == 3
    assert routines["state"] == "running"
    assert routines["action"] == "sit"


def test_no_routine_yet_is_null_not_an_empty_run() -> None:
    """`null` is "nothing has been played"; an empty object would be a run with no steps."""
    assert build_state(RuntimeContext(), now=0.0)["routines"] is None