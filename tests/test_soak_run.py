"""The soak says what it saw, and counts a restart it can only hear about.

`tests/test_bench_tick.py` is the shape being copied - `_run_json` reads stdout - because the two
tools share the report idiom and nothing else. A change in one must not be needed by the other.
"""

from __future__ import annotations

import json
import logging
from typing import Any


def _run_json(capsys: Any, *args: str) -> dict:
    from tools.soak_run import main

    assert main(list(args)) == 0
    return json.loads(capsys.readouterr().out)


def _registered_names() -> list[str]:
    """The roster `main.build_registry` really holds, read independently of the report."""
    from houndmind_ai.core.config import load_config
    from houndmind_ai.hal.fake import FakeDogHAL
    from houndmind_ai.main import build_registry

    return list(build_registry(load_config(None), hal=FakeDogHAL()).names())


def test_a_run_names_every_registered_module_exactly_once(capsys) -> None:
    result = _run_json(capsys, "--ticks", "200", "--warmup", "0", "--json")

    assert result["ticks"] == 200
    assert result["registered"] == _registered_names()
    assert len(result["registered"]) == len(set(result["registered"]))
    # `api` is switched off by the port rule, so the roster and the tick list are not the same set.
    assert "api" in result["registered"]
    # `--script` defaults to the built-in timeline, so a plain run is still a scripted one.
    assert result["script"]["name"] == "default"


def test_every_ticked_module_reports_ordered_percentiles(capsys) -> None:
    result = _run_json(capsys, "--ticks", "3", "--warmup", "0", "--json")

    names = [row["module"] for row in result["modules"]]
    assert len(names) == len(set(names))
    for row in result["modules"]:
        assert row["samples"] == 3
        assert row["p50_ms"] <= row["p95_ms"] <= row["max_ms"]
    # A module that was never started cannot have a timing.
    assert set(names) <= set(result["started"])
    assert set(names) <= set(result["registered"])
    # The report has to say what produced it, and against which budget.
    assert result["python"].count(".") >= 1
    assert result["tick_hz_target"] >= 1
    assert result["budget_ms"] > 0
    assert result["tick_p50_ms"] >= 0


def test_the_control_plane_is_switched_off(capsys) -> None:
    result = _run_json(capsys, "--ticks", "2", "--warmup", "0", "--json")

    assert "api" in result["disabled"]
    assert "api" not in result["started"]
    assert "api" not in [row["module"] for row in result["modules"]]


def test_a_clean_run_reports_zero_counters(capsys) -> None:
    result = _run_json(
        capsys, "--ticks", "200", "--warmup", "0", "--script", "default", "--json"
    )

    assert result["restarts"] == 0
    assert result["restart_names"] == []
    # The built-in timeline names every reading the fake can be scripted with, and all of them land
    # inside 200 ticks: a script that was parsed but never applied would look exactly like this.
    assert result["script"]["events"] > 0
    assert result["script"]["applied"] == result["script"]["events"]
    assert set(result["invariants"]) == {
        "motion_command_without_verdict",
        "verdict_while_latched",
        "expired_intent_alive",
        "unexpected_restart",
    }
    assert all(value == 0 for value in result["invariants"].values())


def test_zero_ticks_is_refused_before_any_module_starts(capsys) -> None:
    from tools.soak_run import main

    assert main(["--ticks", "0"]) == 2
    assert "--ticks" in capsys.readouterr().err


def test_a_negative_warmup_is_refused(capsys) -> None:
    from tools.soak_run import main

    assert main(["--warmup", "-1"]) == 2
    assert "--warmup" in capsys.readouterr().err


def test_a_restart_is_counted_from_the_runtime_announcement() -> None:
    """The counter reads `core/runtime.py:253`, so prove it hears that record and no other."""
    import houndmind_ai.core.runtime as core_runtime
    from houndmind_ai.core.config import load_config
    from houndmind_ai.core.module import Module
    from houndmind_ai.core.runtime import HoundMindRuntime

    from tools.soak_run import RestartCounter

    runtime = HoundMindRuntime(load_config(None), [Module("stub")])
    counter = RestartCounter()
    logger = logging.getLogger(core_runtime.__name__)
    runtime.start()
    logger.addHandler(counter)
    try:
        # What a module would do to ask for itself back: the runtime drains the key and announces it.
        runtime.context.set("restart_modules", ["stub"])
        runtime.tick()
    finally:
        logger.removeHandler(counter)
        runtime.stop()

    assert counter.names == ["stub"]


def test_a_missing_script_is_refused_before_any_module_starts(capsys, tmp_path) -> None:
    from tools.soak_run import main

    missing = str(tmp_path / "nope.json")
    assert main(["--ticks", "5", "--script", missing]) == 2
    err = capsys.readouterr().err
    assert "nope.json" in err
    assert "cannot read script" in err


def test_a_script_with_an_unknown_field_is_refused(capsys, tmp_path) -> None:
    """A typo in a hand-typed script must fail loudly, not soak a dog that never got the event."""
    from tools.soak_run import main

    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"events": [{"tick": 1, "batteries": 7.0}]}), encoding="utf-8")
    assert main(["--ticks", "5", "--script", str(path)]) == 2
    assert "batteries" in capsys.readouterr().err


def test_a_scripted_event_reaches_the_fake_dog(capsys, tmp_path) -> None:
    """A timeline is worth its JSON only if the setters it names are the fake's own."""
    from houndmind_ai.hal.fake import FakeDogHAL

    from tools.soak_run import main

    path = tmp_path / "walk-in.json"
    path.write_text(
        json.dumps(
            {
                "name": "walk-in",
                "events": [
                    {"tick": 1, "distance": 33.5},
                    {"tick": 2, "imu": [4.0, -3.0], "touch": "front"},
                    {"tick": 3, "mode": "manual"},
                ],
            }
        ),
        encoding="utf-8",
    )
    hal = FakeDogHAL()
    assert main(["--ticks", "5", "--warmup", "0", "--script", str(path), "--json"], hal=hal) == 0
    assert json.loads(capsys.readouterr().out)["script"] == {
        "name": "walk-in",
        "events": 3,
        "applied": 4,
    }
    reading = hal.read()
    assert reading.distance_cm == 33.5
    assert (reading.pitch_deg, reading.roll_deg) == (4.0, -3.0)
    assert reading.touch == "front"


class _Context:
    """The two methods one observation needs, and nothing else."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = dict(values or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value


def test_a_command_with_no_verdict_is_counted_once_past_its_deadman() -> None:
    from tools.soak_run import InvariantCounter

    context = _Context(
        {
            "motion_command": {
                "id": "cmd-1",
                "action": "forward",
                "canonical_action": "forward",
                "ttl_ms": 300,
                "issued_at": 100.0,
            },
            "motion_verdict": {"accepted": True, "action": "forward", "status": "accepted"},
        }
    )
    counter = InvariantCounter()
    # The gateway writes both keys in one call, so the healthy pair is never counted, however old
    # the command payload has become.
    counter.observe(context, now=100.2)
    counter.observe(context, now=110.0)
    assert counter.motion_command_without_verdict == 0

    context.set("motion_verdict", None)
    counter.observe(context, now=111.0)
    counter.observe(context, now=112.0)
    assert counter.motion_command_without_verdict == 1


def test_a_verdict_after_the_latch_is_set_is_counted() -> None:
    from tools.soak_run import InvariantCounter

    context = _Context(
        {
            "motion_verdict": {"accepted": True, "action": "forward", "status": "accepted"},
            "tilt_latched": True,
        }
    )
    counter = InvariantCounter()
    # The tick that set the latch published it *after* the interlock judged, so its own verdict is
    # the veto happening, not a violation. Only a later tick can be one.
    counter.observe(context, now=1.0)
    assert counter.verdict_while_latched == 0
    counter.observe(context, now=1.1)
    assert counter.verdict_while_latched == 1

    # A refusal while latched is the interlock working; `stop` and a non-motion action are how the
    # dog ends or expresses itself while tilted, and the interlock accepts both on purpose.
    context.set("motion_verdict", {"accepted": False, "action": "forward", "status": "refused"})
    counter.observe(context, now=1.2)
    for action in ("stop", "head"):
        context.set("motion_verdict", {"accepted": True, "action": action, "status": "accepted"})
        counter.observe(context, now=1.3)
    assert counter.verdict_while_latched == 1


def test_an_intent_past_its_hold_window_is_counted_from_the_board() -> None:
    from houndmind_ai.kernel.commands import Source
    from houndmind_ai.kernel.intents import IntentBoard

    from tools.soak_run import InvariantCounter

    clock = [500.0]
    board = IntentBoard(hold_ms=1000, clock=lambda: clock[0])
    board.publish("forward", Source.NAVIGATION)
    counter = InvariantCounter()
    context = _Context({"intent_board": board})

    counter.observe(context, now=500.5)
    assert counter.expired_intent_alive == 0  # still inside the hold window
    counter.observe(context, now=502.0)  # a hold window later, and still on the board
    assert counter.expired_intent_alive == 1
    # The evidence survived: nothing asked the board a question that would have deleted the slot.
    assert board.expired == 0


def test_a_restart_the_timeline_did_not_cause_is_counted() -> None:
    from tools.soak_run import InvariantCounter, invariants

    counters = invariants(InvariantCounter(), restarts=2)

    assert counters["unexpected_restart"] == 2
    assert set(counters) == {
        "motion_command_without_verdict",
        "verdict_while_latched",
        "expired_intent_alive",
        "unexpected_restart",
    }

