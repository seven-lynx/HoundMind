"""Recognising a place turns two agreeing frames into a pose fix (#297, #298).

The matcher is stubbed here on purpose: `perception/place_views.py` is tested against synthetic
descriptors in `test_place_views.py`, and what this file pins is the module's contract — what it
publishes, when it publishes nothing, and how many frames it takes to move the pose. `cv2` is stubbed
into `sys.modules` for `start()`, which only checks that the wheel is importable.
"""

from __future__ import annotations

import sys
import types

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.navigation.place_recognition import PlaceRecognitionModule
from houndmind_ai.perception.place_views import (
    DESCRIPTOR_BYTES,
    MIN_DESCRIPTORS,
    THUMB_H,
    THUMB_W,
    MatchResult,
    PlaceView,
    save_views,
)

__all__ = [
    "test_a_disabled_module_publishes_nothing",
    "test_a_different_place_restarts_the_count",
    "test_a_frame_that_cannot_be_read_is_reported",
    "test_a_match_is_published_with_its_score",
    "test_a_new_unstamped_frame_is_still_scored",
    "test_a_refusal_is_published_too",
    "test_a_visit_is_anchored_once",
    "test_an_unstamped_frame_is_not_scored_twice",
    "test_one_frame_does_not_move_the_pose",
    "test_start_publishes_the_candidate_places",
    "test_the_same_frame_is_not_scored_twice",
    "test_two_agreeing_frames_anchor_the_pose",
]


def _settings(tmp_path, **overrides) -> dict:
    settings = {
        "views_dir": str(tmp_path / "views"),
        "min_score": 0.45,
        "confirm_frames": 2,
        "interval_s": 0.0,
    }
    settings.update(overrides)
    return {"place_recognition": settings}


def _context(tmp_path, **overrides) -> RuntimeContext:
    ctx = RuntimeContext()
    ctx.set("settings", _settings(tmp_path, **overrides))
    return ctx


def _module(monkeypatch, *, enabled: bool = True) -> PlaceRecognitionModule:
    monkeypatch.setitem(sys.modules, "cv2", types.ModuleType("cv2"))
    return PlaceRecognitionModule("place_recognition", enabled=enabled)


def _frame(ctx: RuntimeContext, frame_ts: float = 1.0) -> None:
    ctx.set("vision_frame", b"frame")
    ctx.set("vision_frame_ts", frame_ts)


def _stub_matcher(monkeypatch, *results: MatchResult) -> list:
    """Return `results` in order and the last one forever, counting the calls."""
    queue = list(results)
    calls: list[tuple] = []

    def fake(frame, views, min_score):
        calls.append((frame, views, min_score))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr("houndmind_ai.navigation.place_recognition.match_frame", fake)
    return calls


def _view(place_id: str) -> PlaceView:
    return PlaceView(
        place_id=place_id,
        created_at=1.0,
        thumb=bytes(THUMB_W * THUMB_H),
        keypoints=tuple((0.0, float(index)) for index in range(MIN_DESCRIPTORS)),
        descriptors=tuple(bytes([index]) * DESCRIPTOR_BYTES for index in range(MIN_DESCRIPTORS)),
    )

def test_a_disabled_module_publishes_nothing(tmp_path, monkeypatch) -> None:
    """The shipped default: off. A key from a module that never runs looks like a dead module."""
    ctx = _context(tmp_path)
    module = _module(monkeypatch, enabled=False)

    module.start(ctx)
    module.tick(ctx)

    assert "place_match" not in ctx
    assert "place_match_candidates" not in ctx


def test_start_publishes_the_candidate_places(tmp_path, monkeypatch) -> None:
    views_dir = tmp_path / "views"
    save_views(views_dir, (_view("kitchen"), _view("hall")))
    ctx = _context(tmp_path)
    module = _module(monkeypatch)

    module.start(ctx)

    assert ctx.get("place_match_candidates") == ["kitchen", "hall"]


def test_a_match_is_published_with_its_score(tmp_path, monkeypatch) -> None:
    _stub_matcher(monkeypatch, MatchResult(valid=True, place_id="kitchen", score=0.87))
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    _frame(ctx, frame_ts=5.0)
    module.tick(ctx)

    published = ctx.get("place_match")
    assert published["valid"] is True
    assert published["place_id"] == "kitchen"
    assert published["score"] == 0.87
    assert published["reason"] is None
    assert published["frame_ts"] == 5.0


def test_a_refusal_is_published_too(tmp_path, monkeypatch) -> None:
    """"No idea, best 0.20" is a state a client can show; silence looks like a dead module."""
    _stub_matcher(
        monkeypatch,
        MatchResult(valid=False, place_id=None, score=0.2, reason="best match hall at 0.20"),
    )
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    _frame(ctx)
    module.tick(ctx)

    published = ctx.get("place_match")
    assert published["valid"] is False
    assert published["place_id"] is None
    assert "hall" in published["reason"]
    assert "odometry_reset" not in ctx


def test_one_frame_does_not_move_the_pose(tmp_path, monkeypatch) -> None:
    _stub_matcher(monkeypatch, MatchResult(valid=True, place_id="kitchen", score=0.9))
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    _frame(ctx, frame_ts=1.0)
    module.tick(ctx)

    assert "odometry_reset" not in ctx
    assert "place_fix" not in ctx, "one good frame is a guess that scored well"


def test_two_agreeing_frames_anchor_the_pose(tmp_path, monkeypatch) -> None:
    _stub_matcher(monkeypatch, MatchResult(valid=True, place_id="kitchen", score=0.9))
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    _frame(ctx, frame_ts=1.0)
    module.tick(ctx)
    _frame(ctx, frame_ts=2.0)
    module.tick(ctx)

    fix = ctx.get("place_fix")
    assert ctx.get("odometry_reset") is True
    assert fix["place_id"] == "kitchen"
    assert fix["confidence"] == 0.9
    assert fix["frame_ts"] == 2.0


def test_a_different_place_restarts_the_count(tmp_path, monkeypatch) -> None:
    _stub_matcher(
        monkeypatch,
        MatchResult(valid=True, place_id="kitchen", score=0.9),
        MatchResult(valid=True, place_id="hall", score=0.8),
    )
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    _frame(ctx, frame_ts=1.0)
    module.tick(ctx)
    _frame(ctx, frame_ts=2.0)
    module.tick(ctx)

    assert "place_fix" not in ctx, "two frames naming different rooms prove nothing"


def test_the_same_frame_is_not_scored_twice(tmp_path, monkeypatch) -> None:
    calls = _stub_matcher(monkeypatch, MatchResult(valid=False, place_id=None, score=0.1))
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    _frame(ctx, frame_ts=7.0)
    module.tick(ctx)
    module.tick(ctx)

    assert len(calls) == 1, "a frame already scored must not be scored again"


def test_an_unstamped_frame_is_not_scored_twice(tmp_path, monkeypatch) -> None:
    """A publisher that sets only `vision_frame` must still not buy one match per tick (#367)."""
    calls = _stub_matcher(monkeypatch, MatchResult(valid=False, place_id=None, score=0.1))
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    ctx.set("vision_frame", b"frame")
    module.tick(ctx)
    module.tick(ctx)

    assert len(calls) == 1, "object identity is the fallback for a producer with no stamp"


def test_a_new_unstamped_frame_is_still_scored(tmp_path, monkeypatch) -> None:
    """Without a stamp the guard falls back to identity, not to a sentinel (#367).

    The old guard coerced a missing `vision_frame_ts` to `0.0`, so the first frame scored and every
    later one looked identical: one match for the life of the process, while `place_match` kept being
    published as if the module were still looking.
    """
    calls = _stub_matcher(monkeypatch, MatchResult(valid=False, place_id=None, score=0.1))
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)
    ticks = iter([1.0, 2.0, 3.0])
    module._clock = lambda: next(ticks)

    stamps = []
    for index in range(3):
        ctx.set("vision_frame", f"frame-{index}".encode())
        module.tick(ctx)
        stamps.append(ctx.get("place_match")["frame_ts"])

    assert len(calls) == 3
    assert all(stamp is not None for stamp in stamps), (
        "an unstamped frame needs an identity, or localization can never call the fix fresh"
    )
    assert len(set(stamps)) == 3, "each frame's identity has to move with the frame"


def test_a_visit_is_anchored_once(tmp_path, monkeypatch) -> None:
    """Re-anchoring on every pair would keep resetting the origin while the dog stands still."""
    _stub_matcher(monkeypatch, MatchResult(valid=True, place_id="kitchen", score=0.9))
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    for frame_ts in (1.0, 2.0, 3.0, 4.0):
        ctx.set("odometry_reset", False)
        _frame(ctx, frame_ts=frame_ts)
        module.tick(ctx)
        if frame_ts == 2.0:
            assert ctx.get("odometry_reset") is True, "the second agreeing frame is the anchor"
        else:
            assert ctx.get("odometry_reset") is False, f"re-anchored again at frame {frame_ts}"


def test_a_frame_that_cannot_be_read_is_reported(tmp_path, monkeypatch) -> None:
    def explode(frame, views, min_score):
        raise ValueError("a frame must be 2-D grayscale or 3-D BGR")

    monkeypatch.setattr("houndmind_ai.navigation.place_recognition.match_frame", explode)
    ctx = _context(tmp_path)
    module = _module(monkeypatch)
    module.start(ctx)

    _frame(ctx)
    module.tick(ctx)

    published = ctx.get("place_match")
    assert published["valid"] is False
    assert "could not be read" in published["reason"]

