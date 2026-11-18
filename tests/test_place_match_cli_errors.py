"""The CLI's refusals, which need no OpenCV (#299).

`test_place_match_cli.py` covers the scoring path and is guarded, because `lite` has no OpenCV. These
are the answers a user gets when there is nothing to score, and they must be the same on a device
without the wheel and in CI with it.
"""

from __future__ import annotations

from types import SimpleNamespace

from tools.place_match import frames_in, main, verdict_for

__all__ = [
    "test_a_missing_directory_is_an_error",
    "test_no_frames_is_an_error",
    "test_no_views_is_an_error_rather_than_silence",
    "test_the_verdict_names_the_three_answers",
]


def test_no_views_is_an_error_rather_than_silence(tmp_path, capsys) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame.png").write_bytes(b"not an image")

    code = main([str(tmp_path / "nothing"), str(frames)])

    assert code == 1
    assert "no views" in capsys.readouterr().err


def test_a_missing_directory_is_an_error(tmp_path, capsys) -> None:
    views = tmp_path / "views"
    views.mkdir()
    (views / "views.json").write_text('{"version": 1, "views": []}', encoding="utf-8")

    code = main([str(views), str(tmp_path / "no-such-dir")])

    assert code == 1
    assert "no views" in capsys.readouterr().err


def test_no_frames_is_an_error(tmp_path, capsys) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "notes.txt").write_text("not a frame", encoding="utf-8")

    code = main([str(tmp_path / "nothing"), str(frames)])

    assert code == 1
    assert "no views" in capsys.readouterr().err


def test_the_verdict_names_the_three_answers() -> None:
    assert verdict_for(True, None) == "match"
    assert verdict_for(False, "frame too featureless (2 descriptors, 8 needed)") == "featureless"
    assert verdict_for(False, "best match hall at 0.20, below 0.45") == "no-match"


def test_only_image_suffixes_are_frames(tmp_path) -> None:
    for name in ("a.png", "b.JPG", "c.jpeg", "d.bmp", "e.txt", "f.json"):
        (tmp_path / name).write_bytes(b"x")

    names = [path.name for path in frames_in(tmp_path)]

    assert names == ["a.png", "b.JPG", "c.jpeg", "d.bmp"]
    assert SimpleNamespace(path=names[0]).path == "a.png"
