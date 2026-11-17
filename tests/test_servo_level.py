"""`tools.servo_level` — the solve, the refusals, and that only `--apply` moves the dog.

No hardware. `TiltingFake` models the one thing the tool needs to be true: a nudged joint tips the
body by a known amount per degree, and a trim shifts it back. That makes the closed loop testable
without a dog.
"""

from __future__ import annotations

import pytest

from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import LEG_SERVO_NAMES, SERVO_NAMES
from tools.servo_level import (
    main,
    next_offsets,
    prerequisite_problem,
    read_tilt,
    trim_solution,
)

#: d(roll), d(pitch) per degree of joint motion. Shoulders roll, knees pitch, as on the real dog.
GAINS = {
    "lf_shoulder": (0.50, 0.0),
    "rf_shoulder": (-0.50, 0.0),
    "lh_shoulder": (0.30, 0.0),
    "rh_shoulder": (-0.30, 0.0),
    "lf_leg": (0.0, 0.40),
    "rf_leg": (0.0, -0.40),
    "lh_leg": (0.0, 0.20),
    "rh_leg": (0.0, -0.20),
}

CALIBRATED = {"acc_bias": [0.0, 0.0, 0.0], "acc_scale": [16384.0, 16384.0, 16384.0]}


class TiltingFake(FakeDogHAL):
    """A dog whose tilt answers to nudges, with a trim baseline already stored."""

    def __init__(self, roll: float = 4.0, pitch: float = -3.0) -> None:
        super().__init__()
        self.tilt = [roll, pitch]
        self._offsets = {name: 0.0 for name in SERVO_NAMES}
        self.set_imu_calibration_store(dict(CALIBRATED))
        self._publish()

    def _publish(self) -> None:
        self.set_imu(pitch_deg=self.tilt[1], roll_deg=self.tilt[0])
        self.set_acc((0.0, 0.0, 1.0))
        self.set_gyro((0.0, 0.0, 0.0))

    def nudge_joint(self, name: str, degrees: float) -> None:
        super().nudge_joint(name, degrees)
        gain = GAINS.get(name, (0.0, 0.0))
        self.tilt[0] += gain[0] * degrees
        self.tilt[1] += gain[1] * degrees
        self._publish()

    def apply_offsets(self, offsets, pose=None) -> None:
        previous = dict(self._offsets)
        super().apply_offsets(offsets, pose)
        for name in (offsets or {}):
            gain = GAINS.get(name)
            if gain is None or name not in previous:
                continue
            delta = self._offsets.get(name, previous[name]) - previous[name]
            self.tilt[0] += gain[0] * delta
            self.tilt[1] += gain[1] * delta
        self._publish()


def _run(hal, *args: str) -> int:
    return main(
        [*args, "--probe-deg", "2", "--settle", "0", "--samples", "2"],
        hal=hal,
        sleep=lambda _seconds: None,
    )


# ---- the maths -------------------------------------------------------------------------------


def test_trim_solution_cancels_the_error_it_was_given() -> None:
    jacobian = [GAINS[name] for name in LEG_SERVO_NAMES]
    error = (4.0, -3.0)

    trim = trim_solution(jacobian, error)

    roll_left = error[0] + sum(c[0] * t for c, t in zip(jacobian, trim, strict=True))
    pitch_left = error[1] + sum(c[1] * t for c, t in zip(jacobian, trim, strict=True))
    # Damping leaves a residual by construction; it has to stay far below the 1 deg target.
    assert roll_left == pytest.approx(0.0, abs=0.05)
    assert pitch_left == pytest.approx(0.0, abs=0.05)


def test_trim_solution_spreads_the_correction_across_the_similar_joints() -> None:
    """Left and right shoulders are mirror images: neither should carry the whole correction."""
    jacobian = [GAINS[name] for name in LEG_SERVO_NAMES]

    trim = trim_solution(jacobian, (4.0, 0.0))

    left = trim[LEG_SERVO_NAMES.index("lf_shoulder")]
    right = trim[LEG_SERVO_NAMES.index("rf_shoulder")]
    assert left == pytest.approx(-right)
    assert all(abs(value) < 20.0 for value in trim)


def test_a_joint_that_moved_nothing_does_not_produce_a_number() -> None:
    assert trim_solution([(0.0, 0.0)] * 8, (3.0, 3.0)) == [0.0] * 8


def test_next_offsets_adds_the_solve_and_clamps() -> None:
    current = {name: 18.0 for name in LEG_SERVO_NAMES}
    trim = [5.0] + [0.0] * 7

    updated = next_offsets(current, trim)

    assert updated[LEG_SERVO_NAMES[0]] == 20.0  # clamped, not 23
    assert updated[LEG_SERVO_NAMES[1]] == 18.0


# ---- the prerequisites -----------------------------------------------------------------------


def test_an_uncalibrated_imu_is_refused_before_anything_moves() -> None:
    hal = FakeDogHAL()

    assert _run(hal) == 1
    assert hal.nudges == []
    assert "imu_calibrate" in str(prerequisite_problem(hal))


def test_an_acc_that_does_not_read_one_g_is_refused(capsys) -> None:
    hal = FakeDogHAL()
    hal.set_imu_calibration_store(dict(CALIBRATED))
    hal.set_acc((1.5, 0.0, 0.0))
    hal.set_gyro((0.0, 0.0, 0.0))

    assert _run(hal) == 1
    assert "instead of 1.00 g" in capsys.readouterr().out


def test_no_stored_trim_means_nothing_to_merge_into(capsys) -> None:
    hal = FakeDogHAL()
    hal.set_imu_calibration_store(dict(CALIBRATED))
    hal.set_acc((0.0, 0.0, 1.0))
    hal.set_gyro((0.0, 0.0, 0.0))

    assert _run(hal) == 1
    assert "calibrate_servos" in capsys.readouterr().out


# ---- the loop --------------------------------------------------------------------------------


def test_read_tilt_averages_and_reports_none_without_an_imu() -> None:
    hal = FakeDogHAL()
    hal.set_imu(pitch_deg=2.0, roll_deg=-1.0)

    assert read_tilt(hal, samples=3, sleep=lambda _s: None) == pytest.approx((-1.0, 2.0))

    blank = FakeDogHAL()
    assert read_tilt(blank, samples=2, sleep=lambda _s: None) is None


def test_a_dry_run_measures_nothing_and_moves_nothing(capsys) -> None:
    hal = TiltingFake()

    assert _run(hal) == 0

    out = capsys.readouterr().out
    assert "Nothing moved" in out
    assert "roll +4.0 deg, pitch -3.0 deg" in out
    assert hal.nudges == []
    assert hal.offsets_applied == []


def test_apply_probes_each_joint_out_and_back_and_levels_the_body(capsys) -> None:
    hal = TiltingFake()

    assert _run(hal, "--apply", "--iterations", "2") == 0

    out = capsys.readouterr().out
    # Every probe is undone: eight joints, out and back, on the first pass.
    assert len(hal.nudges) == 16
    assert {name for name, _ in hal.nudges} == set(LEG_SERVO_NAMES)
    assert sum(1 for _name, degrees in hal.nudges if degrees < 0) == 8
    # The trim was written once, and the body ended level.
    assert len(hal.offsets_applied) == 1
    assert abs(hal.tilt[0]) < 1.0
    assert abs(hal.tilt[1]) < 1.0
    assert "final trim" in out
    assert "pass 2" in out and "stopping" in out


def test_a_trim_beyond_the_limit_is_refused_and_nothing_is_saved(capsys) -> None:
    hal = TiltingFake(roll=60.0, pitch=0.0)

    assert _run(hal, "--apply", "--iterations", "1", "--max-trim", "1") == 1

    assert "mechanical problem" in capsys.readouterr().out
    assert hal.offsets_applied == []
    # The probes were still undone, so the dog is where it started.
    assert hal.tilt == pytest.approx([60.0, 0.0])


def test_an_already_level_dog_is_left_alone(capsys) -> None:
    hal = TiltingFake(roll=0.2, pitch=-0.3)

    assert _run(hal, "--apply") == 0

    assert "already" in capsys.readouterr().out
    assert hal.nudges == []
    assert hal.offsets_applied == []
