"""Replay a recorded clip where the SLAM question has to be answered (plan S).

`--verify` needs no dog, no camera and no SLAM library: it reads a clip written by
`tools/camera_record.py` and refuses it, by name, when it could not be replayed — a frame count the
manifest does not agree with, a line that is not a JPEG, a cadence that is not the one the manifest
promises.

`--host pi|pi5|pc` publishes that clip into the **real** runtime with `slam_pi4` switched on, so the
number includes the loop rather than a bare benchmark: a frame is set on the context when its own
recorded timestamp comes round, the loop keeps ticking at `loop.tick_hz` in between, and every
motion-capable module stays off — `hal_sensors` too, because the IMU has to come from the clip and
not from the dog it was recorded on. One JSON report is written per run: sustained fps, CPU per core,
temperature before and after, `slam_pi4`'s own tick percentiles, the ticks that overran the budget,
the frames the module buffered, processed, dropped or failed (`slam_stats`), and a verdict sentence.

No pixels are decoded by `--verify`: dimensions come from the JPEG's own frame header
(`optional/slam_clip.py::jpeg_size`), so the check runs on any host, including one without OpenCV.
The host replay hands the backend an array when OpenCV is present and the JPEG bytes when it is not,
and the report says which: a backend that cannot read the bytes processes nothing, which is a
finding rather than a crash.

Nothing here moves the dog, and nothing here needs a camera — the clip is the producer.

    python -m tools.slam_replay --verify data/clips/room-01
    python -m tools.slam_replay data/clips/room-01 --host pi --backend rtabmap
    python -m tools.slam_replay data/clips/room-01 --host pc --json
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from houndmind_ai.core.config import ModuleConfig, load_config
from houndmind_ai.core.instance import BusBusy, RunLock
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.main import build_modules
from houndmind_ai.optional.slam_clip import (
    Clip,
    ClipError,
    ClipFrame,
    interval_stats,
    jpeg_size,
    load_clip,
)
from tools.smoke_test import MOTIONLESS_MODULES

# `src/tools/<name>.py` -> the repository root, so a relative clip path means what the recorder meant.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOLERANCE_PCT = 25.0

# The label a report is filed under. It is a label, not a claim: the platform and machine travel with
# it, so a run that says `pi` on a Windows box is visible as one.
HOSTS = ("pi", "pi5", "pc")
REPORT_FORMAT = "houndmind-slam-replay"
REPORT_VERSION = 1

# The clip is the sensor source, so the modules that would publish frames or readings for real stay
# off; the motionless set covers everything that could move, and `api` would bind port 8420.
# `hal_sensors` is the one addition: leaving it on would overwrite the clip's IMU with the dog's on
# the tick before `slam_pi4` reads it, and a pose measured against live sensors is not a replay.
REPLAY_DISABLED = MOTIONLESS_MODULES | {"api", "hal_sensors"}



def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _resolve(text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else REPO_ROOT / path


def _deviation_p95(ordered: list[float], p50: float, fraction: float = 0.95) -> float:
    """p95 of each interval's distance from the median, as a percentage of that median.

    The median is the clip's own cadence, not the number the manifest claims: a recorder that ran
    at 4.9 fps and wrote `fps: 4.9` is regular, and only the *spread* says whether a replay can
    pace it.
    """
    if p50 <= 0 or len(ordered) < 3:
        return 0.0
    deviations = sorted(
        abs((later - earlier) * 1000.0 - p50) / p50 * 100.0
        for earlier, later in zip(ordered, ordered[1:], strict=False)
    )
    index = int(round(fraction * (len(deviations) - 1)))
    return deviations[max(0, min(len(deviations) - 1, index))]


def verify(clip: Clip, tolerance_pct: float = DEFAULT_TOLERANCE_PCT) -> dict[str, Any]:
    """Check that this clip can be replayed, and say what is wrong when it cannot.

    Every check answers "would S2 be measuring the clip, or an accident of it": the count is what
    the manifest promises, the header is what a replayer will open, the timestamps are the pacing,
    and the jitter is the tolerance the measurement will be quoted with.
    """
    manifest = clip.manifest
    frames = clip.frames
    problems: list[str] = []

    declared = _count(manifest.get("frame_count"))
    if declared is None:
        problems.append("manifest.json carries no frame_count")
    elif declared != len(frames):
        problems.append(f"manifest promises {declared} frame(s); clip.jsonl holds {len(frames)}")
    if not frames:
        problems.append("clip.jsonl holds no frames")
    if manifest.get("complete") is False:
        problems.append("the recorder closed this clip unfinished (complete: false)")

    sizes: dict[tuple[int, int], int] = {}
    not_jpeg: list[int] = []
    for index, frame in enumerate(frames):
        size = jpeg_size(frame.jpeg)
        if size is None:
            not_jpeg.append(index)
        else:
            sizes[size] = sizes.get(size, 0) + 1
    if not_jpeg:
        problems.append(f"{len(not_jpeg)} frame(s) are not JPEG, first at index {not_jpeg[0]}")
    if len(sizes) > 1:
        detail = ", ".join(
            f"{width}x{height} x{count}" for (width, height), count in sorted(sizes.items())
        )
        problems.append(f"frames disagree on resolution: {detail}")

    actual = next(iter(sizes), None)
    width = _count(manifest.get("width"))
    height = _count(manifest.get("height"))
    if actual is not None and (width, height) != actual:
        problems.append(f"manifest says {width}x{height}; the frames are {actual[0]}x{actual[1]}")

    stamps = [frame.ts for frame in frames]
    absent = sum(1 for stamp in stamps if stamp is None)
    if absent:
        problems.append(f"{absent} frame(s) carry no timestamp; a replay cannot pace them")
    ordered = [stamp for stamp in stamps if stamp is not None]
    backwards = [
        index
        for index, (earlier, later) in enumerate(zip(ordered, ordered[1:], strict=False))
        if later < earlier
    ]
    if backwards:
        problems.append(f"timestamps go backwards at frame {backwards[0] + 1}")
    if len(set(ordered)) != len(ordered):
        problems.append("two frames share a timestamp; a replay cannot pace them apart")

    stats = interval_stats(stamps)
    jitter = _deviation_p95(ordered, stats["p50"])
    if jitter > tolerance_pct:
        problems.append(
            f"inter-frame jitter p95 {jitter:.1f}% is past the {tolerance_pct:.0f}% tolerance"
        )
    raw_fps = manifest.get("fps")
    fps = float(raw_fps) if isinstance(raw_fps, (int, float)) and not isinstance(raw_fps, bool) else 0.0
    nominal_ms = 1000.0 / fps if fps > 0 else 0.0
    if nominal_ms > 0 and stats["p50"] > 0:
        drift = abs(stats["p50"] - nominal_ms) / nominal_ms * 100.0
        if drift > tolerance_pct:
            problems.append(
                f"cadence p50 {stats['p50']:.1f} ms is {drift:.0f}% away from the manifest's "
                f"{nominal_ms:.1f} ms ({fps:.2f} fps)"
            )

    raw_imu = manifest.get("imu")
    imu = raw_imu if isinstance(raw_imu, dict) else {}
    raw_host = manifest.get("host")
    host = raw_host.get("node") if isinstance(raw_host, dict) else None
    return {
        "clip": str(clip.directory),
        "verdict": "fail" if problems else "pass",
        "frames": len(frames),
        "manifest_frames": declared,
        "resolution": list(actual) if actual else None,
        "fps": fps,
        "duration_s": float(manifest.get("duration_s") or 0.0),
        "timing": {
            "p50_ms": stats["p50"],
            "p95_ms": stats["p95"],
            "max_ms": stats["max"],
            "jitter_p95_pct": jitter,
            "tolerance_pct": float(tolerance_pct),
        },
        "imu": {"samples": imu.get("samples"), "valid": imu.get("valid")},
        "commit": manifest.get("commit"),
        "host": host,
        "problems": problems,
    }


# ---- host replay (S2) ------------------------------------------------------


def _finite(value: Any) -> float | None:
    """A finite float or None: these values cross a clip-file boundary in both directions."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _triple(value: Any) -> tuple[float, float, float] | None:
    """Three finite floats, or None. A recorded IMU triple is the usual input."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    first, second, third = (_finite(item) for item in value)
    if first is None or second is None or third is None:
        return None
    return (first, second, third)


def _reading(frame: ClipFrame) -> SensorReading:
    """The sensors the clip recorded, in the shape `hal_sensors` publishes.

    Distance and sound were never recorded, so they are invalid rather than zero: an unavailable
    reading is not a clear path. The timestamp is the frame's own clock, and 0.0 is only the
    placeholder `SensorReading` demands for a frame that was recorded without one.
    """
    imu = frame.imu if isinstance(frame.imu, dict) else {}
    acc = _triple(imu.get("acc"))
    gyro = _triple(imu.get("gyro"))
    return SensorReading(
        distance_cm=None,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=acc,
        gyro=gyro,
        timestamp=frame.ts if frame.ts is not None else 0.0,
        distance_valid=False,
        touch_valid=False,
        sound_valid=False,
        imu_valid=bool(imu.get("valid")) and acc is not None,
    )


def _decode(jpeg: bytes) -> tuple[Any, str]:
    """The frame the loop expects: an array when OpenCV is here, the JPEG bytes when it is not.

    Decoded one frame at a time and never kept: a 60 s clip is 300 frames, and holding them all
    decoded is ~270 MB at 640x480 — most of a Pi 4's headroom before the backend has done any work.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return jpeg, "jpeg"
    array = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if array is None:
        return jpeg, "jpeg"
    return array, "bgr"


def _offset(frame: ClipFrame, first: float | None, index: int, period: float) -> float:
    """Where this frame belongs on the replay clock, in seconds from the first frame.

    The clip's own timestamps are the cadence; a clip recorded without them falls back to one loop
    period per frame, and the report carries a note so that pace is not mistaken for a measured one.
    """
    if frame.ts is None or first is None:
        return index * period
    return max(0.0, frame.ts - first)


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile: the answer is one of the measurements, not an interpolation."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = int(round(fraction * (len(ordered) - 1)))
    return ordered[max(0, min(len(ordered) - 1, index))]


def _summary(values: list[float]) -> dict[str, Any]:
    return {
        "samples": len(values),
        "p50_ms": _percentile(values, 0.50) * 1000.0,
        "p95_ms": _percentile(values, 0.95) * 1000.0,
        "max_ms": _percentile(values, 1.0) * 1000.0,
    }


def _temperature() -> float | None:
    """The SoC's own sensor in degrees Celsius, or None on a host that has no thermal zone."""
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    # Every Pi reports millidegrees; a host that already reports Celsius is left alone.
    return value / 1000.0 if value > 200.0 else value


def _cpu_times() -> list[tuple[float, float]] | None:
    """Busy and total jiffies per core from `/proc/stat`, or None where there is no `/proc`."""
    try:
        text = Path("/proc/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    rows: list[tuple[float, float]] = []
    for line in text.splitlines():
        parts = line.split()
        if not parts or len(parts[0]) < 4 or not parts[0].startswith("cpu"):
            continue
        if parts[0] == "cpu":
            continue  # the aggregate line; per-core is the question
        try:
            values = [float(value) for value in parts[1:]]
        except ValueError:
            return None
        if len(values) < 4:
            return None
        # Field 4 is idle, field 5 iowait; both are time the core was not doing our work.
        idle = values[3] + (values[4] if len(values) > 4 else 0.0)
        rows.append((sum(values) - idle, sum(values)))
    return rows or None


def _cpu_delta(
    before: list[tuple[float, float]] | None, after: list[tuple[float, float]] | None
) -> list[float] | None:
    """Busy percentage per core between two samples, or None when a sample is missing."""
    if before is None or after is None or len(before) != len(after) or not before:
        return None
    per_core: list[float] = []
    for (busy_before, total_before), (busy_after, total_after) in zip(before, after, strict=True):
        total = total_after - total_before
        if total <= 0:
            per_core.append(0.0)
            continue
        per_core.append(max(0.0, min(100.0, (busy_after - busy_before) / total * 100.0)))
    return per_core


def _enable_slam(config: Any, backend: str | None) -> str:
    """Turn `slam_pi4` on for this run and return the backend it was asked for.

    The module ships off, because its backend is not installable from PyPI (#181), and a replay
    that left it off would measure the loop and nothing else. Enabling it is the whole point of
    the run; every motion-capable module is still off, and the report names the ones that were.
    """
    settings = config.settings.get("slam_pi4")
    if not isinstance(settings, dict):
        settings = {}
        config.settings["slam_pi4"] = settings
    chosen = backend or str(settings.get("backend") or "stub")
    settings["backend"] = chosen
    settings["enabled"] = True
    entry = config.modules.get("slam_pi4")
    if entry is None:
        config.modules["slam_pi4"] = ModuleConfig(enabled=True)
    else:
        entry.enabled = True
    return chosen


def _disable(config: Any, names: frozenset[str]) -> tuple[list[str], list[str]]:
    """Switch off every named module, and report the names this config does not declare.

    The second list is `tools/smoke_test.py`'s lesson (#205): the set is a copy of the registry, so a
    renamed module has to show up in the report instead of leaving a motor or a camera running behind
    a printed list of things that were never touched.
    """
    disabled: list[str] = []
    missing: list[str] = []
    modules = config.modules or {}
    for name in sorted(names):
        entry = modules.get(name)
        if entry is None or not hasattr(entry, "enabled"):
            missing.append(name)
            continue
        entry.enabled = False
        disabled.append(name)
    return disabled, missing

def _print_report(report: dict[str, Any]) -> None:
    timing = report["timing"]
    resolution = report["resolution"]
    picture = f"{resolution[0]}x{resolution[1]}" if resolution else "unknown"
    imu = report["imu"]
    print(f"clip:      {report['clip']}")
    print(
        f"manifest:  commit {report['commit'] or 'unknown'} on {report['host'] or 'unknown'}, "
        f"{report['fps']:.2f} fps"
    )
    print(f"frames:    {report['frames']} (manifest says {report['manifest_frames']})")
    print(f"picture:   {picture}")
    print(
        f"cadence:   p50 {timing['p50_ms']:.1f} ms  p95 {timing['p95_ms']:.1f} ms  "
        f"max {timing['max_ms']:.1f} ms over {report['duration_s']:.1f} s"
    )
    print(
        f"jitter:    p95 {timing['jitter_p95_pct']:.1f}% of p50 "
        f"(tolerance {timing['tolerance_pct']:.0f}%)"
    )
    print(f"imu:       {imu['samples']} sample(s), {imu['valid']} valid")
    for problem in report["problems"]:
        print(f"problem:   {problem}")
    print("PASS" if report["verdict"] == "pass" else "FAIL")


def replay_loop(
    runtime: Any,
    clip: Clip,
    *,
    tick_hz: int,
    speed: float = 1.0,
    max_frames: int | None = None,
    drain_s: float = 1.0,
    now: Any = time.monotonic,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """Feed the clip to the running loop, and measure what the loop and `slam_pi4` did with it.

    The clock and the sleep are parameters for the same reason `camera_record.record_loop` takes
    them: the honest test runs on a workstation with no camera and no clip of real footage, and a
    test that waited out sixty real seconds would not run in CI.

    The pacing is the clip's, not the loop's. `vision_pi4` publishes when it captures, so a frame is
    set on the context when its own recorded timestamp comes round and the loop keeps ticking at
    `tick_hz` in between — which is what makes an overrun count mean something. `speed` above 1
    compresses the clip; it does not slow the loop down, so a compressed run is a *harder* test of
    the tick budget, and the report says which speed produced it.
    """
    frames = clip.frames if max_frames is None else clip.frames[:max_frames]
    if not frames:
        raise ClipError("this clip holds no frames to replay")
    context = runtime.context
    period = 1.0 / max(1, int(tick_hz))
    pace = max(0.01, float(speed))
    first = frames[0].ts
    index = 0
    delivered = 0
    encoding = "none"
    tick_times: list[float] = []
    slam_times: list[float] = []
    overruns = 0
    slam_overruns = 0
    drain_until: float | None = None

    runtime.start()
    # The replay clock starts when the loop is ready: module start-up (a calibration sweep, a lazy
    # import) would otherwise count as clip time and burst every frame at once, which is a finished
    # run pretending to be a measurement.
    start = now()
    # Read the roster before `stop()`: stopping a module clears its `started` flag, and a report that
    # cannot say which modules ran cannot be compared with the next host's.
    started = [module.name for module in runtime.modules if module.status.started]
    try:
        while True:
            elapsed = (now() - start) * pace
            # At most one frame per tick: a frame published and replaced inside the same tick was
            # never visible to the loop, and a replay that hides frames from the consumer is not a
            # replay. When the clip outruns the loop, the remaining frames go out one per tick.
            if index < len(frames) and _offset(frames[index], first, index, period) <= elapsed:
                payload, encoding = _decode(frames[index].jpeg)
                context.set("vision_frame", payload)
                context.set("vision_frame_ts", time.time())
                context.set("sensor_reading", _reading(frames[index]))
                index += 1
                delivered += 1
            began = now()
            runtime.tick()
            cost = now() - began
            tick_times.append(cost)
            if cost > period:
                overruns += 1
            raw = context.get("module_tick_durations")
            durations = raw if isinstance(raw, dict) else {}
            slam = _finite(durations.get("slam_pi4"))
            if slam is not None:
                slam_times.append(slam)
                if slam > period:
                    slam_overruns += 1
            if index >= len(frames):
                # The tick above consumed the last frame; keep the loop turning long enough for a
                # buffered frame to be processed, then stop rather than idle forever.
                if drain_until is None:
                    drain_until = now() + max(0.0, float(drain_s))
                if now() >= drain_until:
                    break
            remaining = period - cost
            if remaining > 0:
                sleep(remaining)
    finally:
        runtime.stop()

    stats = context.get("slam_stats")
    status = context.get("slam_status")
    return {
        "frames_delivered": delivered,
        "encoding": encoding,
        "ticks": len(tick_times),
        "tick_hz": max(1, int(tick_hz)),
        "wall_s": max(0.0, now() - start),
        "tick": _summary(tick_times),
        "overruns": overruns,
        "slam_pi4": {**_summary(slam_times), "overruns": slam_overruns},
        "slam_stats": dict(stats) if isinstance(stats, dict) else None,
        "slam_status": dict(status) if isinstance(status, dict) else None,
        "started": started,
    }


def _verdict(report: dict[str, Any]) -> str:
    """One sentence a human can quote: what held, what did not, and how much of the clip was seen."""
    loop = report["loop"]
    frames = report["frames"]
    stats = frames.get("slam") or {}
    delivered = frames["delivered"]
    processed = stats.get("frames_processed")
    seen = stats.get("frames_in")
    parts: list[str] = []
    budget = 1000.0 / max(1, loop["tick_hz"])
    if loop["overruns"] == 0:
        parts.append(
            f"held the {loop['tick_hz']} Hz loop ({loop['ticks']} tick(s), p95 "
            f"{loop['p95_ms']:.1f} ms against a {budget:.0f} ms budget)"
        )
    else:
        parts.append(
            f"overran the {loop['tick_hz']} Hz loop on {loop['overruns']} of {loop['ticks']} tick(s) "
            f"(max {loop['max_ms']:.1f} ms against a {budget:.0f} ms budget)"
        )
    status = report.get("slam_status") or {}
    actual = status.get("backend")
    if processed is None:
        parts.append("published no frame counters, so the track could not be judged")
    elif not processed:
        parts.append(
            f"processed none of the {delivered} frame(s) delivered"
            + (f" (backend `{actual}`)" if actual else "")
        )
    else:
        share = f" ({processed / seen * 100.0:.0f}% of the {seen} it buffered)" if seen else ""
        parts.append(f"processed {processed} frame(s){share} from {delivered} delivered")
    if stats.get("frames_dropped"):
        parts.append(f"{stats['frames_dropped']} aged out of the buffer")
    if stats.get("frames_failed"):
        parts.append(f"{stats['frames_failed']} were refused by the adapter")
    if stats.get("frames_skipped"):
        parts.append(f"{stats['frames_skipped']} due tick(s) had no new frame")
    change = report["temperature_c"].get("change_c")
    if change is not None:
        parts.append(f"the SoC moved {change:+.1f} C")
    return f"{report['backend']} on the {report['host']['label']} host: " + "; ".join(parts) + "."


def _build_report(
    clip: Clip,
    *,
    host: str,
    backend: str,
    result: dict[str, Any],
    temperature: dict[str, float | None],
    cpu: dict[str, Any],
    disabled: list[str],
    missing: list[str],
    notes: list[str],
    speed: float,
) -> dict[str, Any]:
    """The one JSON document a table row is quoted from."""
    tick = result["tick"]
    slam = result["slam_pi4"]
    delivered = result["frames_delivered"]
    wall = float(result["wall_s"])
    manifest = clip.manifest
    raw_host = manifest.get("host")
    recorded_on = raw_host.get("node") if isinstance(raw_host, dict) else None
    report: dict[str, Any] = {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "measured_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": {
            "label": host,
            "node": platform.node(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "clip": {
            "path": str(clip.directory),
            "frames": len(clip.frames),
            "width": manifest.get("width"),
            "height": manifest.get("height"),
            "fps": manifest.get("fps"),
            "duration_s": manifest.get("duration_s"),
            "commit": manifest.get("commit"),
            "recorded_on": recorded_on,
        },
        "backend": backend,
        "slam_status": result.get("slam_status"),
        "frame_encoding": result["encoding"],
        "speed": speed,
        "frames": {"delivered": delivered, "slam": result.get("slam_stats")},
        "replay": {
            "ticks": result["ticks"],
            "wall_s": wall,
            "fps": (delivered / wall) if wall > 0 else None,
        },
        "loop": {
            "tick_hz": result["tick_hz"],
            "ticks": result["ticks"],
            "samples": tick["samples"],
            "p50_ms": tick["p50_ms"],
            "p95_ms": tick["p95_ms"],
            "max_ms": tick["max_ms"],
            "overruns": result["overruns"],
        },
        "slam_pi4": {
            "samples": slam["samples"],
            "p50_ms": slam["p50_ms"],
            "p95_ms": slam["p95_ms"],
            "max_ms": slam["max_ms"],
            "overruns": slam["overruns"],
        },
        "cpu": cpu,
        "temperature_c": temperature,
        "started": result["started"],
        "disabled": disabled,
        "not_declared": missing,
        "notes": notes,
        "verdict": "",
    }
    report["verdict"] = _verdict(report)
    return report


def run_replay(
    config: Any,
    clip: Clip,
    *,
    host: str,
    backend: str | None = None,
    speed: float = 1.0,
    max_frames: int | None = None,
    drain_s: float = 1.0,
    hal: DogHAL | None = None,
    now: Any = time.monotonic,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """Build the real runtime, replay the clip into it, and return the report.

    `hal` is the test seam, exactly as in `tools/camera_record.py`: a caller that hands in a fake owns
    nothing on the servo bus, and the CLI takes the one-instance lock only when it has no fake.
    """
    chosen = _enable_slam(config, backend)
    disabled, missing = _disable(config, REPLAY_DISABLED)

    temperature_before = _temperature()
    cpu_before = _cpu_times()
    process_before = time.process_time()
    started_wall = now()

    runtime = HoundMindRuntime(config, build_modules(config, hal=hal))
    result = replay_loop(
        runtime,
        clip,
        tick_hz=config.loop.tick_hz,
        speed=speed,
        max_frames=max_frames,
        drain_s=drain_s,
        now=now,
        sleep=sleep,
    )

    wall = max(0.0, now() - started_wall)
    process_pct = (time.process_time() - process_before) / wall * 100.0 if wall > 0 else None
    temperature_after = _temperature()
    per_core = _cpu_delta(cpu_before, _cpu_times())
    cpu = {
        "sampled_s": wall,
        "per_core_pct": per_core,
        "cores": len(per_core) if per_core else None,
        "process_pct": process_pct,
        "available": per_core is not None,
    }
    change = (
        temperature_after - temperature_before
        if temperature_before is not None and temperature_after is not None
        else None
    )
    temperature = {
        "before": temperature_before,
        "after": temperature_after,
        "change_c": change,
    }

    notes: list[str] = []
    if host.startswith("pi") and not sys.platform.startswith("linux"):
        notes.append(
            f"the report says `{host}` but this is {sys.platform}; the numbers are this machine's"
        )
    if result["encoding"] == "jpeg":
        notes.append(
            "OpenCV is absent or could not decode the frame, so the backend was handed JPEG bytes: "
            "a backend that needs an array will process nothing"
        )
    status = result.get("slam_status")
    actual = status.get("backend") if isinstance(status, dict) else None
    if actual and actual != chosen:
        notes.append(f"asked for backend `{chosen}`; slam_pi4 started `{actual}`")
    if any(frame.ts is None for frame in clip.frames):
        notes.append("some frames carry no timestamp; their pace is the loop period, not a cadence")

    return _build_report(
        clip,
        host=host,
        backend=chosen,
        result=result,
        temperature=temperature,
        cpu=cpu,
        disabled=disabled,
        missing=missing,
        notes=notes,
        speed=speed,
    )


def _print_replay(report: dict[str, Any]) -> None:
    clip = report["clip"]
    picture = (
        f"{clip['width']}x{clip['height']}"
        if clip.get("width") and clip.get("height")
        else "unknown"
    )
    print(
        f"[replay] clip {clip['path']}: {clip['frames']} frame(s), {picture}, "
        f"commit {clip['commit'] or 'unknown'} recorded on {clip['recorded_on'] or 'unknown'}"
    )
    host = report["host"]
    print(f"[replay] host {host['label']} — {host['platform']}, python {host['python']}")
    status = report.get("slam_status") or {}
    print(
        f"[replay] backend {report['backend']} ({status.get('backend', 'no status')}), "
        f"frames as {report['frame_encoding']}, speed {report['speed']:g}x"
    )
    loop = report["loop"]
    print(
        f"[replay] loop {loop['tick_hz']} Hz: {loop['ticks']} tick(s), p50 {loop['p50_ms']:.3f} ms "
        f"p95 {loop['p95_ms']:.3f} ms max {loop['max_ms']:.3f} ms, overruns {loop['overruns']}"
    )
    slam = report["slam_pi4"]
    print(
        f"[replay] slam_pi4: {slam['samples']} sample(s), p50 {slam['p50_ms']:.3f} ms "
        f"p95 {slam['p95_ms']:.3f} ms max {slam['max_ms']:.3f} ms, overruns {slam['overruns']}"
    )
    frames = report["frames"]
    stats = frames["slam"] or {}

    def count(key: str) -> str:
        value = stats.get(key)
        return "n/a" if value is None else str(value)

    print(
        f"[replay] frames: {frames['delivered']} delivered, {count('frames_in')} buffered, "
        f"{count('frames_processed')} processed, {count('frames_skipped')} skipped (no new frame), "
        f"{count('frames_dropped')} dropped, {count('frames_failed')} failed"
    )
    cpu = report["cpu"]
    per_core = cpu["per_core_pct"]
    cores = ", ".join(f"{value:.0f}%" for value in per_core) if per_core else "unavailable"
    process = f"{cpu['process_pct']:.0f}%" if cpu["process_pct"] is not None else "unavailable"
    print(f"[replay] cpu: process {process}; per core [{cores}]")
    temps = report["temperature_c"]

    def degrees(value: float | None) -> str:
        return "unavailable" if value is None else f"{value:.1f} C"

    print(f"[replay] temperature: {degrees(temps['before'])} -> {degrees(temps['after'])}")
    for note in report["notes"]:
        print(f"[replay] note: {note}")
    if report["disabled"]:
        print(f"[replay] disabled: {', '.join(report['disabled'])}")
    if report["not_declared"]:
        print(f"[replay] not declared by this config: {', '.join(report['not_declared'])}")
    print(f"[replay] verdict: {report['verdict']}")


def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a recorded clip; --verify needs no dog and no SLAM library, --host runs the "
            "clip through the real loop"
        )
    )
    parser.add_argument("clip", type=str, help="clip directory written by tools.camera_record")
    parser.add_argument("--verify", action="store_true", help="Check the clip can be replayed")
    parser.add_argument(
        "--host",
        choices=HOSTS,
        default=None,
        help="Replay the clip inside the real runtime, and label the report with this host",
    )
    parser.add_argument(
        "--backend", default=None, help="slam_pi4 backend for this run (default: the config's)"
    )
    parser.add_argument(
        "--speed", type=float, default=1.0, help="Replay speed; 2 plays a 60 s clip in 30 s"
    )
    parser.add_argument(
        "--max-frames", type=int, default=None, help="Replay only the first N frames"
    )
    parser.add_argument(
        "--drain-s",
        type=float,
        default=1.0,
        help="Keep ticking this long after the last frame, so a buffered frame is processed",
    )
    parser.add_argument(
        "--tick-hz", type=int, default=None, help="Override loop.tick_hz for this run"
    )
    parser.add_argument("--config", type=str, default=None, help="Path to settings.jsonc")
    parser.add_argument(
        "--out", type=str, default=None, help="Report path (default: beside the clip)"
    )
    parser.add_argument(
        "--tolerance-pct",
        type=float,
        default=DEFAULT_TOLERANCE_PCT,
        help=f"Jitter and cadence tolerance in percent (default {DEFAULT_TOLERANCE_PCT:.0f})",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON only")
    args = parser.parse_args(argv)

    if args.verify and args.host is not None:
        print("[slam] --verify and --host are different runs; give one of them", file=sys.stderr)
        return 2
    if not args.verify and args.host is None:
        print(
            "[slam] give --verify to check a clip, or --host pi|pi5|pc to replay it",
            file=sys.stderr,
        )
        return 2
    if args.tolerance_pct <= 0:
        print("[slam] --tolerance-pct must be positive", file=sys.stderr)
        return 2
    if args.speed <= 0:
        print("[slam] --speed must be positive", file=sys.stderr)
        return 2
    if args.max_frames is not None and args.max_frames < 1:
        print("[slam] --max-frames must be at least 1", file=sys.stderr)
        return 2
    if args.drain_s < 0:
        print("[slam] --drain-s cannot be negative", file=sys.stderr)
        return 2

    try:
        clip = load_clip(_resolve(args.clip))
    except ClipError as exc:
        print(f"[slam] {exc}", file=sys.stderr)
        return 1

    if args.verify:
        report = verify(clip, args.tolerance_pct)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            _print_report(report)
        return 0 if report["verdict"] == "pass" else 1

    config = load_config(args.config)
    if args.tick_hz is not None:
        config.loop.tick_hz = max(1, int(args.tick_hz))

    # A run against the real dog opens the camera through the vision modules and owns the servo bus,
    # so it takes the lock. A run handed a fake HAL owns nothing and must not touch the home
    # directory (`tests`).
    lock: RunLock | None = None
    if hal is None:
        lock = RunLock()
        try:
            lock.acquire("slam_replay")
        except BusBusy as exc:
            print(f"[slam] {exc}", file=sys.stderr)
            print("[slam] stop it first: systemctl stop houndmind", file=sys.stderr)
            return 3

    try:
        report = run_replay(
            config,
            clip,
            host=args.host,
            backend=args.backend,
            speed=args.speed,
            max_frames=args.max_frames,
            drain_s=args.drain_s,
            hal=hal,
        )
    finally:
        if lock is not None:
            lock.release()

    out = (
        _resolve(args.out)
        if args.out
        else clip.directory / f"replay-{args.host}-{report['backend']}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_replay(report)
        print(f"[replay] report: {out}")
    if not report["frames"]["delivered"]:
        print("[slam] no frame was delivered; nothing was measured", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
