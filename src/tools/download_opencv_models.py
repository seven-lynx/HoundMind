"""Download the SSD-MobileNet COCO model and labels for the semantic labeler.

Writes three files into `<repo>/models` - the folder `settings.semantic_labeler` points at: the
TensorFlow frozen graph, the text graph OpenCV reads alongside it, and the 90 COCO class names.

Why these sources (#182): the URLs this tool used to name
(`ssd_mobilenet_v3_large_coco_2020_01_14.*` and `testdata/dnn/labels/coco_labels.txt`) never existed
in `opencv_extra`, so all three downloads were 404s. The graph and weights below are the pair
OpenCV's own `samples/dnn/models.yml` uses, and every URL is pinned to a tag or a model-zoo release
so a rerun is reproducible.
"""

from __future__ import annotations

import argparse
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# The frozen graph ships only inside the model-zoo tarball (~77 MB); `opencv_extra` carries the text
# graph that has to be read with it (`cv2.dnn.readNetFromTensorflow(model, config)`).
WEIGHTS_TARBALL = (
    "https://storage.googleapis.com/download.tensorflow.org/models/object_detection/"
    "ssd_mobilenet_v1_coco_2017_11_17.tar.gz"
)
WEIGHTS_MEMBER = "frozen_inference_graph.pb"
CONFIG_URL = (
    "https://raw.githubusercontent.com/opencv/opencv_extra/4.10.0/testdata/dnn/"
    "ssd_mobilenet_v1_coco_2017_11_17.pbtxt"
)
LABELS_URL = (
    "https://raw.githubusercontent.com/opencv/opencv/4.10.0/samples/data/dnn/"
    "object_detection_classes_coco.txt"
)

# The filenames `settings.semantic_labeler` looks for; keep the two in step.
MODEL_NAME = "ssd_mobilenet_v1_coco.pb"
CONFIG_NAME = "ssd_mobilenet_v1_coco.pbtxt"
LABELS_NAME = "coco_labels.txt"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url} -> {dest}")
    urllib.request.urlretrieve(url, dest)


def extract_member(archive: Path, member_name: str, dest: Path) -> None:
    """Copy one file out of a `.tar.gz` without unpacking the rest of it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or Path(member.name).name != member_name:
                continue
            source = tar.extractfile(member)
            if source is not None:
                dest.write_bytes(source.read())
                print(f"Extracted {member.name} -> {dest}")
                return
    raise SystemExit(f"{member_name} is not in {archive}: the model tarball changed upstream")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the SSD-MobileNet COCO model and labels"
    )
    parser.add_argument(
        "--dest",
        default="models",
        help="Destination folder, relative to the repository root (default: models)",
    )
    args = parser.parse_args()

    # `parents[2]` is the repository root, because this file lives in `src/tools/`. The old
    # `parents[1]` wrote to `src/models`, which is not where `settings.semantic_labeler` looks
    # (#182).
    root = Path(__file__).resolve().parents[2]
    dest = (root / args.dest).resolve()

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "weights.tar.gz"
        download(WEIGHTS_TARBALL, archive)
        extract_member(archive, WEIGHTS_MEMBER, dest / MODEL_NAME)

    download(CONFIG_URL, dest / CONFIG_NAME)
    download(LABELS_URL, dest / LABELS_NAME)
    print(f'Done. Set settings.semantic_labeler.backend to "opencv_dnn" to use {dest}.')


if __name__ == "__main__":
    main()
