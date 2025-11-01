#!/usr/bin/env python3
"""
Lite Face Backend Smoke Test

Runs the FaceRecognitionLiteService for a short duration and logs detections.
Useful on Raspberry Pi 3B to verify camera + Haar cascade pipeline without dlib.

Usage examples:
  python tools/lite_face_smoke_test.py --preset pi3 --duration 60
  python tools/lite_face_smoke_test.py --duration 30 --camera 0 --interval 2.0
"""
from __future__ import annotations

import sys
import time
import argparse
from pathlib import Path

# Ensure repo root in sys.path for direct execution
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packmind.packmind_config import load_config
from packmind.services.face_recognition_lite_service import FaceRecognitionLiteService


def main() -> int:
    p = argparse.ArgumentParser(description="Run lite face backend for N seconds and log detections")
    p.add_argument("--preset", default="default", help="Config preset to load (default, pi3, indoor, etc.)")
    p.add_argument("--duration", type=float, default=60.0, help="How long to run (seconds)")
    p.add_argument("--camera", type=int, default=0, help="Camera index (default 0)")
    p.add_argument("--interval", type=float, default=None, help="Override detection interval (seconds)")
    args = p.parse_args()

    cfg = load_config(args.preset)
    svc = FaceRecognitionLiteService(cfg)

    # Allow overriding camera index and detection interval
    # (camera index is used by OpenCV internally; we can't pass it in directly through service)
    # For now, we set the default camera index via env var if needed — OpenCV's VideoCapture(0) is fixed.
    # If you need a different index, run with `v4l2-ctl`/OS config, or change the code to pass an index.
    if args.interval is not None:
        svc.detection_interval = float(args.interval)

    print(f"Starting lite face service (duration={args.duration}s, interval={svc.detection_interval}s)...")
    if not svc.start():
        print("Failed to start lite face service — check camera is available.")
        return 1

    t_end = time.time() + args.duration
    total_frames = 0
    total_detections = 0
    last_print = 0.0

    try:
        while time.time() < t_end:
            res = svc.detect_and_recognize()
            total_frames += 1
            faces = res.get("faces", []) if isinstance(res, dict) else []
            if faces:
                total_detections += len(faces)
                for f in faces:
                    loc = f.get("location", (0, 0, 0, 0))
                    name = f.get("name", "Unknown")
                    conf = f.get("confidence", 0.0)
                    known = f.get("known", False)
                    print(f"[+]{' KNOWN' if known else ' ---- '} name={name} conf={conf:.2f} loc={loc}")
            # Print a heartbeat every ~5s
            now = time.time()
            if now - last_print > 5.0:
                last_print = now
                print(f"...running; frames={total_frames} detections={total_detections}")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        svc.stop()

    print(f"Done. frames={total_frames}, detections={total_detections}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
