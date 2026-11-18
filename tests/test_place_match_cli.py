"""The CLI that scores a folder of frames off the dog (#299).

The frames are **synthetic**: drawn here with OpenCV, so CI runs the whole path — views file, ORB,
threshold, verdict, exit code — without a photograph of anyone's home ever entering the repository.
`tests/fixtures/places/README.md` says the same thing beside the directory, because a fixture set
nobody can find is how the next session re-derives it.

Guarded by `importorskip`: `lite` carries no OpenCV, and the workstation venv does not either.
"""

from __future__ import annotations

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from houndmind_ai.perception.place_views import save_views, view_from_frame  # noqa: E402
from tools.place_match import main  # noqa: E402

__all__ = [
    "test_a_featureless_frame_is_reported_as_such",
    "test_a_taught_place_is_recognised_and_a_stranger_is_not",
    "test_no_views_is_an_error_rather_than_silence",
]


def _textured(seed: int, size: tuple[int, int] = (240, 320)):
    """A deterministic, textured image: ORB needs corners, and a seed keeps the test repeatable."""
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 60, (size[0], size[1], 3)).astype("uint8")
    for _ in range(60):
        x = int(rng.integers(0, size[1] - 24))
        y = int(rng.integers(0, size[0] - 24))
        colour = tuple(int(value) for value in rng.integers(120, 255, 3))
        cv2.rectangle(image, (x, y), (x + 14, y + 14), colour, -1)
    return image


def _write(image, path) -> None:
    assert cv2.imwrite(str(path), image)


def test_a_taught_place_is_recognised_and_a_stranger_is_not(tmp_path, capsys) -> None:
    views = tmp_path / "views"
    save_views(views, (view_from_frame(_textured(1), "kitchen", now=1.0),))

    frames = tmp_path / "frames"
    frames.mkdir()
    _write(_textured(1), frames / "kitchen.png")
    _write(_textured(99), frames / "elsewhere.png")

    code = main([str(views), str(frames), "--min-score", "0.6"])

    rows = {
        line.split()[0]: line.split()
        for line in capsys.readouterr().out.splitlines()
        if line
    }
    assert code == 0
    # Frames are reported in sorted order, so index by name rather than position.
    assert rows["kitchen.png"][1] == "kitchen"
    assert rows["kitchen.png"][3] == "match"
    assert rows["elsewhere.png"][1] == "-"
    assert rows["elsewhere.png"][3] == "no-match"


def test_a_featureless_frame_is_reported_as_such(tmp_path, capsys) -> None:
    views = tmp_path / "views"
    save_views(views, (view_from_frame(_textured(2), "kitchen", now=1.0),))

    frames = tmp_path / "frames"
    frames.mkdir()
    _write(np.full((240, 320, 3), 128, dtype="uint8"), frames / "wall.png")

    code = main([str(views), str(frames)])

    out = capsys.readouterr().out
    assert code == 0
    assert "featureless" in out


def test_no_views_is_an_error_rather_than_silence(tmp_path, capsys) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    _write(_textured(3), frames / "kitchen.png")

    code = main([str(tmp_path / "nothing"), str(frames)])

    assert code == 1
    assert "no views" in capsys.readouterr().err
