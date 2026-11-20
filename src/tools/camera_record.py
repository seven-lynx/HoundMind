"""Record one clip every host can replay (plan S, S1).

The clip is the dataset every later SLAM claim is measured on, so this tool records and does
nothing else: it borrows the frame `services/camera.py` already holds (`FRAME_KEY`) instead of
opening the camera a second time, pairs it with the sensor snapshot the HAL already publishes, and
writes the pair. No SLAM, no servo, no decision — the module set below is switched off for exactly
that reason, and it is `tools/smoke_test.py`'s motionless set minus the camera itself.

Why in-process and not over HTTP: the two camera routes mint a ticket (`services/api.py:2700`), so a
client would need the device token and a ticket to read bytes this process already has in memory.
The runtime is started here, motion-capable modules are disabled first, and the one-instance lock
is taken (`core/instance.py`) so a run cannot fight `houndmind.service` over the servo bus.

    python -m tools.camera_record --seconds 60 --out data/clips/room-01   # on the dog
    python -m tools.camera_record --seconds 5 --frames 20 --out /tmp/clip # a short check

The clip is `clip.jsonl` + `manifest.json` (`optional/slam_clip.py`); `tools.slam_replay --verify`
is what decides whether it is a clip that can be replayed.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from houndmind_ai.core.config import load_config
from houndmind_ai.core.instance import BusBusy, RunLock
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.main import build_modules
from houndmind_ai.optional.slam_clip import ClipWriter
from houndmind_ai.services.camera import FRAME_KEY, FRAME_TS_KEY
from tools.smoke_test import MOTIONLESS_MODULES

# `src/tools/<name>.py` -> the repository root, so a relative `--out` means what the runtime means.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = "data/clips"

# The camera is the one thing this run exists for, so it stays on; everything else smoke_test
# switches off stays off. `vision_pi4` is the module that actually publishes `vision_frame_jpeg`
# on a Pi 4 (#205), and `vision` is the Vilib path on the Pi 3.
CAMERA_MODULES = frozenset({"vision", "vision_pi4"})
# `api` is not in the motionless set, and binding port 8420 during a recording is the one thing a
# local tool must never do (`tools/bench_tick.py` makes the same call for its own reasons).
RECORD_DISABLED = (MOTIONLESS_MODULES - CAMERA_MODULES) | {"api"}

_MISSING = object()


def _number(value: Any) -> float | None:
    """A finite float or None: the frame timestamp crosses a producer boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _resolve(text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else REPO_ROOT / path


def _disable(config: Any) -> tuple[list[str], list[str]]:
    """Switch off everything that can move or listen, and report the names the config lacks.

    The second list is `tools/smoke_test.py`'s lesson (#205): `RECORD_DISABLED` is a copy of the
    registry, so a renamed module must show up in the report rather than leave a camera or a motor
    running behind a printed list of things that were never touched.
    """
    disabled: list[str] = []
    missing: list[str] = []
    modules = config.modules
    for name in sorted(RECORD_DISABLED):
        entry = modules.get(name)
        if entry is None or not hasattr(entry, "enabled"):
            missing.append(name)
            continue
        entry.enabled = False
        disabled.append(name)
    return disabled, missing


def _imu(context: Any) -> dict[str, Any]:
    """The IMU as the HAL last published it, with its own validity flag.

    `None` for a value the reading does not carry: a gyro the dog never reported is not a zero, and
    a clip whose IMU reads zero everywhere would make every dead-reckoned pose look still.
    """
    reading = context.get("sensor_reading")
    acc = getattr(reading, "acc", None)
    gyro = getattr(reading, "gyro", None)
    return {
        "ts": _number(getattr(reading, "timestamp", None)),
        "acc": list(acc) if isinstance(acc, (tuple, list)) and len(acc) == 3 else None,
        "gyro": list(gyro) if isinstance(gyro, (tuple, list)) and len(gyro) == 3 else None,
        "valid": bool(getattr(reading, "imu_valid", False)),
    }


def _attitude(context: Any) -> dict[str, float] | None:
    """Pitch and roll in degrees, or None. `safety` ships disabled, so this is usually absent."""
    table = context.get("tilt_warning")
    if not isinstance(table, dict):
        return None
    pitch = _number(table.get("pitch"))
    roll = _number(table.get("roll"))
    if pitch is None or roll is None:
        return None
    return {"pitch": pitch, "roll": roll}


class _FrameGate:
    """One line per *new* frame: a producer serves the same JPEG until it captures again.

    `services/camera.py::CameraService.stream` dedupes on exactly this identity, so two ticks over
    one frame must not become two frames in the clip — the cadence in the manifest is what every
    later measurement is divided by.
    """

    def __init__(self) -> None:
        self._ts: object = _MISSING
        self._data: bytes | None = None

    def accept(self, data: bytes | None, ts: float | None) -> bool:
        if not data:
            return False
        if ts is not None:
            if ts == self._ts:
                return False
        elif data == self._data:
            return False
        self._ts = ts
        self._data = data
        return True


def record_loop(
    runtime: Any,
    writer: ClipWriter,
    *,
    seconds: float,
    tick_hz: int,
    max_frames: int | None = None,
    now: Any = time.monotonic,
    sleep: Any = time.sleep,
    wall: Any = time.time,
) -> dict[str, int]:
    """Tick the real runtime and write every new frame until the time or the frame budget runs out.

    The clock and the sleep are parameters because the honest test for this lives on a workstation
    with no camera: a clip of synthetic frames over a stubbed runtime must produce the same file the
    dog would, and a test that waits sixty real seconds would not run in CI.
    """
    context = runtime.context
    gate = _FrameGate()
    period = 1.0 / max(1, int(tick_hz))
    ticks = 0
    deadline = now() + max(0.0, seconds)
    runtime.start()
    try:
        while now() < deadline:
            started = now()
            runtime.tick()
            ticks += 1
            data = context.get(FRAME_KEY)
            ts = _number(context.get(FRAME_TS_KEY))
            frame = bytes(data) if isinstance(data, (bytes, bytearray)) else None
            if gate.accept(frame, ts):
                writer.append(
                    ts=ts,
                    wall=wall(),
                    jpeg=frame or b"",
                    imu=_imu(context),
                    attitude=_attitude(context),
                )
                if max_frames is not None and writer.count >= max_frames:
                    break
            remaining = period - (now() - started)
            if remaining > 0:
                sleep(remaining)
    finally:
        runtime.stop()
    return {"ticks": ticks, "frames": writer.count}


def _host_block() -> dict[str, str]:
    """Who recorded it. `platform.node()` is what tells the Pi 4 row from the PC row in a table."""
    return {
        "node": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


def _commit() -> str | None:
    """The commit under test, or None when this is not a checkout. A number needs its tree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text or None


def _report(manifest: dict[str, Any], path: Path) -> None:
    imu = manifest.get("imu") or {}
    acc_norm = imu.get("acc_norm_mean")
    gyro = imu.get("gyro_bias")
    print(f"[clip] {manifest['frame_count']} frame(s) in {manifest['duration_s']:.1f} s -> {path}")
    print(
        f"[clip] picture {manifest['width']}x{manifest['height']}, {manifest['fps']:.2f} fps, "
        f"interval p50 {manifest['interval_ms']['p50']:.0f} ms p95 {manifest['interval_ms']['p95']:.0f} ms"
    )
    magnitude = f"{acc_norm:.2f}" if isinstance(acc_norm, (int, float)) else "absent"
    bias = (
        "[" + ", ".join(f"{value:+.3f}" for value in gyro) + "]"
        if isinstance(gyro, list)
        else "absent"
    )
    print(f"[clip] |acc| {magnitude} m/s^2, gyro bias {bias}, imu valid {imu.get('valid', 0)}/{imu.get('samples', 0)}")
    print(f"[clip] commit {manifest.get('commit') or 'unknown'} on {manifest['host'].get('node', 'unknown')}")
    for note in manifest.get("notes") or []:
        print(f"[clip] note: {note}")
    print(f"[clip] verify: python -m tools.slam_replay --verify {path}")


def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a replayable camera clip (never moves the dog, never listens)"
    )
    parser.add_argument(
        "--out", type=str, default=DEFAULT_OUT, help=f"clip directory (default {DEFAULT_OUT})"
    )
    parser.add_argument("--seconds", type=float, default=60.0, help="Recording length (default 60)")
    parser.add_argument(
        "--frames", type=int, default=None, help="Stop after N frames, whichever comes first"
    )
    parser.add_argument(
        "--tick-hz", type=int, default=None, help="Override loop.tick_hz; the sampling cadence"
    )
    parser.add_argument("--config", type=str, default=None, help="Path to settings.jsonc")
    parser.add_argument("--json", action="store_true", help="Print the manifest as JSON only")
    args = parser.parse_args(argv)

    if args.seconds <= 0 and args.frames is None:
        print("[clip] --seconds must be positive unless --frames is given", file=sys.stderr)
        return 2
    if args.frames is not None and args.frames < 1:
        print("[clip] --frames must be at least 1", file=sys.stderr)
        return 2

    config = load_config(args.config)
    if args.tick_hz is not None:
        config.loop.tick_hz = max(1, int(args.tick_hz))
    disabled, missing = _disable(config)

    # A run against the real dog opens the camera and owns the servo bus, so it takes the lock.
    # A run handed a fake HAL owns nothing and must not touch the home directory (`tests`).
    lock: RunLock | None = None
    if hal is None:
        lock = RunLock()
        try:
            lock.acquire("camera_record")
        except BusBusy as exc:
            print(f"[clip] {exc}", file=sys.stderr)
            print("[clip] stop it first: systemctl stop houndmind", file=sys.stderr)
            return 3

    path = _resolve(args.out)
    try:
        runtime = HoundMindRuntime(config, build_modules(config, hal=hal))
        writer = ClipWriter(path, host=_host_block(), commit=_commit())
        try:
            record_loop(
                runtime,
                writer,
                seconds=args.seconds,
                tick_hz=config.loop.tick_hz,
                max_frames=args.frames,
            )
        except BaseException:
            writer.finish(complete=False)
            raise
        manifest = writer.finish(complete=True)
    finally:
        if lock is not None:
            lock.release()

    if args.json:
        print(json.dumps(manifest, indent=2))
    else:
        _report(manifest, path)
        print(f"[clip] disabled: {', '.join(disabled) if disabled else 'none'}")
        if missing:
            print(f"[clip] not declared by this config: {', '.join(missing)}")
    if manifest["frame_count"] == 0:
        print(
            "[clip] no frames were published: enable a vision module (vision_pi4 on a Pi 4) "
            "and record again; nothing was replayed from this run",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
