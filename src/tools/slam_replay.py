"""Replay a recorded clip where the SLAM question has to be answered (plan S).

S1 lands the half that needs no dog and no SLAM library: `--verify` reads a clip written by
`tools/camera_record.py` and refuses it, by name, when it could not be replayed — a frame count the
manifest does not agree with, a line that is not a JPEG, a cadence that is not the one the manifest
promises. The host replay (`--host pi`, `--host pc`, `--host pi5`) is S2: it publishes the clip as
`vision_frame` and lets the real runtime with `slam_pi4` enabled consume it, which is the only way a
number includes the loop rather than a bare benchmark.

No pixels are decoded: dimensions come from the JPEG's own frame header
(`optional/slam_clip.py::jpeg_size`), so the check runs on any host, including one without OpenCV.
Nothing here moves the dog, and nothing here needs a camera.

    python -m tools.slam_replay --verify data/clips/room-01
    python -m tools.slam_replay --verify data/clips/room-01 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from houndmind_ai.optional.slam_clip import (
    Clip,
    ClipError,
    interval_stats,
    jpeg_size,
    load_clip,
)

# `src/tools/<name>.py` -> the repository root, so a relative clip path means what the recorder meant.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOLERANCE_PCT = 25.0


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay a recorded clip; --verify needs no dog, no camera and no SLAM library"
    )
    parser.add_argument("clip", type=str, help="clip directory written by tools.camera_record")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check the clip can be replayed (the host replay lands with S2)",
    )
    parser.add_argument(
        "--tolerance-pct",
        type=float,
        default=DEFAULT_TOLERANCE_PCT,
        help=f"Jitter and cadence tolerance in percent (default {DEFAULT_TOLERANCE_PCT:.0f})",
    )
    parser.add_argument("--json", action="store_true", help="Print the verdict as JSON only")
    args = parser.parse_args(argv)

    if args.tolerance_pct <= 0:
        print("[slam] --tolerance-pct must be positive", file=sys.stderr)
        return 2
    if not args.verify:
        print(
            "[slam] only --verify is implemented here; the host replay is segment S2",
            file=sys.stderr,
        )
        return 2

    try:
        clip = load_clip(_resolve(args.clip))
    except ClipError as exc:
        print(f"[slam] {exc}", file=sys.stderr)
        return 1

    report = verify(clip, args.tolerance_pct)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
