"""A place is recognised by what it looks like, not by where dead reckoning says it is (#296, #301).

A *view* is the smallest artefact that can be matched twice: a 32x24 grayscale thumbnail, the ORB
keypoints and descriptors, and when it was taken. One JSON file holds every view in a directory, so a
place can be taught on the dog and matched off it, and `tools.place_match` can score a folder of
frames without a camera.

Two rules shape this module.

1. **A view with no descriptors is refused, not stored.** A stored view that cannot match anything
   looks exactly like a place nobody has visited, and the next session re-derives why.
2. **A weak match is published as weak.** `match` returns the best score whether or not it clears the
   threshold, so "no idea, best 0.12" is visible instead of silent. The caller decides; this module
   never upgrades a guess to a place.

cv2 is imported **inside** `extract` and `view_from_jpeg`: `lite` does not carry OpenCV, and
`perception/__init__.py` must stay importable on an install without it. The scoring and the refusal
rules are plain Python, which is also why they are testable on a workstation with no wheel at all.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_VIEWS_DIR",
    "DESCRIPTOR_BYTES",
    "MATCH_BITS",
    "MIN_DESCRIPTORS",
    "MatchResult",
    "PlaceView",
    "THUMB_H",
    "THUMB_W",
    "extract",
    "load_views",
    "match",
    "match_frame",
    "save_views",
    "score",
    "thumb_b64",
    "upsert_view",
    "view_from_frame",
    "view_from_jpeg",
    "views_path",
]

# The thumbnail a person can see in a listing, small enough that 200 places cost 150 KB.
THUMB_W = 32
THUMB_H = 24

# ORB descriptors are 32 bytes each, always: the length is how a truncated row is caught on load.
DESCRIPTOR_BYTES = 32

# A frame below this has nothing to match, so it is reported as featureless rather than scored 0.0
# against every place - "the wall is blank" and "this is not the kitchen" are different answers.
MIN_DESCRIPTORS = 8

# A descriptor pair within half of the 256 bits is a candidate match. Half is deliberately generous:
# the ratio below does the discriminating, and a tight gate would make score() behave like a cliff.
MATCH_BITS = 64

VIEWS_FILENAME = "views.json"

# Where a teach request leaves a view, and where `place_recognition` looks for one. Beside the places
# file, so a user who moves `settings.places.path` finds the views next to it. It lives here — with
# the format, not with a consumer — because the control plane writes views too and `services` may not
# import `navigation` (`services/api.py` states that rule where it compares `place_goal` as a string).
DEFAULT_VIEWS_DIR = "~/.houndmind/places/views"


def views_path(directory: str | Path) -> Path:
    """The views file inside a directory, so the caller may name the directory or the file."""
    path = Path(directory).expanduser()
    return path if path.suffix == ".json" else path / VIEWS_FILENAME


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: Any) -> bytes:
    if not isinstance(text, str):
        raise ValueError("a descriptor or thumbnail must be base64 text")
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same refusal
        raise ValueError(f"not base64: {exc}") from exc

@dataclass(frozen=True)
class PlaceView:
    """One place, as seen from the anchor it was taught at. Immutable: a re-teach is a new view."""

    place_id: str
    created_at: float
    thumb: bytes
    keypoints: tuple[tuple[float, float], ...]
    descriptors: tuple[bytes, ...]

    def __post_init__(self) -> None:
        if not self.place_id:
            raise ValueError("a view needs a place id")
        if len(self.thumb) != THUMB_W * THUMB_H:
            raise ValueError(
                f"a thumbnail is {THUMB_W}x{THUMB_H} = {THUMB_W * THUMB_H} bytes, "
                f"got {len(self.thumb)}"
            )
        if len(self.keypoints) != len(self.descriptors):
            raise ValueError("every keypoint needs a descriptor and the other way round")
        if len(self.descriptors) < MIN_DESCRIPTORS:
            raise ValueError(
                f"a view needs at least {MIN_DESCRIPTORS} descriptors, got {len(self.descriptors)}: "
                "a view that cannot match is a place nobody can find"
            )
        for row in self.descriptors:
            if len(row) != DESCRIPTOR_BYTES:
                raise ValueError(
                    f"a descriptor is {DESCRIPTOR_BYTES} bytes, got {len(row)} for {self.place_id}"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "place_id": self.place_id,
            "created_at": self.created_at,
            "thumb": _b64(self.thumb),
            "keypoints": [[round(x, 2), round(y, 2)] for x, y in self.keypoints],
            "descriptors": [_b64(row) for row in self.descriptors],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> PlaceView:
        if not isinstance(raw, dict):
            raise ValueError("a view must be an object")
        keypoints = raw.get("keypoints")
        if not isinstance(keypoints, list):
            raise ValueError("keypoints must be a list")
        points: list[tuple[float, float]] = []
        for entry in keypoints:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError("a keypoint is [x, y]")
            points.append((float(entry[0]), float(entry[1])))
        descriptors = raw.get("descriptors")
        if not isinstance(descriptors, list):
            raise ValueError("descriptors must be a list")
        return cls(
            place_id=str(raw.get("place_id") or ""),
            created_at=float(raw.get("created_at") or 0.0),
            thumb=_unb64(raw.get("thumb")),
            keypoints=tuple(points),
            descriptors=tuple(_unb64(row) for row in descriptors),
        )


def save_views(directory: str | Path, views: tuple[PlaceView, ...]) -> Path:
    """Write every view into one file (versioned, so a later format can be told apart)."""
    path = views_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"version": 1, "views": [view.to_dict() for view in views]}
    path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    return path


def load_views(directory: str | Path) -> tuple[PlaceView, ...]:
    """Every view a directory holds. A missing file is no views, not an error.

    A malformed entry is skipped rather than fatal: one unreadable view must not cost the others,
    and the caller sees a shorter tuple, which is exactly what `score` reports.
    """
    path = views_path(directory)
    if not path.exists():
        return ()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    raw = document.get("views") if isinstance(document, dict) else None
    if not isinstance(raw, list):
        return ()
    views: list[PlaceView] = []
    for entry in raw:
        try:
            views.append(PlaceView.from_dict(entry))
        except (TypeError, ValueError):
            continue
    return tuple(views)


def upsert_view(views: tuple[PlaceView, ...], view: PlaceView) -> tuple[PlaceView, ...]:
    """`views` with `view` in place of every view for the same place, or appended.

    `save_views` writes the whole file, so a second teach that appended blindly would duplicate the
    one view a place has. One view per place is the file's shape: a re-teach replaces what the place
    looked like from there, and a place taught before still keeps its own view.
    """
    kept = tuple(existing for existing in views if existing.place_id != view.place_id)
    return kept + (view,)


def thumb_b64(view: PlaceView) -> str:
    """The 32x24 thumbnail as base64, for a listing that draws it (#313).

    Published beside a place rather than inside it: the places file carries the flag
    (`kernel/place.py::PLACE_KEYS`), the views file carries the image, and a client joins them by id.
    """
    return _b64(view.thumb)


def extract(
    frame: Any, *, max_features: int = 200
) -> tuple[bytes, tuple[tuple[float, float], ...], tuple[bytes, ...]]:
    """The three parts of a view from one frame. OpenCV's feature extraction, and only here.

    `ImportError` is left to the caller: a module disables with a reason, a tool exits non-zero.
    """
    import cv2  # imported here so `lite` can import this module without OpenCV
    import numpy as np

    array = np.asarray(frame)
    if array.ndim == 3:
        gray = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
    elif array.ndim == 2:
        gray = array
    else:
        raise ValueError("a frame must be 2-D grayscale or 3-D BGR")
    thumb = cv2.resize(gray, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(nfeatures=max(1, int(max_features)))
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    points = tuple((float(kp.pt[0]), float(kp.pt[1])) for kp in keypoints or ())
    rows = tuple(bytes(row) for row in (descriptors if descriptors is not None else []))
    return thumb.astype("uint8").tobytes(), points, rows


def view_from_jpeg(data: Any, place_id: str, *, now: float | None = None) -> PlaceView:
    """A view of `place_id` from encoded JPEG bytes, or `ValueError` when they are not an image.

    `view_from_frame` takes the raw array, which is what `vision_frame` carries. The control plane's
    camera holds **encoded** frames (`services/camera.py::CameraService.latest`), so this decodes
    them here rather than in an HTTP handler — the same reason `extract` imports OpenCV itself.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        # Checked before the import: empty bytes are not an OpenCV problem, and a `lite` install
        # should hear that rather than "OpenCV is not installed".
        raise ValueError("a view needs an encoded frame and got nothing")

    import cv2  # imported here so `lite` can import this module without OpenCV
    import numpy as np

    array = cv2.imdecode(np.frombuffer(bytes(data), dtype="uint8"), cv2.IMREAD_COLOR)
    if array is None:
        raise ValueError("those bytes are not an image OpenCV can read")
    return view_from_frame(array, place_id, now=now)


def view_from_frame(frame: Any, place_id: str, *, now: float | None = None) -> PlaceView:
    """A view of `place_id` from this frame, or `ValueError` when the frame cannot be matched later."""
    thumb, points, rows = extract(frame)
    if len(rows) < MIN_DESCRIPTORS:
        raise ValueError(
            f"a view needs at least {MIN_DESCRIPTORS} descriptors and this frame gave {len(rows)}: "
            "point the camera at something with texture, or teach the place from further away"
        )
    return PlaceView(
        place_id=place_id,
        created_at=time.time() if now is None else now,
        thumb=thumb,
        keypoints=points,
        descriptors=rows,
    )


@dataclass(frozen=True)
class MatchResult:
    """What the matcher concluded, and what it would have said if the threshold were lower.

    `valid` is the only field a consumer may act on. `score` and `ranked` are always present, so a
    refusal is as informative as a match.
    """

    valid: bool
    place_id: str | None
    score: float
    reason: str | None = None
    ranked: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "place_id": self.place_id,
            "score": round(self.score, 3),
            "reason": self.reason,
        }


def _hamming(left: bytes, right: bytes) -> int:
    return sum((a ^ b).bit_count() for a, b in zip(left, right, strict=False))


def score(descriptors: tuple[bytes, ...], view: PlaceView) -> float:
    """The share of the smaller descriptor set that found a partner in the larger one, in [0, 1].

    Symmetric on purpose, and it has to ask the *smaller* set: a 50-descriptor view of a wall against
    a 200-descriptor frame of the same wall is a full match, and counting the frame's descriptors as
    the numerator over the view's as the denominator produced 4.0 for exactly that case. Asking the
    smaller set of the larger keeps the ratio at or below 1 by construction.
    """
    if not descriptors or not view.descriptors:
        return 0.0
    query, target = (
        (descriptors, view.descriptors)
        if len(descriptors) <= len(view.descriptors)
        else (view.descriptors, descriptors)
    )
    paired = 0
    for descriptor in query:
        if min(_hamming(descriptor, other) for other in target) <= MATCH_BITS:
            paired += 1
    return paired / len(query)


def match(
    descriptors: tuple[bytes, ...], views: tuple[PlaceView, ...], min_score: float
) -> MatchResult:
    """Rank every view against this frame's descriptors, and say what the best one scored.

    Below `min_score` the answer is `place_id: None` **with** the score that lost, and a frame with
    fewer than `MIN_DESCRIPTORS` descriptors is refused as featureless before any comparison is made.
    """
    if len(descriptors) < MIN_DESCRIPTORS:
        return MatchResult(
            valid=False,
            place_id=None,
            score=0.0,
            reason=(
                f"frame too featureless ({len(descriptors)} descriptors, {MIN_DESCRIPTORS} needed)"
            ),
        )
    ranked = tuple(
        sorted(
            ((view.place_id, score(descriptors, view)) for view in views),
            key=lambda item: (-item[1], item[0]),
        )
    )
    if not ranked:
        return MatchResult(valid=False, place_id=None, score=0.0, reason="no views stored")
    place_id, best = ranked[0]
    if best >= min_score:
        return MatchResult(valid=True, place_id=place_id, score=best, ranked=ranked)
    return MatchResult(
        valid=False,
        place_id=None,
        score=best,
        reason=f"best match {place_id} at {best:.2f}, below {min_score:.2f}",
        ranked=ranked,
    )


def match_frame(frame: Any, views: tuple[PlaceView, ...], min_score: float) -> MatchResult:
    """`extract` then `match`: the whole question for one frame, which is what the CLI asks."""
    _thumb, _points, descriptors = extract(frame)
    return match(descriptors, views, min_score)

