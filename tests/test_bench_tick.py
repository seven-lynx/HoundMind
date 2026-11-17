"""The bench reports what it measured, and never pretends a fake is the dog."""

from __future__ import annotations

import json
from typing import Any


def _run_json(capsys: Any, *args: str) -> dict:
    from tools.bench_tick import main

    assert main(list(args)) == 0
    return json.loads(capsys.readouterr().out)


def test_every_started_module_appears_once_with_ordered_percentiles(capsys) -> None:
    result = _run_json(capsys, "--ticks", "3", "--warmup", "0", "--json")

    assert result["ticks"] == 3
    names = [row["module"] for row in result["modules"]]
    assert len(names) == len(set(names))
    for row in result["modules"]:
        assert row["samples"] == 3
        assert row["p50_ms"] <= row["p95_ms"] <= row["max_ms"]
    # A module that was never started cannot have a timing.
    assert set(names) <= set(result["started"])


def test_a_disabled_module_is_not_measured(capsys) -> None:
    result = _run_json(
        capsys, "--ticks", "2", "--warmup", "0", "--json", "--disable", "mapping"
    )

    assert "mapping" in result["disabled"]
    assert "mapping" not in [row["module"] for row in result["modules"]]
    assert "mapping" not in result["started"]


def test_the_control_plane_is_switched_off(capsys) -> None:
    result = _run_json(capsys, "--ticks", "2", "--warmup", "0", "--json")

    assert "api" in result["disabled"]
    assert "api" not in result["started"]


def test_the_report_carries_the_interpreter_and_the_budget(capsys) -> None:
    result = _run_json(capsys, "--ticks", "2", "--warmup", "0", "--json")

    assert result["python"].count(".") >= 1
    assert result["tick_hz_target"] >= 1
    assert result["budget_ms"] > 0
    assert result["tick_p50_ms"] >= 0


def test_zero_ticks_is_refused_before_any_module_starts(capsys) -> None:
    from tools.bench_tick import main

    assert main(["--ticks", "0"]) == 2
    assert "--ticks" in capsys.readouterr().err
