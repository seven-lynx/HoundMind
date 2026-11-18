"""Score a folder of frames against stored place views, off the dog (#299).

    python -m tools.place_match <views-dir> <frames-dir> [--min-score 0.45] [--json]

One line per frame: `place_id score verdict`, where verdict is `match`, `no-match` (the best view
scored below the threshold — the score is the evidence) or `featureless` (the frame had too little to
match). Exit 0 when every frame was scored, 1 when there were no views, no frames, or a frame could
not be read — a tool that silently scores nothing is the failure this exists to prevent.

The frames are ordinary images. `tests/test_place_match_cli.py` draws a **synthetic** set for CI,
because a photograph of somebody's kitchen cannot be committed; nothing here needs a camera.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from houndmind_ai.perception.place_views import load_views, match_frame

FRAME_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")


def frames_in(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.iterdir() if path.suffix.lower() in FRAME_SUFFIXES
    )


def verdict_for(valid: bool, reason: str | None) -> str:
    if valid:
        return "match"
    return "featureless" if (reason or "").startswith("frame too featureless") else "no-match"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score frames against stored place views")
    parser.add_argument("views", type=Path, help="the views directory (or a views.json)")
    parser.add_argument("frames", type=Path, help="a directory of image frames")
    parser.add_argument("--min-score", type=float, default=0.45, help="match threshold (default 0.45)")
    parser.add_argument("--json", action="store_true", help="one JSON object per frame")
    args = parser.parse_args(argv)

    views = load_views(args.views)
    if not views:
        print(f"no views in {args.views}: teach a place first (docs/TOOLS.md)", file=sys.stderr)
        return 1
    if not args.frames.is_dir():
        print(f"not a directory: {args.frames}", file=sys.stderr)
        return 1
    frames = frames_in(args.frames)
    if not frames:
        print(f"no frames in {args.frames} ({', '.join(FRAME_SUFFIXES)})", file=sys.stderr)
        return 1

    try:
        import cv2  # imported here so `--help` works on a machine without OpenCV
    except ImportError as exc:
        print(f"missing dependency: {exc.name or 'opencv'}", file=sys.stderr)
        return 1

    code = 0
    for path in frames:
        image = cv2.imread(str(path))
        if image is None:
            print(f"{path.name}: cannot be read as an image", file=sys.stderr)
            code = 1
            continue
        result = match_frame(image, views, args.min_score)
        verdict = verdict_for(result.valid, result.reason)
        if args.json:
            print(
                json.dumps(
                    {
                        "frame": path.name,
                        "place_id": result.place_id,
                        "score": round(result.score, 3),
                        "verdict": verdict,
                        "reason": result.reason,
                        "ranked": [[place, round(value, 3)] for place, value in result.ranked],
                    }
                )
            )
        else:
            print(
                f"{path.name} {result.place_id or '-'} {result.score:.3f} {verdict}"
                + (f"  ({result.reason})" if result.reason else "")
            )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
