"""Download a basic OpenCV DNN model + labels for semantic labeling.

This script downloads a lightweight MobileNet-SSD COCO model and labels into
./models so the Pi4 semantic labeler can be enabled quickly.
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

FILES = {
    "model": "https://github.com/opencv/opencv_extra/raw/master/testdata/dnn/ssd_mobilenet_v3_large_coco_2020_01_14.pbtxt",
    "weights": "https://github.com/opencv/opencv_extra/raw/master/testdata/dnn/ssd_mobilenet_v3_large_coco_2020_01_14.pb",
    "labels": "https://github.com/opencv/opencv_extra/raw/master/testdata/dnn/labels/coco_labels.txt",
}


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url} -> {dest}")
    urllib.request.urlretrieve(url, dest)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download basic OpenCV DNN model + labels"
    )
    parser.add_argument("--dest", default="models", help="Destination folder")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    dest = (root / args.dest).resolve()

    download(FILES["model"], dest / "ssd_mobilenet_v3_large_coco_2020_01_14.pbtxt")
    download(FILES["weights"], dest / "ssd_mobilenet_v3_large_coco_2020_01_14.pb")
    download(FILES["labels"], dest / "coco_labels.txt")
    print("Done.")


if __name__ == "__main__":
    main()
