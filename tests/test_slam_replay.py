"""A clip is only a clip if a replay would measure it rather than an accident of it (plan S, S1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from houndmind_ai.optional.slam_clip import ClipWriter
from tools import slam_replay


def jpeg(width: int = 64, height: int = 48) -> bytes:
    """A JPEG header: SOI, SOF0 carrying the dimensions, EOI. Verification decodes no pixels."""
    body = (
        b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + body + b"\xff\xd9"


def _clip(
    tmp_path: Path,
    stamps: list[float | None],
    *,
    complete: bool = True,
    frames: list[bytes] | None = None,
) -> Path:
    writer = ClipWriter(tmp_path / "clip", host={"node": "bench"}, commit="abc1234")
    payloads = frames or [jpeg() for _ in stamps]
    for ts, payload in zip(stamps, payloads, strict=True):
        writer.append(
            ts=ts,
            wall=1000.0 if ts is None else 1000.0 + ts,
            jpeg=payload,
            imu={"ts": ts, "acc": [0.0, 0.0, 9.8], "gyro": [0.0, 0.0, 0.0], "valid": True},
        )
    writer.finish(complete=complete)
    return tmp_path / "clip"


def test_a_regular_clip_passes(tmp_path: Path, capsys: Any) -> None:
    path = _clip(tmp_path, [index * 0.2 for index in range(11)])

    assert slam_replay.main([str(path), "--verify"]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "frames:    11 (manifest says 11)" in out
    assert "64x48" in out


def test_json_mode_carries_the_numbers_a_table_would_quote(tmp_path: Path, capsys: Any) -> None:
    path = _clip(tmp_path, [index * 0.2 for index in range(11)])

    assert slam_replay.main([str(path), "--verify", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "pass"
    assert report["frames"] == report["manifest_frames"] == 11
    assert report["resolution"] == [64, 48]
    assert report["commit"] == "abc1234"
    assert report["host"] == "bench"
    assert abs(report["timing"]["p50_ms"] - 200.0) < 0.5
    assert report["timing"]["jitter_p95_pct"] < 1.0


def test_a_frame_count_the_manifest_does_not_agree_with_fails(tmp_path: Path, capsys: Any) -> None:
    path = _clip(tmp_path, [index * 0.2 for index in range(5)])
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    manifest["frame_count"] = 99
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert slam_replay.main([str(path), "--verify"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "99" in out and "5" in out


def test_a_line_that_is_not_a_jpeg_fails(tmp_path: Path, capsys: Any) -> None:
    path = _clip(tmp_path, [0.0, 0.2, 0.4], frames=[jpeg(), b"not a jpeg", jpeg()])

    assert slam_replay.main([str(path), "--verify"]) == 1
    out = capsys.readouterr().out
    assert "not JPEG" in out and "index 1" in out


def test_frames_that_disagree_on_resolution_fail(tmp_path: Path, capsys: Any) -> None:
    path = _clip(tmp_path, [0.0, 0.2], frames=[jpeg(64, 48), jpeg(32, 24)])

    assert slam_replay.main([str(path), "--verify"]) == 1
    assert "disagree on resolution" in capsys.readouterr().out


def test_a_jittery_clip_fails_at_the_tolerance(tmp_path: Path, capsys: Any) -> None:
    path = _clip(tmp_path, [0.0, 0.2, 0.25, 0.9, 1.1, 1.3, 1.5, 1.7])

    assert slam_replay.main([str(path), "--verify"]) == 1
    assert "jitter" in capsys.readouterr().out


def test_a_loose_tolerance_accepts_the_same_clip(tmp_path: Path) -> None:
    path = _clip(tmp_path, [0.0, 0.2, 0.25, 0.9, 1.1, 1.3, 1.5, 1.7])

    assert slam_replay.main([str(path), "--verify", "--tolerance-pct", "300"]) == 0


def test_a_clip_closed_unfinished_is_refused(tmp_path: Path, capsys: Any) -> None:
    path = _clip(tmp_path, [0.0, 0.2], complete=False)

    assert slam_replay.main([str(path), "--verify"]) == 1
    assert "unfinished" in capsys.readouterr().out


def test_a_missing_manifest_is_named_rather_than_guessed(tmp_path: Path, capsys: Any) -> None:
    path = tmp_path / "nothing-here"

    assert slam_replay.main([str(path), "--verify"]) == 1
    assert "manifest.json is missing" in capsys.readouterr().err


def test_without_verify_it_says_where_the_replay_lives(capsys: Any) -> None:
    assert slam_replay.main(["somewhere"]) == 2
    assert "S2" in capsys.readouterr().err
