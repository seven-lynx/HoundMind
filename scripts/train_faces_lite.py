#!/usr/bin/env python3
"""
Train the Lite face recognizer (LBPH) from directory structure:

    data/faces_lite/<name>/*.jpg

- Requires OpenCV contrib (cv2.face) for LBPH; otherwise exits with info.
- If cv2.face is missing, the lite backend still supports detection-only.

Usage:
  python scripts/train_faces_lite.py --preset pi3 --data-dir data/faces_lite
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

# Ensure repo root on sys.path (so `packmind` can be imported when run directly)
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packmind.packmind_config import load_config
from packmind.services.face_recognition_lite_service import FaceRecognitionLiteService


def main() -> int:
    parser = argparse.ArgumentParser(description="Train LBPH model for lite face backend")
    parser.add_argument("--preset", default="default", help="Config preset to load (default, pi3, indoor, etc.)")
    parser.add_argument("--data-dir", default=None, help="Training images directory (defaults to config.FACE_LITE_DATA_DIR)")
    args = parser.parse_args()

    cfg = load_config(args.preset)
    data_dir = Path(args.data_dir or getattr(cfg, "FACE_LITE_DATA_DIR", "data/faces_lite"))

    svc = FaceRecognitionLiteService(cfg)
    # Check if LBPH is available
    if getattr(svc, "_recognizer", None) is None:
        print("cv2.face (opencv-contrib) not available — detection-only mode; training is not applicable.")
        print("Install opencv-contrib-python to enable LBPH training.")
        return 1

    ok = svc.train_from_dir(data_dir)
    if ok:
        print(f"Training complete. Model saved; labels in: {svc._labels_file}")
        return 0
    else:
        print("Training failed or no images found. Ensure directory structure: data/faces_lite/<name>/*.jpg")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
