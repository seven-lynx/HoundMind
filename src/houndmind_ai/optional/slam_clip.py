"""One recorded clip that every host can replay (plan S, S1).

A SLAM verdict is only worth what the footage behind it is worth, and a Pi 4 number is only
comparable to a PC number if both replayed the *same bytes*. This module is the contract between
the recorder (`tools/camera_record.py`) and the replayer (`tools/slam_replay.py`): one
`clip.jsonl`, one line per frame, and one `manifest.json` that says what the numbers describe.

Nothing here imports `rtabmap`, `opencv` or `numpy` — the dimensions come from the JPEG's own SOF
marker, so a clip can be checked on any host, including the ones that cannot run the pipeline at
all. Layout, version 1:

    clip.jsonl     {"ts": float|null, "wall": float, "jpeg": "<base64>",
                    "imu": {"ts", "acc", "gyro", "valid"}|null,
                    "attitude": {"pitch": float, "roll": float}|null}
    manifest.json  {"format": "houndmind-clip", "version": 1, ...}

A frame is stored as the bytes the producer published (`services/camera.py::FRAME_KEY`), never
re-encoded: a replay that resized or re-compressed would be measuring a different picture.

A `null` `ts` is a producer that published bytes without a timestamp. The line is kept rather than
dropped, because dropping it would change the frame count this manifest promises.
"""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "Clip",
    "ClipError",
    "ClipFrame",
    "ClipWriter",
    "CLIP_FILE",
    "CLIP_FORMAT",
    "CLIP_VERSION",
    "MANIFEST_FILE",
    "interval_stats",
    "jpeg_size",
    "load_clip",
]

CLIP_FORMAT = "houndmind-clip"
CLIP_VERSION = 1
CLIP_FILE = "clip.jsonl"
MANIFEST_FILE = "manifest.json"

# SOFn: every frame header a JPEG can carry. C4, C8 and CC are not frame headers (DHT, JPG, DAC),
# and a scan (DA) has no dimensions behind it.
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


class ClipError(RuntimeError):
    """A clip that cannot be read as one. Named, because every caller prints the reason."""


def _number(value: Any) -> float | None:
    """A finite float or None. `bool` is not a number here, and NaN is a missing value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _triple(value: Any) -> list[float] | None:
    """Three finite floats, or None. A vendor tuple is the usual input."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    numbers = [_number(item) for item in value]
    if any(number is None for number in numbers):
        return None
    return [number for number in numbers if number is not None]


def _table(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def jpeg_size(data: bytes | bytearray) -> tuple[int, int] | None:
    """`(width, height)` from a JPEG's frame header, or None when this is not a JPEG.

    Parsed instead of decoded: the manifest promises a resolution, and checking that promise must
    not need OpenCV. Only the markers before the first scan are read, which is where the
    dimensions always are.
    """
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return None
    index = 2
    size = len(data)
    while index + 3 < size:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF:  # fill byte, not a marker
            index += 1
            continue
        if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xD9 or marker == 0xDA:  # end of image, or the scan started
            return None
        length = (data[index + 2] << 8) | data[index + 3]
        if length < 2:
            return None
        if marker in _SOF_MARKERS:
            if index + 8 >= size:
                return None
            height = (data[index + 5] << 8) | data[index + 6]
            width = (data[index + 7] << 8) | data[index + 8]
            if width <= 0 or height <= 0:
                return None
            return int(width), int(height)
        index += 2 + length
    return None


def interval_stats(values: Sequence[float | None]) -> dict[str, float]:
    """Intervals between consecutive timestamps, in milliseconds, summarised.

    Summarised rather than emitted: a 60 s clip at 5 fps would otherwise carry 300 numbers into
    every manifest and every report, and the question asked of them is only ever "how regular".
    """
    stamps = [value for value in values if value is not None]
    deltas = [
        (later - earlier) * 1000.0
        for earlier, later in zip(stamps, stamps[1:], strict=False)
        if later >= earlier
    ]
    if not deltas:
        return {"count": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0, "mean": 0.0}
    ordered = sorted(deltas)

    def pick(fraction: float) -> float:
        index = int(round(fraction * (len(ordered) - 1)))
        return ordered[max(0, min(len(ordered) - 1, index))]

    return {
        "count": float(len(deltas)),
        "p50": pick(0.50),
        "p95": pick(0.95),
        "max": max(ordered),
        "mean": sum(ordered) / len(ordered),
    }


@dataclass(frozen=True)
class ClipFrame:
    """One frame and the sensors that were read beside it."""

    ts: float | None
    wall: float | None
    jpeg: bytes
    imu: dict[str, Any] | None = None
    attitude: dict[str, Any] | None = None


@dataclass(frozen=True)
class Clip:
    """What `load_clip` hands back: the manifest as written, and every frame in order."""

    directory: Path
    manifest: dict[str, Any]
    frames: list[ClipFrame]


class ClipWriter:
    """Streams frames to `clip.jsonl`, then writes `manifest.json` from what actually arrived.

    Frames go out as they arrive, because a 60 s clip should not be held in memory twice; the
    manifest is computed at `finish()` from that same stream, so it cannot describe a clip that
    was not written.
    """

    def __init__(
        self,
        directory: Path | str,
        *,
        host: dict[str, Any] | None = None,
        commit: str | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / CLIP_FILE
        self.manifest_path = self.directory / MANIFEST_FILE
        self._handle = self.path.open("w", encoding="utf-8", newline="\n")
        self._host = dict(host or {})
        self._commit = commit
        self._count = 0
        self._stamps: list[float | None] = []
        self._size: tuple[int, int] | None = None
        self._conflicts = 0
        self._imu_samples = 0
        self._imu_valid = 0
        self._acc: list[list[float]] = []
        self._gyro: list[list[float]] = []
        self._attitude = 0
        self._notes: list[str] = []
        self._finished = False

    # ---- writing -----------------------------------------------------------

    def append(
        self,
        *,
        ts: float | None,
        wall: float | None,
        jpeg: bytes,
        imu: dict[str, Any] | None = None,
        attitude: dict[str, Any] | None = None,
    ) -> None:
        """Write one frame. Everything that crosses back out has already been coerced."""
        if self._finished:
            raise ClipError(f"{self.path} is already closed")
        size = jpeg_size(jpeg)
        if self._size is None:
            self._size = size
        elif size != self._size:
            self._conflicts += 1
        if ts is None and not self._notes:
            self._notes.append("the producer published no frame timestamps; cadence is unknown")
        self._stamps.append(ts)
        self._imu_samples += 1
        if imu:
            if imu.get("valid"):
                self._imu_valid += 1
            acc = _triple(imu.get("acc"))
            gyro = _triple(imu.get("gyro"))
            if acc is not None:
                self._acc.append(acc)
            if gyro is not None:
                self._gyro.append(gyro)
        if attitude:
            self._attitude += 1
        record = {
            "ts": ts,
            "wall": wall,
            "jpeg": base64.b64encode(jpeg).decode("ascii"),
            "imu": imu,
            "attitude": attitude,
        }
        self._handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._count += 1

    @property
    def count(self) -> int:
        return self._count

    # ---- closing -----------------------------------------------------------

    def finish(self, *, complete: bool = True) -> dict[str, Any]:
        """Close the file and write the manifest that describes what is on disk.

        `complete=False` is the honest manifest for an interrupted run: the frames written so far
        are still a clip and a reader may use them, but nothing may quote it as a whole run.
        """
        if self._finished:
            return dict(json.loads(self.manifest_path.read_text(encoding="utf-8")))
        self._finished = True
        self._handle.close()
        manifest = self.manifest()
        manifest["complete"] = bool(complete)
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest

    def manifest(self) -> dict[str, Any]:
        """The numbers a replayer needs, computed from the stream this writer saw."""
        stamps = [stamp for stamp in self._stamps if stamp is not None]
        duration = (stamps[-1] - stamps[0]) if len(stamps) >= 2 else 0.0
        fps = (len(stamps) - 1) / duration if duration > 0 else 0.0
        size = self._size
        return {
            "format": CLIP_FORMAT,
            "version": CLIP_VERSION,
            "encoding": "base64",
            "recorded_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "frame_count": self._count,
            "width": size[0] if size else None,
            "height": size[1] if size else None,
            "resolution_conflicts": self._conflicts,
            "duration_s": duration,
            "fps": fps,
            "interval_ms": interval_stats(self._stamps),
            "imu": {
                "samples": self._imu_samples,
                "valid": self._imu_valid,
                "acc_mean": _mean(self._acc),
                # The magnitude is the gravity check: ~9.8 m/s^2 is a clip that lay still, and a
                # reading far from it is one whose IMU cannot serve as a reference.
                "acc_norm_mean": _norm_mean(self._acc),
                "gyro_bias": _mean(self._gyro),
            },
            "attitude": {"samples": self._attitude},
            "host": self._host,
            "commit": self._commit,
            "notes": list(self._notes),
        }

    def __enter__(self) -> ClipWriter:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._finished:
            self.finish(complete=exc_type is None)


def _mean(rows: list[list[float]]) -> list[float] | None:
    if not rows:
        return None
    return [sum(column) / len(rows) for column in zip(*rows, strict=False)]


def _norm_mean(rows: list[list[float]]) -> float | None:
    if not rows:
        return None
    return sum(math.sqrt(sum(value * value for value in row)) for row in rows) / len(rows)


# ---- reading ---------------------------------------------------------------


def load_clip(directory: Path | str) -> Clip:
    """Read a clip, or refuse it with the reason. Never a partial clip that looks whole."""
    path = Path(directory)
    manifest_path = path / MANIFEST_FILE
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClipError(f"{manifest_path} is missing; this is not a clip directory") from exc
    except (OSError, ValueError) as exc:
        raise ClipError(f"{manifest_path} cannot be read: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ClipError(f"{manifest_path} is not an object")
    if manifest.get("format") != CLIP_FORMAT:
        raise ClipError(f"{manifest_path} is not a {CLIP_FORMAT} manifest")
    version = _number(manifest.get("version"))
    if version is None or int(version) != CLIP_VERSION:
        raise ClipError(
            f"{manifest_path} says version {manifest.get('version')}; this build reads {CLIP_VERSION}"
        )

    clip_path = path / CLIP_FILE
    frames: list[ClipFrame] = []
    try:
        handle = clip_path.open("r", encoding="utf-8")
    except FileNotFoundError as exc:
        raise ClipError(f"{clip_path} is missing; the manifest has no frames behind it") from exc
    except OSError as exc:
        raise ClipError(f"{clip_path} cannot be read: {exc}") from exc
    with handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except ValueError as exc:
                raise ClipError(f"{clip_path} line {number} is not JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ClipError(f"{clip_path} line {number} is not an object")
            encoded = record.get("jpeg")
            if not isinstance(encoded, str):
                raise ClipError(f"{clip_path} line {number} has no jpeg")
            try:
                jpeg = base64.b64decode(encoded.encode("ascii"), validate=True)
            except (ValueError, UnicodeEncodeError) as exc:
                raise ClipError(f"{clip_path} line {number} is not base64: {exc}") from exc
            frames.append(
                ClipFrame(
                    ts=_number(record.get("ts")),
                    wall=_number(record.get("wall")),
                    jpeg=jpeg,
                    imu=_table(record.get("imu")) or None,
                    attitude=_table(record.get("attitude")) or None,
                )
            )
    return Clip(directory=path, manifest=manifest, frames=frames)
