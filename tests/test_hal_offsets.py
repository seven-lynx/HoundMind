"""The servo trim crosses the HAL boundary in both directions (#10).

The vendor stores three ordered lists (`legs_servo_offset_list`, `head_servo_offset_list`,
`tail_servo_offset_list`) and its setters replace a whole list. Two rules follow, and this file
pins both: joint names map positionally onto those lists, and a write merges over the values the
hardware already has instead of zeroing the joints nobody measured.

`PidogHAL(dog=...)` is the injection seam, so none of this imports `pidog` on a workstation.
Motion: the vendor has no silent-save path, so a trim write re-poses as it saves (#263) — it must land
on the pose the dog already holds, and the stub fails the test if the write would reset the legs
instead. `nudge_joint` is the one call that moves a joint on purpose.
"""

from __future__ import annotations

import logging

import pytest

from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import HEAD_SERVO_NAMES, LEG_SERVO_NAMES, TAIL_SERVO_NAMES
from houndmind_ai.hal.vendor import PidogHAL

VENDOR = "houndmind_ai.hal.vendor"


class StubRobot:
    """`robot_hat.Robot`, reduced to the offset list and the setter that replaces it."""

    def __init__(self, pins: int) -> None:
        self.offset: list[float] | None = [0.0] * pins
        self.saved: list[float] | None = None

    def set_offset(self, values: list[float]) -> None:
        self.saved = list(values)
        self.offset = list(values)


class StubDog:
    """`pidog.Pidog`, reduced to the three joint groups the trim lives on, plus the move calls."""

    def __init__(self) -> None:
        self.legs = StubRobot(8)
        self.head = StubRobot(3)
        self.tail = StubRobot(1)
        self.leg_current_angles: list[float] | None = [0.0] * 8
        self.head_current_angles: list[float] | None = [0.0] * 3
        self.tail_current_angles: list[float] | None = [0.0]
        self.posed: list[float] | None = None
        self.moves: list[tuple[str, list[float], int]] = []

    def set_leg_offsets(self, cali_list: list[float], reset_list=None) -> None:
        if reset_list is None:
            # `reset_list=None` is the vendor's "drive all eight leg servos to zero" branch (#263).
            raise AssertionError("an offset write must land on a pose, not reset the legs")
        self.posed = list(reset_list)
        self.legs.set_offset(cali_list)

    def set_head_offsets(self, cali_list: list[float]) -> None:
        self.head.set_offset(cali_list)

    def set_tail_offset(self, cali_list: list[float]) -> None:
        self.tail.set_offset(cali_list)

    def legs_move(self, target_angles, immediately=True, speed=50) -> None:
        self.moves.append(("legs", list(target_angles[0]), speed))
        self.leg_current_angles = list(target_angles[0])

    def head_move_raw(self, target_angles, immediately=True, speed=50) -> None:
        self.moves.append(("head", list(target_angles[0]), speed))
        self.head_current_angles = list(target_angles[0])

    def tail_move(self, target_angles, immediately=True, speed=50) -> None:
        self.moves.append(("tail", list(target_angles[0]), speed))
        self.tail_current_angles = list(target_angles[0])


def hal_for(dog: StubDog) -> PidogHAL:
    return PidogHAL(settings={}, dog=dog)


def test_read_offsets_names_the_vendor_lists_in_their_own_order() -> None:
    dog = StubDog()
    dog.legs.offset = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    dog.head.offset = [-1.0, 0.0, 2.5]
    dog.tail.offset = [4.0]

    assert hal_for(dog).read_offsets() == {
        **dict(zip(LEG_SERVO_NAMES, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], strict=True)),
        **dict(zip(HEAD_SERVO_NAMES, [-1.0, 0.0, 2.5], strict=True)),
        **dict(zip(TAIL_SERVO_NAMES, [4.0], strict=True)),
    }


def test_an_unreadable_group_is_absent_rather_than_zero() -> None:
    """"Could not read" is not "measured straight" — the same rule `SensorSnapshot` follows."""
    dog = StubDog()
    dog.legs.offset = None
    dog.head.offset = [0.0, 0.0, 0.0]

    offsets = hal_for(dog).read_offsets()

    assert not [name for name in offsets if name in LEG_SERVO_NAMES]
    assert offsets["head_yaw"] == 0.0


def test_a_short_list_is_not_guessed_at() -> None:
    dog = StubDog()
    dog.head.offset = [1.0]

    assert not [name for name in hal_for(dog).read_offsets() if name in HEAD_SERVO_NAMES]


def test_apply_offsets_merges_over_the_values_already_loaded() -> None:
    """The vendor setter replaces the whole list: one joint must not zero the other seven."""
    dog = StubDog()
    dog.legs.offset = [1.0] * 8
    hal = hal_for(dog)

    hal.apply_offsets({"lf_shoulder": 3.0})

    assert dog.legs.saved == [3.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    assert hal.read_offsets()["lf_shoulder"] == 3.0


def test_apply_offsets_reaches_each_group_through_its_own_setter() -> None:
    dog = StubDog()
    hal = hal_for(dog)

    hal.apply_offsets({"head_pitch": -2.0, "tail": 5.0})

    assert dog.head.saved == [0.0, 0.0, -2.0]
    assert dog.tail.saved == [5.0]
    assert dog.legs.saved is None


def test_apply_offsets_clamps_to_the_vendor_limit(caplog) -> None:
    dog = StubDog()
    hal = hal_for(dog)

    with caplog.at_level(logging.WARNING, logger=VENDOR):
        hal.apply_offsets({"lf_shoulder": 25.0, "lf_leg": -40.0})

    assert dog.legs.saved is not None
    assert dog.legs.saved[0] == 20.0
    assert dog.legs.saved[1] == -20.0
    assert "clamped" in caplog.text


def test_apply_offsets_ignores_a_name_the_contract_does_not_know(caplog) -> None:
    dog = StubDog()
    with caplog.at_level(logging.WARNING, logger=VENDOR):
        hal_for(dog).apply_offsets({"leg_0": 5.0, "toggle": 1.0})

    assert dog.legs.saved is None and dog.head.saved is None and dog.tail.saved is None
    assert "unknown servo offset" in caplog.text


def test_a_group_with_no_readable_baseline_is_not_written(caplog) -> None:
    """Writing the rest of the list as zeros would be user data nobody measured."""
    dog = StubDog()
    dog.legs.offset = None
    with caplog.at_level(logging.WARNING, logger=VENDOR):
        hal_for(dog).apply_offsets({"lf_shoulder": 3.0})

    assert dog.legs.saved is None
    assert "not writing" in caplog.text


def test_a_missing_vendor_setter_is_a_warning_not_a_crash(caplog) -> None:
    class NoSetters(StubDog):
        set_tail_offset = None  # type: ignore[assignment]

    dog = NoSetters()
    with caplog.at_level(logging.WARNING, logger=VENDOR):
        hal_for(dog).apply_offsets({"tail": 2.0})

    assert "no set_tail_offset()" in caplog.text


def test_the_fake_round_trips_the_same_contract() -> None:
    hal = FakeDogHAL()
    hal.set_offsets({"lf_shoulder": 1.0, "tail": 0.0})

    hal.apply_offsets({"lf_shoulder": 25.0, "leg_0": 4.0})

    assert hal.read_offsets() == {"lf_shoulder": 20.0, "tail": 0.0}
    assert hal.offsets_applied == [{"lf_shoulder": 25.0, "leg_0": 4.0}]


def test_the_fake_will_not_invent_a_baseline_either() -> None:
    hal = FakeDogHAL()
    hal.apply_offsets({"lf_shoulder": 3.0})

    assert hal.read_offsets() == {}


def test_a_legs_write_lands_on_the_pose_the_dog_is_already_in() -> None:
    """#263: `reset_list=None` is the vendor branch that drives every leg servo to zero."""
    dog = StubDog()
    dog.leg_current_angles = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]

    hal_for(dog).apply_offsets({"lf_shoulder": 3.0})

    assert dog.posed == [5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]


def test_an_unreadable_pose_skips_the_write_rather_than_resetting_the_legs(caplog) -> None:
    dog = StubDog()
    dog.leg_current_angles = None

    with caplog.at_level(logging.WARNING, logger=VENDOR):
        hal_for(dog).apply_offsets({"lf_shoulder": 3.0})

    assert dog.legs.saved is None
    assert "not saving that group" in caplog.text


def test_a_caller_supplied_pose_is_used_for_the_legs_write() -> None:
    """The interactive trim asks for a pose on purpose; that is the only sanctioned move here."""
    dog = StubDog()
    pose = dict(zip(LEG_SERVO_NAMES, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], strict=True))

    hal_for(dog).apply_offsets({"lf_shoulder": 3.0}, pose=pose)

    assert dog.posed == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]


def test_a_pose_missing_a_joint_is_not_half_applied(caplog) -> None:
    dog = StubDog()

    with caplog.at_level(logging.WARNING, logger=VENDOR):
        hal_for(dog).apply_offsets({"lf_shoulder": 3.0}, pose={"lf_shoulder": 1.0})

    assert dog.legs.saved is None
    assert "Pose is missing" in caplog.text


def test_nudge_moves_one_joint_relative_to_where_it_is() -> None:
    dog = StubDog()
    dog.leg_current_angles = [10.0] * 8

    hal_for(dog).nudge_joint("lf_shoulder", 2.0)

    group, angles, speed = dog.moves[-1]
    assert group == "legs"
    assert angles[LEG_SERVO_NAMES.index("lf_shoulder")] == pytest.approx(12.0)
    assert angles[: LEG_SERVO_NAMES.index("lf_shoulder")] == [10.0] * LEG_SERVO_NAMES.index(
        "lf_shoulder"
    )
    assert speed == 30
    # No trim written: a probe must be undoable by nudging back.
    assert dog.legs.saved is None


def test_nudge_clamps_the_step_and_the_angle(caplog) -> None:
    dog = StubDog()
    dog.leg_current_angles = [89.0] + [0.0] * 7

    with caplog.at_level(logging.WARNING, logger=VENDOR):
        hal_for(dog).nudge_joint(LEG_SERVO_NAMES[0], 99.0)

    assert dog.moves[-1][1][0] == 90.0  # step capped to 3, then the servo capped to 90
    assert "clamped" in caplog.text


def test_nudge_moves_the_head_and_tail_through_their_own_calls() -> None:
    dog = StubDog()
    hal = hal_for(dog)

    hal.nudge_joint(HEAD_SERVO_NAMES[0], 1.5)
    hal.nudge_joint(TAIL_SERVO_NAMES[0], -1.5)

    assert dog.moves == [("head", [1.5, 0.0, 0.0], 30), ("tail", [-1.5], 30)]


def test_nudge_refuses_an_unknown_joint() -> None:
    with pytest.raises(ValueError):
        hal_for(StubDog()).nudge_joint("nose", 1.0)


def test_nudge_refuses_when_the_pose_is_unreadable() -> None:
    dog = StubDog()
    dog.leg_current_angles = None

    with pytest.raises(RuntimeError):
        hal_for(dog).nudge_joint(LEG_SERVO_NAMES[0], 1.0)


def test_the_fake_records_nudges_and_the_pose_a_trim_landed_on() -> None:
    hal = FakeDogHAL()

    hal.nudge_joint("lf_shoulder", 2.0)
    hal.apply_offsets({"lf_shoulder": 3.0}, pose={"lf_shoulder": 4.0})

    assert hal.nudges == [("lf_shoulder", 2.0)]
    assert hal.poses_applied == [{"lf_shoulder": 4.0}]

