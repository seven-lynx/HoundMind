"""The trim tool drives a `DogHAL`, so the fake can exercise all of it - including `--apply`.

#142: the vendor's interactive script was the only way to *save* a trim, so nothing in this repo
could reach the step every install needs before the dog stands straight. Every case here is
`FakeDogHAL`-only: no servo is commanded, and `--apply` writes a value, never a pose.
"""

from __future__ import annotations

import pytest

from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import SERVO_NAMES, SERVO_OFFSET_LIMIT_DEG
from tools.calibrate_servos import main


def _measured(**overrides: float) -> FakeDogHAL:
    """A trim the vendor file would hold: every joint present, zeros unless overridden."""
    values = {name: 0.0 for name in SERVO_NAMES}
    values.update(overrides)
    hal = FakeDogHAL()
    hal.set_offsets(values)
    return hal


def test_it_prints_every_joint_in_the_vendor_order_and_saves_nothing(capsys) -> None:
    hal = _measured()

    assert main([], hal=hal) == 0

    out = capsys.readouterr().out
    positions = [out.index(name) for name in SERVO_NAMES]
    assert positions == sorted(positions), "joints must come out in SERVO_GROUPS order"
    assert "[tune] legs" in out and "[tune] head" in out and "[tune] tail" in out
    assert "[tune] nothing to save" in out
    assert hal.offsets_applied == []


def test_a_set_without_apply_is_a_dry_run(capsys) -> None:
    hal = _measured()

    assert main(["--set", "lf_shoulder=4"], hal=hal) == 0

    out = capsys.readouterr().out
    assert "+4.0" in out
    assert "dry run: 1 joint(s) would change; re-run with --apply to save" in out
    assert hal.offsets_applied == []
    assert hal.read_offsets()["lf_shoulder"] == 0.0


def test_apply_writes_through_the_hal_and_reads_it_back(capsys) -> None:
    hal = _measured()

    assert main(["--set", "lf_shoulder=4", "--set", "tail=-2.5", "--apply"], hal=hal) == 0

    out = capsys.readouterr().out
    assert "[tune] saved 2/2 joint(s)" in out
    assert hal.offsets_applied == [{"lf_shoulder": 4.0, "tail": -2.5}]
    assert hal.read_offsets()["lf_shoulder"] == 4.0
    assert hal.read_offsets()["tail"] == -2.5
    # Saving a trim is not a move: no action reached the HAL.
    assert hal.calls == []


def test_a_value_beyond_the_limit_is_clamped_not_refused(capsys) -> None:
    hal = _measured()

    assert main(["--set", f"tail={SERVO_OFFSET_LIMIT_DEG + 30}", "--apply"], hal=hal) == 0

    out = capsys.readouterr().out
    assert f"+{SERVO_OFFSET_LIMIT_DEG:.1f}" in out
    assert hal.read_offsets()["tail"] == SERVO_OFFSET_LIMIT_DEG


def test_an_unknown_joint_is_a_usage_error(capsys) -> None:
    hal = _measured()

    assert main(["--set", "hoof=1"], hal=hal) == 2

    assert "unknown joint 'hoof'" in capsys.readouterr().err
    assert hal.offsets_applied == []


def test_a_value_that_is_not_a_number_is_a_usage_error(capsys) -> None:
    hal = _measured()

    assert main(["--set", "tail=sideways"], hal=hal) == 2

    assert "is not a number" in capsys.readouterr().err


def test_a_hardware_with_no_readable_trim_writes_nothing(capsys) -> None:
    hal = FakeDogHAL()

    assert main(["--set", "tail=2", "--apply"], hal=hal) == 2

    captured = capsys.readouterr()
    assert "reported no servo offsets" in captured.err
    assert hal.offsets_applied == []


def test_a_joint_with_no_baseline_is_not_written(capsys) -> None:
    """`apply_offsets` would have to invent the rest of that vendor list, so it refuses."""
    hal = FakeDogHAL()
    hal.set_offsets({name: 0.0 for name in SERVO_NAMES if name != "tail"})

    assert main(["--set", "tail=3", "--apply"], hal=hal) == 0

    captured = capsys.readouterr()
    assert "tail: the dog reported no current value" in captured.err
    assert "[tune] nothing to save" in captured.out
    assert hal.offsets_applied == []


# ---- --interactive: the guided pass --------------------------------------------------------------


def _keys(*sequence: str):
    """A `read_key` handing back the script, then Enter forever."""
    pending = list(sequence)

    def read_key() -> str:
        return pending.pop(0) if pending else "\r"

    return read_key


def _interactive(hal: FakeDogHAL, *keys: str, only: str = "lf_shoulder", runtime: bool = False) -> int:
    return main(
        ["--interactive", "--only", only],
        hal=hal,
        read_key=_keys(*keys),
        runtime_up=lambda: runtime,
    )


def test_interactive_steps_a_joint_and_keeps_it(capsys) -> None:
    hal = _measured()

    assert _interactive(hal, "+", "+", "\r") == 0

    assert hal.read_offsets()["lf_shoulder"] == pytest.approx(0.88)
    assert "trimmed 1 joint" in capsys.readouterr().out


def test_interactive_takes_the_arrow_keys(capsys) -> None:
    hal = _measured()

    assert _interactive(hal, "\x1b[C", "\x1b[C", "\r") == 0

    assert hal.read_offsets()["lf_shoulder"] == pytest.approx(0.88)


def test_interactive_steps_down_too(capsys) -> None:
    hal = _measured(lf_shoulder=1.0)

    assert _interactive(hal, "-", "-", "\r") == 0

    assert hal.read_offsets()["lf_shoulder"] == pytest.approx(0.12)


def test_interactive_never_passes_the_offset_limit() -> None:
    hal = _measured()

    assert _interactive(hal, *(["+"] * 100), "\r", only="tail") == 0

    assert hal.read_offsets()["tail"] == SERVO_OFFSET_LIMIT_DEG


def test_a_skip_walks_back_a_step_already_taken(capsys) -> None:
    hal = _measured()

    assert _interactive(hal, "+", "s", only="lf_leg") == 0

    assert hal.read_offsets()["lf_leg"] == 0.0
    assert "nothing changed" in capsys.readouterr().out


def test_quit_restores_what_the_pass_changed(capsys) -> None:
    hal = _measured(lf_shoulder=2.0)

    assert _interactive(hal, "+", "+", "q") == 2

    assert hal.read_offsets()["lf_shoulder"] == pytest.approx(2.0)
    assert "restoring" in capsys.readouterr().out


def test_interactive_refuses_while_the_runtime_is_up(capsys) -> None:
    hal = _measured()

    assert _interactive(hal, "\r", runtime=True) == 2

    assert hal.offsets_applied == []
    assert "stop the houndmind service" in capsys.readouterr().err


def test_interactive_and_set_are_not_mixable(capsys) -> None:
    assert main(["--interactive", "--set", "tail=1"], hal=_measured(),
                read_key=_keys("\r"), runtime_up=lambda: False) == 2

    assert "choose one" in capsys.readouterr().err


def test_an_unknown_only_joint_is_refused(capsys) -> None:
    assert _interactive(_measured(), "\r", only="nose") == 2

    assert "unknown joint" in capsys.readouterr().err


def test_a_key_it_does_not_know_is_ignored() -> None:
    hal = _measured()

    assert _interactive(hal, "x", "?", "\r") == 0

    assert hal.offsets_applied == []
    assert hal.read_offsets()["lf_shoulder"] == 0.0


def test_interactive_walks_every_joint_by_default(capsys) -> None:
    hal = _measured()

    assert main(["--interactive"], hal=hal, read_key=_keys(), runtime_up=lambda: False) == 0

    out = capsys.readouterr().out
    assert f"interactive trim, {len(SERVO_NAMES)} joint(s)" in out
    assert "nothing changed" in out

