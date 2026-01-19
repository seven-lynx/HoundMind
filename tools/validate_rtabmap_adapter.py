#!/usr/bin/env python3
"""Validate the internal RTAB-Map adapter used by `slam_pi4.py`.

Run this on the Pi4 after RTAB-Map is installed. It attempts to import the adapter,
initialize it, and exercise `process`, `get_pose`, `get_map_data`, and `get_trajectory`.

Usage:
  python tools/validate_rtabmap_adapter.py --camera 0
  python tools/validate_rtabmap_adapter.py --image /path/to/sample.jpg

If OpenCV is not available, the script will generate a synthetic frame.
"""

from __future__ import annotations

import argparse
import sys
import time
import importlib

def main():
    parser = argparse.ArgumentParser(description="Validate RTAB-Map adapter")
    parser.add_argument("--camera", type=int, help="camera index to capture frames from", default=None)
    parser.add_argument("--image", type=str, help="single image file to use as frame", default=None)
    parser.add_argument("--count", type=int, default=5, help="number of frames to send")
    args = parser.parse_args()

    try:
        mod = importlib.import_module('houndmind_ai.optional.slam_pi4')
    except Exception as exc:
        print("Failed to import slam_pi4 module:", exc)
        sys.exit(2)

    Adapter = getattr(mod, '_RtabmapAdapter', None)
    if Adapter is None:
        print("Adapter class not found in slam_pi4.py")
        sys.exit(2)

    adapter = Adapter({'params': {}})

    print("Checking for RTAB-Map Python bindings...")
    if not adapter.available():
        print("RTAB-Map bindings not available in this environment. Install and retry.")
        sys.exit(1)

    print("Initializing adapter...")
    try:
        adapter.init('rtabmap_test.db')
    except Exception as exc:
        print("Adapter.init failed:", exc)
        # Continue — some bindings may not need explicit init

    frame_supplier = None
    try:
        import cv2
        import numpy as np
        if args.camera is not None:
            cap = cv2.VideoCapture(args.camera)
            if not cap.isOpened():
                print("Failed to open camera index", args.camera)
                cap = None
            else:
                def supplier():
                    ret, f = cap.read()
                    if not ret:
                        return None
                    return f
                frame_supplier = supplier
        if frame_supplier is None and args.image is not None:
            img = cv2.imread(args.image)
            if img is None:
                print("Failed to read image", args.image)
            else:
                frame_supplier = lambda: img
    except Exception:
        # OpenCV not installed — generate a synthetic frame
        frame_supplier = None

    if frame_supplier is None:
        try:
            import numpy as np
            def synth():
                return (np.zeros((480,640,3), dtype='uint8'))
            frame_supplier = synth
        except Exception:
            frame_supplier = lambda: None

    print("Sending frames to adapter...")
    for i in range(args.count):
        f = frame_supplier()
        try:
            adapter.process(f, imu=None, timestamp=time.time())
            print(f"Processed frame {i+1}")
        except Exception as exc:
            print(f"adapter.process raised: {exc}")

    print("Attempting to fetch pose, map, trajectory")
    try:
        pose = adapter.get_pose()
        print("pose:", pose)
    except Exception as exc:
        print("get_pose error:", exc)

    try:
        md = adapter.get_map_data()
        print("map_data type:", type(md))
    except Exception as exc:
        print("get_map_data error:", exc)

    try:
        traj = adapter.get_trajectory()
        print("trajectory type:", type(traj))
    except Exception as exc:
        print("get_trajectory error:", exc)

    print("Validation complete — if any calls failed, adapt `_RtabmapAdapter` in `slam_pi4.py` accordingly.")

if __name__ == '__main__':
    main()
