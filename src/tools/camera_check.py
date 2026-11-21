"""Camera diagnostic tool for Pi4 vision setup.

Usage:
    python -m tools.camera_check --list-devices --max-index 5
    python -m tools.camera_check --index 0 --save frame.jpg

The runtime captures through `picamera2` on Bookworm (see `optional/vision_pi4.py`, `backend:
picamera2`): the sensor is served by libcamera/unicam, and the V4L2 node OpenCV opens does not
produce frames there. This tool used to try only OpenCV, so on a healthy Pi 4 it reported a broken
camera (#395). It now tries the backend the runtime uses first, falls back to OpenCV, and names
what it tried when both fail.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

# How long the sensor is given to settle its exposure before the still is taken. Module-level so a
# test can set it to zero instead of sleeping.
PICAMERA2_SETTLE_S = 0.5


def _picamera2() -> Any | None:
    """The `Picamera2` class, or None when the wheel is not installed."""
    try:
        from picamera2 import Picamera2  # type: ignore
    except Exception:  # noqa: BLE001 - a missing optional wheel is the answer
        return None
    return Picamera2


def _encode_jpeg(frame: Any) -> bytes | None:
    """One still as JPEG. The runtime needs OpenCV for this too, so it is the same requirement."""
    try:
        import cv2  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    ok, buf = cv2.imencode(".jpg", frame)
    return buf.tobytes() if ok else None


def _picamera2_indexes() -> list[int]:
    """The cameras libcamera reports. On Bookworm that is the list a still can come from."""
    camera = _picamera2()
    if camera is None:
        return []
    try:
        return list(range(len(camera.global_camera_info())))
    except Exception:  # noqa: BLE001 - the wheel may be present with no camera attached
        return []


def _cv2_indexes(max_index: int) -> list[int]:
    try:
        import cv2  # type: ignore
    except Exception:  # noqa: BLE001
        return []

    available: list[int] = []
    for idx in range(max_index + 1):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            available.append(idx)
        cap.release()
    return available


def list_devices(max_index: int) -> list[int]:
    """Indexes a still can actually be taken from, by either backend."""
    indexes = _picamera2_indexes()
    return indexes if indexes else _cv2_indexes(max_index)


def _capture_picamera2() -> bytes | None:
    camera = _picamera2()
    if camera is None:
        return None
    instance = None
    try:
        instance = camera()
        instance.configure(instance.create_still_configuration())
        instance.start()
        if PICAMERA2_SETTLE_S:
            time.sleep(PICAMERA2_SETTLE_S)
        return _encode_jpeg(instance.capture_array())
    except Exception:  # noqa: BLE001 - reported by the caller, which names the backend
        return None
    finally:
        if instance is not None:
            try:
                instance.stop()
                instance.close()
            except Exception:  # noqa: BLE001 - closing a failed camera has no better outcome
                pass


def _capture_cv2(index: int) -> bytes | None:
    try:
        import cv2  # type: ignore
    except Exception:  # noqa: BLE001
        return None

    cap = cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            return None
        ok, frame = cap.read()
        if not ok:
            return None
        return _encode_jpeg(frame)
    finally:
        cap.release()


def capture_frame_with_backend(index: int) -> tuple[bytes | None, str]:
    """`(jpeg, backend)` - the backend names what was tried, so a failure is not a lens problem."""
    data = _capture_picamera2()
    if data is not None:
        return data, "picamera2"
    data = _capture_cv2(index)
    if data is not None:
        return data, f"cv2 index {index}"
    return None, f"picamera2 and cv2 index {index}"


def capture_frame(index: int) -> bytes | None:
    data, _ = capture_frame_with_backend(index)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Camera diagnostic tool")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--max-index", type=int, default=5)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--save", type=str, default=None)
    args = parser.parse_args()

    if args.list_devices:
        print("Available indexes:", list_devices(args.max_index))
        return

    data, backend = capture_frame_with_backend(args.index)
    if data is None:
        raise SystemExit(
            f"Failed to capture a frame with {backend}. "
            "Check `libcamera-hello` and try --list-devices, then a different index."
        )
    if args.save:
        Path(args.save).write_bytes(data)
        print(f"Saved frame to {args.save} (backend: {backend})")
    else:
        print(f"Captured {len(data)} bytes with {backend}")


if __name__ == "__main__":
    main()
