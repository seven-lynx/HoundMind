"""A place is recognised by what it looks like (#296, #301).

The matcher is plain Python, so all of this runs on a workstation with no OpenCV: the descriptors are
synthetic and the questions are the decisions - which place wins, what a refusal says, and what a
frame with nothing to match is told. The ORB path has one guarded test at the end, which runs in CI
where `opencv-contrib-python` is installed.
"""

from __future__ import annotations

import json

import pytest

from houndmind_ai.perception.place_views import (
    DESCRIPTOR_BYTES,
    MIN_DESCRIPTORS,
    THUMB_H,
    THUMB_W,
    PlaceView,
    load_views,
    match,
    save_views,
    score,
    views_path,
)

__all__ = [
    "test_a_featureless_frame_is_refused_before_any_comparison",
    "test_a_view_below_the_descriptor_floor_is_refused",
    "test_a_view_round_trips_through_the_file",
    "test_an_empty_directory_is_no_views_not_an_error",
    "test_below_the_threshold_the_best_score_still_comes_back",
    "test_one_unreadable_view_does_not_cost_the_others",
    "test_the_best_matching_view_wins_and_the_ranking_is_ordered",
]


def _thumb() -> bytes:
    return bytes(range(256)) * (THUMB_W * THUMB_H // 256) + bytes(THUMB_W * THUMB_H % 256)


def _descriptor(seed: int) -> bytes:
    return bytes((seed * 37 + index) % 256 for index in range(DESCRIPTOR_BYTES))


def _view(place_id: str, rows: int = MIN_DESCRIPTORS, offset: int = 0) -> PlaceView:
    return PlaceView(
        place_id=place_id,
        created_at=4212.0,
        thumb=_thumb(),
        keypoints=tuple((float(index), float(index * 2)) for index in range(rows)),
        descriptors=tuple(_descriptor(offset + index) for index in range(rows)),
    )


def test_a_view_round_trips_through_the_file(tmp_path) -> None:
    view = _view("kitchen", rows=MIN_DESCRIPTORS + 4)

    path = save_views(tmp_path, (view,))
    loaded = load_views(tmp_path)

    assert path == views_path(tmp_path)
    assert loaded == (view,), "a save/load pair must lose nothing"


def test_an_empty_directory_is_no_views_not_an_error(tmp_path) -> None:
    assert load_views(tmp_path) == ()


def test_one_unreadable_view_does_not_cost_the_others(tmp_path) -> None:
    """The quarantine rule: one bad entry must not hide the places that are fine."""
    document = {
        "version": 1,
        "views": [
            _view("kitchen").to_dict(),
            {"place_id": "hall", "created_at": 1.0, "thumb": "not base64", "keypoints": [], "descriptors": []},
        ],
    }
    (tmp_path / "views.json").write_text(json.dumps(document), encoding="utf-8")

    loaded = load_views(tmp_path)

    assert [view.place_id for view in loaded] == ["kitchen"]


def test_a_view_below_the_descriptor_floor_is_refused() -> None:
    """A stored view that cannot match is a place nobody can find, so it is refused at construction."""
    with pytest.raises(ValueError, match="cannot match"):
        PlaceView(
            place_id="blank",
            created_at=1.0,
            thumb=_thumb(),
            keypoints=((0.0, 0.0),),
            descriptors=(_descriptor(1),),
        )


def test_the_best_matching_view_wins_and_the_ranking_is_ordered() -> None:
    kitchen = _view("kitchen", rows=MIN_DESCRIPTORS)
    hall = _view("hall", rows=MIN_DESCRIPTORS, offset=100)

    result = match(kitchen.descriptors, (hall, kitchen), 0.8)

    assert result.valid is True
    assert result.place_id == "kitchen"
    assert result.score == pytest.approx(1.0)
    assert [place for place, _score in result.ranked] == ["kitchen", "hall"], "best first"
    assert result.to_dict()["valid"] is True


def test_below_the_threshold_the_best_score_still_comes_back() -> None:
    """A refusal is as informative as a match: it says which place came closest and by how much."""
    kitchen = _view("kitchen", rows=MIN_DESCRIPTORS)
    far_off = tuple(_descriptor(200 + index) for index in range(MIN_DESCRIPTORS))

    result = match(far_off, (kitchen,), 0.99)

    assert result.valid is False
    assert result.place_id is None
    assert 0.0 <= result.score < 0.99
    assert "kitchen" in (result.reason or "")
    assert result.ranked and result.ranked[0][0] == "kitchen"


def test_a_featureless_frame_is_refused_before_any_comparison() -> None:
    """"The wall is blank" and "this is not the kitchen" are different answers."""
    result = match((_descriptor(1),), (_view("kitchen"),), 0.5)

    assert result.valid is False
    assert result.score == 0.0
    assert "featureless" in (result.reason or "")
    assert result.ranked == ()


def test_the_score_is_symmetric_between_a_short_view_and_a_long_frame() -> None:
    view = _view("wall", rows=MIN_DESCRIPTORS)
    frame = view.descriptors + tuple(_descriptor(90 + index) for index in range(MIN_DESCRIPTORS))

    assert score(frame, view) == pytest.approx(1.0), "the smaller set is the denominator"


def test_a_blank_frame_teaches_nothing() -> None:
    """#296: the refusal has to be actionable — "the wall is blank" is what a person can fix."""
    pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    from houndmind_ai.perception.place_views import view_from_frame

    with pytest.raises(ValueError, match="at least"):
        view_from_frame(numpy.full((240, 320, 3), 128, dtype="uint8"), "wall")


def test_a_textured_frame_teaches_a_view_with_a_thumbnail() -> None:
    pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    from houndmind_ai.perception.place_views import view_from_frame

    rng = numpy.random.default_rng(7)
    frame = rng.integers(0, 255, (240, 320, 3)).astype("uint8")

    view = view_from_frame(frame, "kitchen", now=42.0)

    assert view.place_id == "kitchen"
    assert view.created_at == 42.0
    assert len(view.thumb) == THUMB_W * THUMB_H
    assert len(view.descriptors) == len(view.keypoints) >= MIN_DESCRIPTORS
