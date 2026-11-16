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
