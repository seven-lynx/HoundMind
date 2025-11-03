#!/usr/bin/env python3
"""
Camera diagnostics utility.

Features:
- Try to open a camera by index and backend (MSMF/DShow/V4L2/etc.)
- Print capture properties (resolution, FPS, FOURCC, backend)
- Optionally save a single frame to a file for validation
- Optionally probe a range of indexes to list available devices

Usage examples:
  python tools/camera_check.py                 # Try index 0 with default backend
  python tools/camera_check.py --index 1       # Try index 1
  python tools/camera_check.py --backend dshow # Force DirectShow (Windows)
  python tools/camera_check.py --save frame.jpg
  python tools/camera_check.py --list-devices --max-index 10

Env fallback:
  CAMERA_INDEX environment variable is used if --index is not provided.

Note: On Windows, try --backend dshow if MSMF has issues. On Linux (Pi), V4L2 is typical.
"""

import argparse
import os
import sys
import time
from typing import Optional


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def map_backend(name: Optional[str]) -> int:
    """Map backend name to OpenCV CAP_* constant. Returns 0 for default if name is falsy/unknown."""
    if not name:
        return 0
    name_lower = name.strip().lower()
    # Common backends
    mapping = {
        "any": 0,
        "default": 0,
        "msmf": getattr(__import__("cv2"), "CAP_MSMF", 0),
        "dshow": getattr(__import__("cv2"), "CAP_DSHOW", 0),
        "v4l2": getattr(__import__("cv2"), "CAP_V4L2", 0),
        "gstreamer": getattr(__import__("cv2"), "CAP_GSTREAMER", 0),
        "ffmpeg": getattr(__import__("cv2"), "CAP_FFMPEG", 0),
    }
    return mapping.get(name_lower, 0)


def fourcc_to_str(fourcc: float) -> str:
    try:
        v = int(fourcc)
        return "".join([chr(v & 0xFF), chr((v >> 8) & 0xFF), chr((v >> 16) & 0xFF), chr((v >> 24) & 0xFF)])
    except Exception:
        return str(fourcc)


def try_import_cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except ImportError:
        eprint("ERROR: OpenCV (cv2) is not installed.")
        eprint("Install with: pip install opencv-python")
        sys.exit(1)


def list_devices(cv2, max_index: int, backend: int, timeout: float) -> None:
    print(f"Probing camera indexes 0..{max_index} using backend={backend} (0=default)...")
    for idx in range(0, max_index + 1):
        cap = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
        # Give it a moment to initialize
        t0 = time.time()
        ok = False
        while time.time() - t0 < timeout:
            if cap.isOpened():
                ok = True
                break
            time.sleep(0.05)
        if ok:
            print(f"  [OK] Index {idx} opened")
            cap.release()
        else:
            print(f"  [--] Index {idx} not available")


def print_properties(cv2, cap) -> None:
    props = {
        "FRAME_WIDTH": cv2.CAP_PROP_FRAME_WIDTH,
        "FRAME_HEIGHT": cv2.CAP_PROP_FRAME_HEIGHT,
        "FPS": cv2.CAP_PROP_FPS,
        "FOURCC": cv2.CAP_PROP_FOURCC,
        "FORMAT": cv2.CAP_PROP_FORMAT,
        "MODE": cv2.CAP_PROP_MODE,
        "CONVERT_RGB": cv2.CAP_PROP_CONVERT_RGB,
        "BACKEND": cv2.CAP_PROP_BACKEND,
        "AUTO_EXPOSURE": getattr(cv2, "CAP_PROP_AUTO_EXPOSURE", None),
    }
    print("Capture properties:")
    for name, prop in props.items():
        if prop is None:
            continue
        val = cap.get(prop)
        if name == "FOURCC":
            sval = f"{val} ({fourcc_to_str(val)})"
        else:
            sval = str(val)
        print(f"  - {name}: {sval}")


def main():
    parser = argparse.ArgumentParser(description="Camera diagnostics utility")
    parser.add_argument("--index", type=int, default=None, help="Camera index to open (default: env CAMERA_INDEX or 0)")
    parser.add_argument("--backend", type=str, default=None, help="Backend hint: any|default|msmf|dshow|v4l2|gstreamer|ffmpeg")
    parser.add_argument("--width", type=int, default=None, help="Requested frame width")
    parser.add_argument("--height", type=int, default=None, help="Requested frame height")
    parser.add_argument("--fps", type=float, default=None, help="Requested FPS")
    parser.add_argument("--timeout", type=float, default=2.0, help="Seconds to wait for device to open")
    parser.add_argument("--save", type=str, default=None, help="Save a single frame to this path (jpg/png)")
    parser.add_argument("--list-devices", action="store_true", help="Probe a range of indexes to list available devices")
    parser.add_argument("--max-index", type=int, default=5, help="Max index to probe when listing devices")

    args = parser.parse_args()

    cv2 = try_import_cv2()

    idx = args.index
    if idx is None:
        env_idx = os.environ.get("CAMERA_INDEX")
        if env_idx is not None and env_idx.strip():
            try:
                idx = int(env_idx)
            except ValueError:
                eprint(f"Ignoring invalid CAMERA_INDEX env value: {env_idx}")
                idx = 0
        else:
            idx = 0

    backend_flag = map_backend(args.backend)

    if args.list_devices:
        list_devices(cv2, args.max_index, backend_flag, args.timeout)
        # Continue to try the selected index as well to provide detailed diagnostics

    print(f"Opening camera index={idx} backend={args.backend or 'default'}...")
    cap = cv2.VideoCapture(idx, backend_flag) if backend_flag else cv2.VideoCapture(idx)

    t0 = time.time()
    while time.time() - t0 < args.timeout:
        if cap.isOpened():
            break
        time.sleep(0.05)

    if not cap.isOpened():
        eprint("FAILED to open camera. Tips:")
        eprint("- Windows: try --backend dshow or unplug/replug camera; ensure it's not in use by another app")
        eprint("- Linux/Pi: ensure /dev/video* exists and permissions are correct; try sudo usermod -a -G video $USER")
        eprint("- Try a different index with --index or probe with --list-devices")
        sys.exit(2)

    if args.width is not None:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(args.width))
    if args.height is not None:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(args.height))
    if args.fps is not None:
        cap.set(cv2.CAP_PROP_FPS, float(args.fps))

    # Read a frame
    ok, frame = cap.read()
    if not ok or frame is None:
        eprint("Opened device but failed to read a frame.")
        eprint("- Try increasing --timeout or adjusting --backend")
        eprint("- Some cameras require explicit width/height/fps; try --width 640 --height 480")
        cap.release()
        sys.exit(3)

    print_properties(cv2, cap)

    h, w = frame.shape[:2]
    print(f"Got a frame: {w}x{h}")

    if args.save:
        out_path = args.save
        try:
            ok_write = cv2.imwrite(out_path, frame)
            if ok_write:
                print(f"Saved a frame to: {out_path}")
            else:
                eprint(f"Failed to save frame to: {out_path}")
        except Exception as ex:
            eprint(f"Exception while saving frame to {out_path}: {ex}")

    cap.release()
    print("Done.")


if __name__ == "__main__":
    # Add repo root to sys.path so the utility can import project modules if needed later
    try:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
    except Exception:
        pass
    main()
