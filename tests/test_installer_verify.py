"""The verifier reads a mirror of the extras, so it has to parse the pins those files carry."""

from __future__ import annotations

import pytest

from tools.installer_verify import package_name


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("numpy<2", "numpy"),
        ("opencv-contrib-python<4.12", "opencv-contrib-python"),
        ("scipy>=1.10", "scipy"),
        ("flake8==6.1.0", "flake8"),
        ("vosk", "vosk"),
        ("SpeechRecognition", "SpeechRecognition"),
        ("some-pkg!=2.0", "some-pkg"),
        ("compatible~=1.4", "compatible"),
    ],
)
def test_a_version_specifier_is_not_part_of_the_name(line, expected) -> None:
    """#242: `numpy<2` was imported as `numpy<2`, so an installed package read as MISSING."""
    assert package_name(line) == expected


def test_the_pins_this_repo_ships_parse_to_real_packages() -> None:
    """The mirror is the live input, so assert on it rather than on a copy of it."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    names = [
        package_name(line)
        for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert "numpy" in names
    assert not any("<" in name or ">" in name for name in names), names


def test_rtabmap_is_unsupported_rather_than_missing(tmp_path, capsys) -> None:
    """#181: the bindings cannot be installed, so the check must not pretend either way."""
    from tools.installer_verify import UNSUPPORTED_REQUIREMENTS, check_requirements

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("rtabmap-py==0.21.0\n", encoding="utf-8")

    assert check_requirements(requirements) is True
    printed = capsys.readouterr().out
    assert "UNSUPPORTED" in printed
    assert "slam_pi4" in printed
    assert "MISSING" not in printed
    assert "rtabmap-py" in UNSUPPORTED_REQUIREMENTS


def test_no_boot_config_means_not_applicable(tmp_path, capsys) -> None:
    """A workstation has no Pi boot config, and that is not a failure (#288)."""
    from tools.installer_verify import check_audio_chain

    assert check_audio_chain(boot_config=tmp_path / "absent.txt") is True
    assert "not applicable" in capsys.readouterr().out


def test_a_missing_overlay_warns_without_failing_the_check(tmp_path, capsys) -> None:
    """A dog with no voice stack does not need a speaker, so absence is a warning (#288)."""
    from tools.installer_verify import check_audio_chain

    boot = tmp_path / "config.txt"
    boot.write_text("dtparam=audio=on\n", encoding="utf-8")

    assert check_audio_chain(boot_config=boot) is True
    printed = capsys.readouterr().out
    assert "WARN" in printed
    assert "dtoverlay=hifiberry-dac" in printed


def test_a_half_configured_hat_fails_the_check(tmp_path, capsys) -> None:
    """#254: the overlay is enabled and nothing routes the default PCM to the card."""
    from tools.installer_verify import check_audio_chain

    boot = tmp_path / "config.txt"
    boot.write_text("dtoverlay=hifiberry-dac\n", encoding="utf-8")
    asound = tmp_path / "asound.conf"
    asound.write_text("pcm.!default { type hw card 0 }\n", encoding="utf-8")

    assert check_audio_chain(boot_config=boot, asound=asound) is False
    assert "robothat" in capsys.readouterr().out


def test_a_complete_chain_is_ok(tmp_path, capsys) -> None:
    from tools.installer_verify import check_audio_chain

    boot = tmp_path / "config.txt"
    boot.write_text("dtoverlay=hifiberry-dac\n", encoding="utf-8")
    asound = tmp_path / "asound.conf"
    asound.write_text("pcm.!default {\n  type plug\n  slave.pcm robothat\n}\n", encoding="utf-8")

    assert check_audio_chain(boot_config=boot, asound=asound) is True
    assert "audio: OK" in capsys.readouterr().out


def test_the_dry_chain_carries_the_motion_safe_flags() -> None:
    """#315: the flags are the whole point, so they are asserted rather than remembered."""
    from tools.installer_verify import dry_chain

    chain = dry_chain("python")
    modules = [command[2] for command in chain]

    assert modules == ["tools.installer_verify", "tools.hardware_checkup", "tools.smoke_test"]
    assert "--skip-motion" in chain[1]
    assert "--include-motion" not in chain[2]
    assert not any("motion" in part for part in chain[2])
