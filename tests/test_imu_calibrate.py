"""`tools.imu_calibrate` — the maths, and that it saves nothing unless told to.

No hardware: `FakeDogHAL` is scripted to present the six faces, which is exactly what the tool asks
a person to do.
"""

from __future__ import annotations

import pytest

from houndmind_ai.hal.fake import FakeDogHAL
from tools.imu_calibrate import (
    NOMINAL_ACC_LSB_PER_G,
    coverage,
    magnitude_g,
    main,
    solve,
    to_raw,
)

BIAS = (500.0, -300.0, 200.0)
SCALE = (16000.0, 15800.0, 16200.0)


def _face(axis: int, sign: float) -> tuple[float, float, float]:
    """The g reading for a dog resting on one face, given this sensor's bias and scale."""
    acc = [BIAS[index] / NOMINAL_ACC_LSB_PER_G for index in range(3)]
    acc[axis] = (BIAS[axis] + sign * SCALE[axis]) / NOMINAL_ACC_LSB_PER_G
    return (acc[0], acc[1], acc[2])


FACES = [_face(0, 1.0), _face(0, -1.0), _face(1, 1.0), _face(1, -1.0), _face(2, 1.0), _face(2, -1.0)]


def _raw_poses() -> list[list[float]]:
    return [to_raw(face, [NOMINAL_ACC_LSB_PER_G] * 3) for face in FACES]


def test_solve_recovers_the_bias_and_scale_it_was_given() -> None:
    solution = solve(_raw_poses())

    assert solution["acc_bias"] == pytest.approx(list(BIAS), abs=0.01)
    assert solution["acc_scale"] == pytest.approx(list(SCALE), abs=0.01)


def test_coverage_requires_every_axis_to_see_gravity() -> None:
    covered, problems = coverage(_raw_poses())
    assert covered is True
    assert problems == []

    half, half_problems = coverage(_raw_poses()[:3])  # +X, -X, +Y only
    assert half is False
    assert any("Z" in problem for problem in half_problems)


def test_coverage_of_nothing_is_not_coverage() -> None:
    covered, problems = coverage([])
    assert covered is False
    assert problems == ["no samples"]


def test_an_axis_that_never_points_the_other_way_is_refused() -> None:
    """The dog's first saved run: X never up, Y never down - and the old span check passed it.

    A run like that produces bias values equal to whatever constant was shifting the data, not the
    sensor's bias, so it has to be refused before anything is written.
    """
    shift = (500.0, 16183.0, 0.0)
    poses = []
    for axis, sign in ((0, -1.0), (0, -1.0), (1, 1.0), (1, 1.0), (2, 1.0), (2, -1.0)):
        acc = [0.0, 0.0, 0.0]
        acc[axis] = sign
        poses.append([acc[i] * NOMINAL_ACC_LSB_PER_G + shift[i] for i in range(3)])

    covered, problems = coverage(poses)

    assert covered is False
    assert any("X never pointed up" in problem for problem in problems)
    assert any("Y never pointed down" in problem for problem in problems)
    assert not any(problem.startswith("Z") for problem in problems)


def test_to_raw_undoes_the_hal_conversion() -> None:
    raw = to_raw((1.0, -1.0, 0.5), (16384.0, 16000.0, 8192.0))
    assert raw == pytest.approx([16384.0, -16000.0, 4096.0])


def test_magnitude_g_is_one_for_gravity() -> None:
    assert magnitude_g((0.0, 0.0, 1.0)) == pytest.approx(1.0)
    assert magnitude_g((-1.489, -0.143, 0.087)) == pytest.approx(1.498, abs=0.001)


def _scripted(hal: FakeDogHAL, faces: list[tuple[float, float, float]]):
    """Answer each prompt by putting the dog on the next face before it is sampled."""
    state = {"index": 0}

    def prompt(_message: str) -> str:
        face = faces[min(state["index"], len(faces) - 1)]
        state["index"] += 1
        hal.set_acc(face)
        hal.set_gyro((1.0, -2.0, 0.5))
        return ""

    return prompt


def _dry(hal: FakeDogHAL, faces, *extra: str) -> int:
    return main(
        ["--seconds", "0", "--samples", "1", *extra],
        hal=hal,
        prompt=_scripted(hal, faces),
    )


def test_a_dry_run_measures_and_saves_nothing(capsys) -> None:
    hal = FakeDogHAL()

    assert _dry(hal, FACES) == 0

    out = capsys.readouterr().out
    assert "dry run: nothing saved" in out
    assert hal.imu_calibrations_saved == []
    assert "16000" in out or "16000" in out.replace(" ", "")


def test_apply_saves_the_measured_bias_and_scale(capsys) -> None:
    hal = FakeDogHAL()

    assert _dry(hal, FACES, "--apply") == 0

    assert len(hal.imu_calibrations_saved) == 1
    saved = hal.imu_calibrations_saved[0]
    assert saved["acc_bias"] == pytest.approx(list(BIAS), abs=0.01)
    assert saved["acc_scale"] == pytest.approx(list(SCALE), abs=0.01)
    # Gyro bias only: a rate scale needs a known rotation, which a hand cannot supply.
    assert saved["gyro_scale"] is None
    assert saved["gyro_bias"] == pytest.approx([16.4, -32.8, 8.2], abs=0.1)
    assert "saved" in capsys.readouterr().out


def test_the_same_pose_six_times_is_refused(capsys) -> None:
    hal = FakeDogHAL()

    assert _dry(hal, [FACES[0]] * 6, "--apply") == 1

    out = capsys.readouterr().out
    assert "coverage too small" in out
    assert hal.imu_calibrations_saved == []


def test_no_imu_reading_stops_the_run(capsys) -> None:
    hal = FakeDogHAL()  # never told an acc or a gyro

    assert main(["--seconds", "0", "--samples", "1"], hal=hal, prompt=lambda _m: "") == 1

    assert "no IMU reading" in capsys.readouterr().out
    assert hal.imu_calibrations_saved == []


def test_apply_clears_the_old_calibration_before_measuring(capsys) -> None:
    """Measure the sensor, not what was already subtracted from it."""
    hal = FakeDogHAL()
    hal.set_imu_calibration_store({"acc_bias": [-20448.0, 16183.0, -605.0]})

    assert _dry(hal, FACES, "--apply") == 0

    assert hal.imu_calibration_resets == 1
    assert "cleared the stored calibration" in capsys.readouterr().out


def test_a_dry_run_leaves_the_stored_calibration_alone() -> None:
    hal = FakeDogHAL()
    hal.set_imu_calibration_store({"acc_bias": [-20448.0, 16183.0, -605.0]})

    assert _dry(hal, FACES) == 0

    assert hal.imu_calibration_resets == 0


def test_a_dry_run_says_when_the_vendor_startup_offset_is_in_force(capsys) -> None:
    """`Pidog` shifts every sample by an offset it derives at boot assuming a level dog."""
    hal = FakeDogHAL()
    hal.set_imu_calibration_store({"acc_offset": [-20448.0, 16183.0, -605.0]})

    _dry(hal, FACES)

    assert "startup offset is in force" in capsys.readouterr().out


def test_reset_asks_the_hal_to_clear_the_calibration(capsys) -> None:
    hal = FakeDogHAL()
    hal.set_imu_calibration_store({"acc_bias": [1.0, 2.0, 3.0]})

    assert main(["--reset"], hal=hal) == 0

    assert hal.imu_calibration_resets == 1
    assert hal.read_imu_calibration() is None
    assert "cleared" in capsys.readouterr().out
