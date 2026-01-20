"""Camera diagnostic tool for Pi4 vision setup.

Usage:
    python -m tools.camera_check --list-devices --max-index 5
    python -m tools.camera_check --index 0 --save frame.jpg
"""

from __future__ import annotations

import argparse
from pathlib import Path


def list_devices(max_index: int) -> list[int]:
    try:
        import cv2  # type: ignore
    except Exception:
        return []

    available: list[int] = []
    for idx in range(max_index + 1):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            available.append(idx)
        cap.release()
    return available


def capture_frame(index: int) -> bytes | None:
    try:
        import cv2  # type: ignore
    except Exception:
        return None

    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        return None
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return None
    return buf.tobytes()


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

    data = capture_frame(args.index)
    if data is None:
        raise SystemExit("Failed to capture frame. Try a different index.")
    if args.save:
        Path(args.save).write_bytes(data)
        print(f"Saved frame to {args.save}")


if __name__ == "__main__":
    main()
