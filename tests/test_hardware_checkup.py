"""The checkup drives a `DogHAL`, so the fake can exercise all of it - including the motion path.

#11: `src/tools/hardware_checkup.py` used to construct its own `Pidog()`, which meant no test
could reach it and the sensor conditioning the HAL applies was skipped. Every case here is
`FakeDogHAL`-only: nothing moves, nothing sleeps longer than `--pause 0`.
"""

from __future__ import annotations

from houndmind_ai.hal.fake import FakeDogHAL
from tools.hardware_checkup import MOTION_STEPS, main


def _make_healthy(hal: FakeDogHAL) -> FakeDogHAL:
    """One wired-up dog, whether the HAL is the plain fake or a subclass of it."""
    hal.set_distance(41.7)
    hal.set_touch("N")
    hal.set_sound(None, valid=True)
    hal.set_acc((412.0, -180.0, 16310.0))
    hal.set_gyro((18.0, -7.0, 11.0))
    return hal


def _healthy() -> FakeDogHAL:
    return _make_healthy(FakeDogHAL())


class _FailingStepHAL(FakeDogHAL):
    """One motion step fails the way a servo bus can: the rest of the run must still happen."""

    def action(self, name, params):  # type: ignore[override]
        if name == "turn_left":
            raise RuntimeError("servo bus timeout")
        super().action(name, params)


def test_skip_motion_reads_the_snapshot_and_commands_nothing(capsys):
    hal = _healthy()

    assert main(["--skip-motion", "--pause", "0"], hal=hal) == 0

    out = capsys.readouterr().out
    assert "[checkup] Reading sensors..." in out
    assert "[checkup] distance_cm: 41.7" in out
    assert "[checkup] touch: N" in out
    assert "[checkup] sound: detected=False dir=None" in out
    assert "[checkup] acc: (412.0, -180.0, 16310.0)" in out
    assert "[checkup] gyro: (18.0, -7.0, 11.0)" in out
    assert "[checkup] valid: distance=True touch=True sound=True imu=True" in out
    assert "[checkup] sensors: all answered" in out
    assert "[checkup] Motion skipped." in out
    # The whole point of the flag: no action, and no close of a HAL this tool did not open.
    assert hal.calls == []
    assert hal.closed is False


def test_a_failed_reading_prints_none_and_says_so(capsys):
    """`None` is "no reading", and a non-zero exit is what a script can act on (#109)."""
    hal = FakeDogHAL()

    assert main(["--skip-motion", "--pause", "0"], hal=hal) == 1

    out = capsys.readouterr().out
    assert "[checkup] distance_cm: None" in out
    assert "[checkup] touch: None" in out
    assert "[checkup] sound: detected=None dir=None" in out
    assert "[checkup] acc: None" in out
    assert "[checkup] gyro: None" in out
    assert "[checkup] valid: distance=False touch=False sound=False imu=False" in out
    assert "[checkup] no reading from: distance, touch, sound, imu" in out


def test_one_dead_sensor_is_a_failed_checkup(capsys):
    """The failure the exit code exists for: a healthy dog with one sensor that never answered."""
    hal = _healthy()
    hal.set_acc(None)

    assert main(["--skip-motion", "--pause", "0"], hal=hal) == 1

    out = capsys.readouterr().out
    assert "[checkup] no reading from: imu" in out
    # The healthy sensors keep their values: one dead sensor does not blank the report.
    assert "[checkup] distance_cm: 41.7" in out


def test_a_dead_sensor_does_not_stop_the_motion_run(capsys):
    """`--skip-motion` is the only gate on motion; a bad reading must not silently cancel it."""
    hal = _healthy()
    hal.set_distance(None)

    assert main(["--pause", "0"], hal=hal) == 1

    assert "[checkup] Running minimal motion..." in capsys.readouterr().out
    assert [name for name, _ in hal.calls] == [name for name, _ in MOTION_STEPS]


def test_a_quiet_room_is_valid_without_a_direction(capsys):
    """The normal state on a healthy dog: the sensor answered, nothing was heard."""
    hal = _healthy()

    assert main(["--skip-motion", "--pause", "0"], hal=hal) == 0

    out = capsys.readouterr().out
    assert "[checkup] sound: detected=False dir=None" in out
    assert "sound=True" in out


def test_motion_runs_the_documented_sequence_through_the_hal(capsys):
    hal = _healthy()

    assert main(["--pause", "0"], hal=hal) == 0

    out = capsys.readouterr().out
    assert "[checkup] Running minimal motion..." in out
    assert "[checkup] Done." in out
    assert [name for name, _ in hal.calls] == [name for name, _ in MOTION_STEPS]
    assert hal.calls[0] == ("stand", {"speed": 180, "steps": 1, "wait": True})
    head_yaws = [params["yaw"] for name, params in hal.calls if name == "head"]
    assert head_yaws == [-30.0, 30.0, 0.0]
    assert hal.closed is False


def test_one_failed_step_is_reported_and_the_rest_still_run(capsys):
    hal = _make_healthy(_FailingStepHAL())

    assert main(["--pause", "0"], hal=hal) == 0

    captured = capsys.readouterr()
    assert "[checkup] step turn_left failed: servo bus timeout" in captured.err
    assert [name for name, _ in hal.calls] == [
        "stand",
        "turn_right",
        "head",
        "head",
        "head",
    ]
