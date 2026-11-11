"""The client-facing snapshot says who is driving and what the watchdog is doing.

`GET /api/v1/state` and the WS `state` message are the only things a phone renders, so the fields
that answer "why did the dog do that" belong here, not in a log the client cannot read.
"""

from __future__ import annotations

from houndmind_ai.core.runtime import RuntimeContext
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