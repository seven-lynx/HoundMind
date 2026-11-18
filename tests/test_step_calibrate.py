"""`tools.step_calibrate` measures a stride it can prove, and refuses to drive without clearance.

`step_cm` shipped as 25 cm for a dog whose body is about 25 cm, with the vendor reference itself
listing the real travel of one gait cycle as unknown (#285). These tests hold the measurement, the
gates that stop it, and the odometry resolution that consumes the result.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from houndmind_ai.hal.iface import SensorSnapshot
from houndmind_ai.navigation.odometry import OdometryModule, resolve_step_cm
from tools.step_calibrate import (
    MAX_DRIFT_DEG,
    _WallDogHAL,
    main,
    run_calibration,
    snippet,
)


class _Context:
    def __init__(self, values: dict | None = None) -> None:
        self.values = dict(values or {})

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def set(self, key: str, value) -> None:
        self.values[key] = value


class _Clock:
    """One second per read, so drift integration gets a real dt without sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def _no_sleep(_seconds: float) -> None:
    return None


def _run(hal, **kwargs):
    options = {"confirmed": True, "surface": "hardwood", "sleep": _no_sleep, "pause_s": 0.0}
    options.update(kwargs)
    return run_calibration(hal, **options)


def test_the_walk_recovers_the_stride_it_was_given() -> None:
    hal = _WallDogHAL(distance_cm=150.0, step_cm=8.0)

    report = _run(hal, commands=5)

    assert report.accepted
    assert report.per_cycle_cm == pytest.approx(8.0, abs=0.05)
    assert report.residual_cm == pytest.approx(0.0, abs=0.05)
    assert len(report.cycles) == 5
    assert report.verdict == "measured"
    assert report.drift_deg == pytest.approx(0.0, abs=0.01)
    # One issued command per cycle: the stride is per *command*, not per second of walking.
    assert [name for name, _ in hal.calls] == ["forward"] * 5


def test_without_clearance_nothing_moves() -> None:
    hal = _WallDogHAL()

    report = _run(hal, confirmed=False)

    assert report.refused is not None and "confirm-clearance" in report.refused
    assert hal.calls == []
    assert report.cycles == []


def test_main_refuses_without_the_flag(capsys) -> None:
    assert main([]) == 2

    captured = capsys.readouterr()
    assert "Refusing" in captured.err
    assert "--confirm-clearance" in captured.err


def test_the_interlock_still_vetoes_below_its_own_floor() -> None:
    """Two floors, on purpose: the tool's walk floor fires first, the interlock's veto still holds.

    This lowers `min_volts` out of the way so the 6.4 V compiled floor is the one that answers -
    which is what a caller would get if they used `--min-volts` to override the tool's gate.
    """
    hal = _WallDogHAL()
    hal.set_battery(6.0)  # below the compiled 6.4 V floor

    report = _run(hal, min_volts=6.0)

    assert report.veto == "low_voltage"
    assert report.cycles == []
    assert hal.calls == []
    assert "low_voltage" in report.verdict
    assert not report.accepted


def test_the_walk_stops_before_the_wall() -> None:
    hal = _WallDogHAL(distance_cm=60.0, step_cm=8.0)

    report = _run(hal, commands=5, stop_at_cm=45.0)

    # 60 -> 52 is fine, 52 -> 44 leaves less than 45 cm, so the third step never happens.
    assert len(report.cycles) == 2
    assert any("stop_at" in reason for reason in report.stopped)
    assert len(hal.calls) == 2


def test_a_veering_run_is_rejected_rather_than_averaged_in() -> None:
    clock = _Clock()
    hal = _WallDogHAL(distance_cm=150.0, step_cm=8.0, now=clock)
    hal.set_gyro((0.0, 0.0, 20.0))  # 20 deg/s for a second between samples

    report = _run(hal, commands=5)

    assert report.drift_measured
    assert abs(report.drift_deg or 0.0) > MAX_DRIFT_DEG
    assert not report.accepted
    assert "veered" in report.verdict
    assert snippet(report).startswith("// nothing to save")


class _FlakyEcho(_WallDogHAL):
    """Every third read misses, which is what carpet does to an ultrasonic."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.reads = 0

    def read(self) -> SensorSnapshot:
        self.reads += 1
        snapshot = super().read()
        if self.reads % 3 == 0:
            return dataclasses.replace(snapshot, distance_cm=None, distance_valid=False)
        return snapshot


def test_a_missed_echo_is_retried_not_counted_as_distance() -> None:
    hal = _FlakyEcho(distance_cm=150.0, step_cm=8.0)

    report = _run(hal, commands=5)

    assert report.dropped_echoes > 0
    assert report.accepted
    assert report.per_cycle_cm == pytest.approx(8.0, abs=0.05)


def test_head_zero_only_moves_the_head() -> None:
    hal = _WallDogHAL(distance_cm=88.0)

    report = _run(hal, measure="head-zero")

    assert [name for name, _ in hal.calls] == ["head"]
    assert report.distance_cm == pytest.approx(88.0)
    assert report.cycles == []


def test_an_unknown_measure_is_refused() -> None:
    hal = _WallDogHAL()

    report = _run(hal, measure="sideways")

    assert report.refused is not None
    assert hal.calls == []


class _SaggingPack(_WallDogHAL):
    """A pack that reads fine standing still and collapses once eight servos ask for current."""

    def __init__(self, sag_v: float = 7.2, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sag_v = sag_v

    def action(self, name: str, params: dict[str, Any]) -> None:
        super().action(name, params)
        if name in ("forward", "backward"):
            self.set_battery(self._sag_v)


def test_a_pack_below_the_walk_floor_is_refused_before_it_moves() -> None:
    # The bench dog read 7.78-7.85 V idle and rebooted the Pi mid-gait twice (#292).
    hal = _WallDogHAL()
    hal.set_battery(7.85)

    report = _run(hal)

    assert report.refused is not None and "walk floor" in report.refused
    assert "#292" in report.refused
    assert hal.calls == []
    assert report.cycles == []


def test_the_walk_floor_can_be_lowered_on_purpose() -> None:
    hal = _WallDogHAL()
    hal.set_battery(7.85)

    report = _run(hal, min_volts=7.0)

    assert report.refused is None
    assert len(report.cycles) == 5


def test_a_pack_that_sags_mid_walk_ends_the_run() -> None:
    hal = _SaggingPack(distance_cm=150.0, step_cm=8.0)

    report = _run(hal, commands=5)

    assert report.veto == "pack_sag"
    assert "below" in (report.veto_detail or "")
    # One cycle completed; the second read the sagging pack and stopped before another step.
    assert len(report.cycles) == 1
    assert len(hal.calls) == 1
    assert not report.accepted


def test_the_snippet_is_a_config_block_and_a_rejected_run_has_none() -> None:
    report = _run(_WallDogHAL(distance_cm=150.0, step_cm=9.5), commands=4)

    assert report.accepted
    document = json.loads("{" + snippet(report) + "}")
    assert document["odometry"]["surface"] == "hardwood"
    assert document["odometry"]["surface_step_cm"]["hardwood"] == pytest.approx(9.5)


def test_json_mode_reports_the_measurement(capsys) -> None:
    assert main(["--fake", "--commands", "5", "--surface", "carpet", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["verdict"] == "measured"
    assert payload["report"]["surface"] == "carpet"
    assert payload["report"]["cm_per_cycle"] == pytest.approx(8.0, abs=0.05)
    assert '"carpet"' in payload["snippet"]


# ---------------------------------------------------------------- odometry (L3.2)


def test_a_measured_surface_wins_over_the_assumed_constant() -> None:
    scale = resolve_step_cm(
        {"step_cm": 25.0, "surface": "carpet", "surface_step_cm": {"carpet": 9.5}}
    )

    assert scale.cm == pytest.approx(9.5)
    assert scale.source == "measured:carpet"
    assert scale.surface == "carpet"


def test_an_unlisted_surface_falls_back_and_says_assumed() -> None:
    scale = resolve_step_cm(
        {"step_cm": 25.0, "surface": "tile", "surface_step_cm": {"carpet": 9.5}}
    )

    assert scale.cm == pytest.approx(25.0)
    assert scale.source == "assumed"
    assert scale.surface == "tile"


def test_a_junk_entry_in_the_table_is_not_a_measurement() -> None:
    scale = resolve_step_cm(
        {"step_cm": 25.0, "surface": "rug", "surface_step_cm": {"rug": 0}}
    )

    assert scale.cm == pytest.approx(25.0)
    assert scale.source == "assumed"


def test_no_surface_configured_uses_the_assumed_value() -> None:
    scale = resolve_step_cm({"step_cm": 25.0, "surface": "", "surface_step_cm": {}})

    assert scale.cm == pytest.approx(25.0)
    assert scale.source == "assumed"
    assert scale.surface is None


def test_the_published_pose_names_the_constant_it_used() -> None:
    context = _Context(
        {
            "settings": {
                "odometry": {
                    "step_cm": 25.0,
                    "surface": "hardwood",
                    "surface_step_cm": {"hardwood": 8.0},
                }
            },
            "current_heading": 0.0,
        }
    )

    OdometryModule("odometry").tick(context)

    payload = context.get("odometry")
    assert payload["step_cm"] == pytest.approx(8.0)
    assert payload["step_cm_source"] == "measured:hardwood"
    assert payload["surface"] == "hardwood"



def _report(
    cycles: list[float], *, surface: str = "hardwood", veto: str | None = None
):
    """A run report with one cycle per distance, in the shape `run_calibration` produces."""
    from tools.step_calibrate import Cycle, RunReport

    report = RunReport(surface=surface, measure="forward", speed=100, stop_at_cm=45.0)
    for index, covered in enumerate(cycles):
        before = 150.0 - index * covered
        report.cycles.append(Cycle(index=index, before_cm=before, after_cm=before - covered))
    report.veto = veto
    return report


def test_apply_takes_the_median_of_enough_consistent_cycles() -> None:
    from tools.step_calibrate import apply_value

    value, why = apply_value(_report([8.0, 8.1, 7.9, 8.0, 8.05]), current_cm=8.0)

    assert value == pytest.approx(8.0)
    assert "5 cycles" in why


def test_apply_refuses_fewer_samples_than_it_needs() -> None:
    """One cycle is an echo; --apply asks for more evidence than `measured` does (#300)."""
    from tools.step_calibrate import apply_value

    value, why = apply_value(_report([8.0, 8.0, 8.0, 8.0]), current_cm=8.0)

    assert value is None
    assert "needed for --apply" in why


def test_apply_refuses_cycles_that_disagree() -> None:
    from tools.step_calibrate import apply_value

    value, why = apply_value(_report([4.0, 12.0, 6.0, 9.0, 11.0]), current_cm=8.0)

    assert value is None
    assert "disagree" in why


def test_apply_clamps_a_jump_so_one_run_cannot_rescale_every_anchor() -> None:
    """25 -> 8 clamps to 20: the constant moves by at most 20 % per apply, by design."""
    from tools.step_calibrate import apply_value

    value, why = apply_value(_report([8.0, 8.0, 8.0, 8.0, 8.0]), current_cm=25.0)

    assert value == pytest.approx(20.0)
    assert "clamped from 8.00" in why


def test_apply_refuses_a_run_the_interlock_stopped() -> None:
    from tools.step_calibrate import apply_value

    value, why = apply_value(_report([8.0] * 5, veto="low_voltage"), current_cm=8.0)

    assert value is None
    assert "low_voltage" in why

