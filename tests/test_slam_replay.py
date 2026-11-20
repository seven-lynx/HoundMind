"""A clip is only a clip if a replay would measure it rather than an accident of it (plan S).

Two halves, one file: `--verify` refuses a clip that could not be replayed, and `--host` publishes
one into the real runtime so the measurement includes the loop. Both run on synthetic frames over a
fake dog: no camera, no servo, no SLAM library.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.optional.slam_clip import Clip, ClipWriter, load_clip
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


def test_without_a_mode_it_names_both_of_them(capsys: Any) -> None:
    assert slam_replay.main(["somewhere"]) == 2
    err = capsys.readouterr().err
    assert "--verify" in err and "--host" in err


# ---- host replay (S2) ------------------------------------------------------


class _Clock:
    """A monotonic clock that moves on every read, so a paced loop terminates without waiting."""

    def __init__(self, step: float = 0.02) -> None:
        self.value = 0.0
        self.step = step

    def now(self) -> float:
        current = self.value
        self.value += self.step
        return current

    def sleep(self, seconds: float) -> None:
        self.value += max(0.0, seconds)


class _DictContext(dict):
    """The two methods `replay_loop` uses, on a plain dict."""

    def set(self, key: str, value: object) -> None:
        self[key] = value

    def get(self, key: str, default: object | None = None) -> object | None:
        return dict.get(self, key, default)


class _StubRuntime:
    """What `replay_loop` touches: `context`, `modules`, `start`, `tick`, `stop`."""

    def __init__(
        self,
        *,
        slam_seconds: float = 0.001,
        stats: dict[str, int] | None = None,
        status: dict[str, str] | None = None,
    ) -> None:
        self.context = _DictContext()
        self.modules = [
            SimpleNamespace(name="slam_pi4", status=SimpleNamespace(started=True)),
            SimpleNamespace(name="hal_motors", status=SimpleNamespace(started=False)),
        ]
        self._slam_seconds = slam_seconds
        self._stats = stats
        self._status = status
        self.ticks = 0
        self.started = 0
        self.stopped = 0
        # One entry per tick: the frame the loop would have consumed on that tick.
        self.seen: list[Any] = []

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def tick(self) -> None:
        self.ticks += 1
        self.seen.append(self.context.get("vision_frame"))
        self.context["module_tick_durations"] = {"slam_pi4": self._slam_seconds}
        if self._stats is not None:
            self.context["slam_stats"] = dict(self._stats)
        if self._status is not None:
            self.context["slam_status"] = dict(self._status)


def _frames_clip(tmp_path: Path, stamps: list[float | None]) -> Clip:
    writer = ClipWriter(tmp_path / "clip", host={"node": "bench"}, commit="abc1234")
    payloads = [jpeg(64 + index, 48) for index in range(len(stamps))]
    for ts, payload in zip(stamps, payloads, strict=True):
        writer.append(
            ts=ts,
            wall=1000.0 if ts is None else 1000.0 + ts,
            jpeg=payload,
            imu={"ts": ts, "acc": [0.0, 0.0, 9.8], "gyro": [0.0, 0.0, 0.0], "valid": True},
        )
    writer.finish()
    return load_clip(tmp_path / "clip")


def test_the_replay_publishes_each_frame_once_and_in_order(tmp_path: Path) -> None:
    runtime = _StubRuntime()
    clip = _frames_clip(tmp_path, [0.0, 0.05, 0.10])
    clock = _Clock()

    result = slam_replay.replay_loop(
        runtime,
        clip,
        tick_hz=20,
        drain_s=0.0,
        now=clock.now,
        sleep=clock.sleep,
    )

    assert runtime.started == 1 and runtime.stopped == 1
    assert result["frames_delivered"] == 3
    assert result["started"] == ["slam_pi4"]
    # Each frame reached the context once, in the clip's order; a tick that saw no new frame keeps
    # the previous one, exactly as `vision_pi4` leaves it on the context between captures.
    order: list[bytes] = []
    previous: Any = object()
    for frame in runtime.seen:
        if frame is not None and frame != previous:
            order.append(frame)
            previous = frame
    assert order == [frame.jpeg for frame in clip.frames]
    assert result["slam_stats"] is None


def test_the_loop_keeps_ticking_between_frames(tmp_path: Path) -> None:
    runtime = _StubRuntime()
    clip = _frames_clip(tmp_path, [0.0, 0.5])

    clock = _Clock()
    result = slam_replay.replay_loop(
        runtime, clip, tick_hz=10, drain_s=0.0, now=clock.now, sleep=clock.sleep
    )

    # Half a second of clip at a 10 Hz loop is several ticks, not two frame deliveries.
    assert result["ticks"] > result["frames_delivered"]
    assert result["tick_hz"] == 10


def test_speed_compresses_the_clip_without_speeding_the_loop(tmp_path: Path) -> None:
    clip = _frames_clip(tmp_path, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])

    slow_clock = _Clock()
    slow = slam_replay.replay_loop(
        _StubRuntime(),
        clip,
        tick_hz=10,
        speed=1.0,
        drain_s=0.0,
        now=slow_clock.now,
        sleep=slow_clock.sleep,
    )
    fast_clock = _Clock()
    fast = slam_replay.replay_loop(
        _StubRuntime(),
        clip,
        tick_hz=10,
        speed=4.0,
        drain_s=0.0,
        now=fast_clock.now,
        sleep=fast_clock.sleep,
    )

    assert slow["frames_delivered"] == fast["frames_delivered"] == 6
    assert fast["ticks"] < slow["ticks"]


def test_a_slam_tick_over_the_budget_is_counted(tmp_path: Path) -> None:
    runtime = _StubRuntime(slam_seconds=0.5)
    clip = _frames_clip(tmp_path, [0.0, 0.05])

    # A clock that advances 0.1 s per read makes a tick cost more than the 50 ms budget at 20 Hz, so
    # both counters have something to count.
    clock = _Clock(step=0.1)
    result = slam_replay.replay_loop(
        runtime, clip, tick_hz=20, drain_s=0.0, now=clock.now, sleep=clock.sleep
    )

    assert result["slam_pi4"]["samples"] >= 1
    assert result["slam_pi4"]["overruns"] >= 1
    assert result["overruns"] >= 1


def test_a_clip_with_no_frames_is_refused_before_a_runtime_runs(tmp_path: Path) -> None:
    runtime = _StubRuntime()
    clip = Clip(directory=tmp_path, manifest={}, frames=[])

    try:
        slam_replay.replay_loop(runtime, clip, tick_hz=10)
    except slam_replay.ClipError as exc:
        assert "no frames" in str(exc)
    else:  # pragma: no cover - the point of the test
        raise AssertionError("an empty clip was replayed")
    assert runtime.started == 0


def test_the_cli_replays_into_the_real_runtime_and_writes_one_report(
    tmp_path: Path, capsys: Any
) -> None:
    path = _clip(tmp_path, [0.0, 0.05, 0.10, 0.15])

    code = slam_replay.main(
        [str(path), "--host", "pi", "--tick-hz", "20", "--drain-s", "0"], hal=FakeDogHAL()
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "verdict:" in out
    report = json.loads((path / "replay-pi-stub.json").read_text(encoding="utf-8"))
    assert report["format"] == "houndmind-slam-replay"
    assert report["version"] == 1
    assert report["host"]["label"] == "pi"
    assert report["clip"]["frames"] == report["frames"]["delivered"] == 4
    assert report["clip"]["commit"] == "abc1234"
    assert report["slam_status"]["backend"] == "stub"
    assert report["frames"]["slam"] is not None
    # The modules that could move, and the one that would overwrite the clip's IMU, were off.
    assert "hal_motors" in report["disabled"]
    assert "hal_sensors" in report["disabled"]
    assert "slam_pi4" in report["started"]
    assert report["verdict"].startswith("stub on the pi host:")


def test_a_backend_the_config_does_not_get_is_named_in_the_report(tmp_path: Path) -> None:
    path = _clip(tmp_path, [0.0, 0.05])

    code = slam_replay.main(
        [str(path), "--host", "pi", "--backend", "rtabmap", "--tick-hz", "20", "--drain-s", "0"],
        hal=FakeDogHAL(),
    )

    assert code == 0
    report = json.loads((path / "replay-pi-rtabmap.json").read_text(encoding="utf-8"))
    assert report["backend"] == "rtabmap"
    # Whatever this host has installed, the report has to say what actually ran.
    if report["slam_status"]["backend"] != "rtabmap":
        assert any("started `stub`" in note for note in report["notes"])


def test_the_label_never_stands_in_for_the_platform(tmp_path: Path) -> None:
    path = _clip(tmp_path, [0.0, 0.05])

    assert (
        slam_replay.main(
            [str(path), "--host", "pi", "--tick-hz", "20", "--drain-s", "0"], hal=FakeDogHAL()
        )
        == 0
    )
    report = json.loads((path / "replay-pi-stub.json").read_text(encoding="utf-8"))
    assert report["host"]["platform"]
    assert report["host"]["machine"]


def test_a_zero_speed_a_frame_budget_of_zero_or_a_negative_drain_is_refused(
    capsys: Any,
) -> None:
    assert slam_replay.main(["somewhere", "--host", "pi", "--speed", "0"]) == 2
    assert "--speed" in capsys.readouterr().err
    assert slam_replay.main(["somewhere", "--host", "pi", "--max-frames", "0"]) == 2
    assert "--max-frames" in capsys.readouterr().err
    assert slam_replay.main(["somewhere", "--host", "pi", "--drain-s", "-1"]) == 2
    assert "--drain-s" in capsys.readouterr().err


def test_verify_and_host_together_are_refused(capsys: Any) -> None:
    assert slam_replay.main(["somewhere", "--verify", "--host", "pi"]) == 2
    assert "one of them" in capsys.readouterr().err



