"""The clip is written from what the runtime publishes, and the manifest says what arrived.

Synthetic frames over a stubbed runtime: no camera, no dog, no servo (plan S, S1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.optional.slam_clip import ClipWriter, load_clip
from houndmind_ai.services.camera import FRAME_KEY, FRAME_TS_KEY
from tools import camera_record


def jpeg(width: int = 64, height: int = 48) -> bytes:
    """A JPEG header: SOI, SOF0 carrying the dimensions, EOI. `jpeg_size` reads no pixels."""
    body = (
        b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + body + b"\xff\xd9"


def reading(valid: bool = True) -> SensorReading:
    return SensorReading(
        distance_cm=100.0,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=(0.0, 0.0, 9.81),
        gyro=(0.01, -0.02, 0.03),
        timestamp=12.5,
        distance_valid=True,
        touch_valid=True,
        sound_valid=True,
        imu_valid=valid,
    )


class _Clock:
    """A monotonic clock that moves on every read, so a loop terminates without real waiting."""

    def __init__(self, step: float = 0.05) -> None:
        self.value = 0.0
        self.step = step

    def now(self) -> float:
        current = self.value
        self.value += self.step
        return current

    def sleep(self, seconds: float) -> None:
        self.value += max(0.0, seconds)


class _StubRuntime:
    """The three members `record_loop` uses, plus a frame source like a vision module's."""

    def __init__(self, frames: list[tuple[float, bytes]], every: int = 1) -> None:
        self.context: dict[str, Any] = {}
        self._frames = frames
        self._every = max(1, every)
        self._ticks = 0
        self._index = 0
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def tick(self) -> None:
        if not self._frames:
            return
        if self._ticks % self._every == 0:
            # Past the list, the last frame keeps being served - a scene that stopped moving.
            ts, data = self._frames[min(self._index, len(self._frames) - 1)]
            self.context[FRAME_KEY] = data
            self.context[FRAME_TS_KEY] = ts
            self._index += 1
        self._ticks += 1


def _record(tmp_path: Path, runtime: _StubRuntime, **kwargs: Any) -> tuple[dict[str, Any], Any]:
    clock = _Clock()
    writer = ClipWriter(tmp_path, host=kwargs.get("host"), commit=kwargs.get("commit"))
    camera_record.record_loop(
        runtime,
        writer,
        seconds=kwargs.get("seconds", 5.0),
        tick_hz=kwargs.get("tick_hz", 5),
        max_frames=kwargs.get("max_frames"),
        now=clock.now,
        sleep=clock.sleep,
        wall=lambda: 1000.0,
    )
    manifest = writer.finish()
    return manifest, load_clip(tmp_path)


def test_every_new_frame_is_one_line_with_the_sensors_beside_it(tmp_path: Path) -> None:
    runtime = _StubRuntime([(0.0, jpeg()), (0.2, jpeg())], every=2)
    runtime.context["sensor_reading"] = reading()
    runtime.context["tilt_warning"] = {"pitch": 1.5, "roll": -2.5}

    manifest, clip = _record(tmp_path, runtime, host={"node": "bench"}, commit="abc1234")

    assert runtime.started == 1 and runtime.stopped == 1
    assert manifest["frame_count"] == len(clip.frames) >= 2
    assert manifest["complete"] is True
    assert manifest["commit"] == "abc1234"
    assert manifest["host"] == {"node": "bench"}
    assert (manifest["width"], manifest["height"]) == (64, 48)
    assert clip.frames[0].ts == 0.0
    assert clip.frames[0].imu is not None and clip.frames[0].imu["acc"] == [0.0, 0.0, 9.81]
    assert clip.frames[0].attitude == {"pitch": 1.5, "roll": -2.5}
    assert abs(manifest["imu"]["acc_norm_mean"] - 9.81) < 1e-6
    assert manifest["imu"]["gyro_bias"] == [0.01, -0.02, 0.03]
    assert manifest["imu"]["samples"] == manifest["frame_count"]
    assert manifest["attitude"]["samples"] == manifest["frame_count"]
    assert manifest["fps"] > 0


def test_a_frame_served_twice_is_written_once(tmp_path: Path) -> None:
    runtime = _StubRuntime([(7.0, jpeg())], every=1)
    runtime.context["sensor_reading"] = reading()

    manifest, clip = _record(tmp_path, runtime)

    assert manifest["frame_count"] == 1
    assert len(clip.frames) == 1


def test_the_frame_budget_stops_the_run(tmp_path: Path) -> None:
    runtime = _StubRuntime([(0.0, jpeg()), (0.1, jpeg()), (0.2, jpeg())], every=1)

    manifest, _ = _record(tmp_path, runtime, seconds=60.0, max_frames=2)

    assert manifest["frame_count"] == 2
    assert runtime.stopped == 1


def test_a_missing_imu_is_recorded_as_missing_not_as_zero(tmp_path: Path) -> None:
    runtime = _StubRuntime([(0.0, jpeg())])
    runtime.context["sensor_reading"] = SensorReading(
        distance_cm=None,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=None,
        gyro=None,
        timestamp=None,
        distance_valid=False,
        touch_valid=False,
        sound_valid=False,
        imu_valid=False,
    )

    manifest, clip = _record(tmp_path, runtime)

    assert clip.frames[0].imu is not None
    assert clip.frames[0].imu["acc"] is None and clip.frames[0].imu["gyro"] is None
    assert clip.frames[0].imu["valid"] is False
    assert clip.frames[0].attitude is None
    assert manifest["imu"]["valid"] == 0
    assert manifest["imu"]["acc_norm_mean"] is None


def test_no_camera_means_no_clip_and_a_named_reason(tmp_path: Path, capsys: Any) -> None:
    out = tmp_path / "clip"

    code = camera_record.main(["--out", str(out), "--seconds", "0.2"], hal=FakeDogHAL())

    assert code == 1
    assert "no frames were published" in capsys.readouterr().err
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["frame_count"] == 0
    assert manifest["complete"] is True


def test_an_empty_frame_budget_is_refused_before_the_runtime_is_built(
    tmp_path: Path, capsys: Any
) -> None:
    out = tmp_path / "never"

    assert camera_record.main(["--out", str(out), "--frames", "0"]) == 2
    assert "--frames" in capsys.readouterr().err
    assert not out.exists()


def test_a_negative_duration_with_no_frame_budget_is_refused(capsys: Any) -> None:
    assert camera_record.main(["--seconds", "-1"]) == 2
    assert "--seconds" in capsys.readouterr().err
