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
    result = _run_json(capsys, "--ticks", "200", "--warmup", "0", "--json")

    assert result["restarts"] == 0
    assert result["restart_names"] == []
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
