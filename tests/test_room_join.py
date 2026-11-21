"""Two rooms drawn on their own, joined through a shared doorway (H7).

The document has carried a `joints` slot since H3; this is the half that reads it. Three claims are
pinned here: a chain of joins puts a second drawing in the first one's centimetres without a second
frame swap (#347), two drawings that disagree about the wall their doorway is cut into are **reported**
and never rewritten, and a join that names a doorway no drawing answers is refused by name. The map is
user data throughout, so a disagreement is a `notes` entry and the document still loads.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from houndmind_ai.mapping.home_map import (
    CURRENT_VERSION,
    JOINT_DISAGREEMENT_TOLERANCE,
    RoomFrames,
    RoomTransform,
    resolve_room_frames,
    validate_document,
)
from tools import map_inspect


def _room(room_id: str, polygon: list[list[float]]) -> dict[str, Any]:
    return {"id": room_id, "polygon": polygon, "source": "user"}


def _joint(**overrides: Any) -> dict[str, Any]:
    """A doorway the two drawings share, and where the hall sits in the kitchen's frame (H7)."""
    entry: dict[str, Any] = {
        "id": "joint_kitchen_hall",
        "a_room": "room_kitchen",
        "a_opening": "door_kitchen",
        "b_room": "room_hall",
        "b_opening": "door_hall",
        "transform": {"translate_cm": [200, 0], "rotation_deg": 0},
    }
    entry.update(overrides)
    return entry


def _document(**overrides: Any) -> dict[str, Any]:
    """Two rooms drawn on their own, each with a doorway cut into one of its own walls."""
    document: dict[str, Any] = {
        "version": CURRENT_VERSION,
        "walls": [
            {"id": "wall_kitchen", "a": [-200, 0], "b": [0, 0], "source": "user"},
            {"id": "wall_hall", "a": [0, 200], "b": [200, 200], "source": "user"},
        ],
        "openings": [
            {"id": "door_kitchen", "a": [-60, 0], "b": [0, 0], "width_cm": 60, "kind": "door"},
            {"id": "door_hall", "a": [100, 200], "b": [160, 200], "width_cm": 60, "kind": "door"},
        ],
        "rooms": [
            _room("room_kitchen", [[-200, 0], [0, 0], [0, 200], [-200, 200]]),
            _room("room_hall", [[0, 200], [200, 200], [200, 400], [0, 400]]),
        ],
        "joints": [_joint()],
    }
    document.update(overrides)
    return document


def _chain_document() -> dict[str, Any]:
    """Kitchen -> hall -> dining, the second join turning the dining room a quarter turn."""
    document = _document()
    document["rooms"].append(_room("room_dining", [[0, 0], [200, 0], [200, 200], [0, 200]]))
    document["walls"].append({"id": "wall_dining", "a": [0, 0], "b": [0, 200], "source": "user"})
    document["openings"].append(
        {"id": "door_dining", "a": [0, 60], "b": [0, 120], "width_cm": 60, "kind": "door"}
    )
    document["joints"].append(
        _joint(
            id="joint_hall_dining",
            a_room="room_hall",
            a_opening="door_hall",
            b_room="room_dining",
            b_opening="door_dining",
            transform={"translate_cm": [0, 120], "rotation_deg": 90},
        )
    )
    return document


def _frames(document: dict[str, Any]) -> RoomFrames:
    """The frames of a document that has to load: a refusal here is a broken fixture, not a case."""
    result = validate_document(document)
    assert result.map is not None, result.problems
    sections = result.map.sections
    return resolve_room_frames(
        sections.get("joints"),
        walls=sections.get("walls"),
        openings=sections.get("openings"),
    )


def test_two_rooms_joined_resolve_to_one_home_frame() -> None:
    """The kitchen is the home frame; the hall is placed in it by the one join between them."""
    frames = _frames(_document())

    kitchen = frames.frame_for("room_kitchen")
    hall = frames.frame_for("room_hall")
    assert kitchen is not None and hall is not None
    assert kitchen.parent is None and kitchen.transform == RoomTransform()
    assert hall.parent == "room_kitchen"
    assert hall.chain == ("joint_kitchen_hall",)
    assert hall.transform.translate_cm == (200.0, 0.0)
    assert hall.transform.rotation_deg == 0.0


def test_a_joined_room_reaches_the_runtime_through_one_swap() -> None:
    """#347: the transform is document arithmetic, and `to_runtime` is the only place axes swap."""
    frames = _frames(_document())

    # 100 cm ahead in the hall's own drawing is 200 cm to the kitchen's left and 100 cm ahead of it.
    assert frames.to_runtime("room_hall", (100.0, 0.0)) == (100.0, 200.0)
    assert frames.to_runtime("room_kitchen", (100.0, 0.0)) == (100.0, 0.0)
    assert frames.to_runtime("room_nobody_drew", (0.0, 0.0)) is None


def test_a_chain_of_two_joins_composes_through_both() -> None:
    """A room two joins away names both, and its own point lands where the two placements put it."""
    frames = _frames(_chain_document())

    dining = frames.frame_for("room_dining")
    assert dining is not None
    assert dining.parent == "room_hall"
    assert dining.chain == ("joint_kitchen_hall", "joint_hall_dining")
    assert dining.transform.translate_cm == pytest.approx((200.0, 120.0))
    assert dining.transform.rotation_deg == pytest.approx(90.0)
    # 100 cm left in the dining room's own drawing is 220 cm ahead and 200 cm left in the home frame.
    assert frames.to_runtime("room_dining", (0.0, 100.0)) == pytest.approx((220.0, 200.0))


def test_a_room_no_join_reaches_keeps_its_own_drawing() -> None:
    """An unjoined room is not given a frame: there is nothing to place it against."""
    document = _document()
    document["rooms"].append(_room("room_attic", [[0, 0], [100, 0], [100, 100], [0, 100]]))

    frames = _frames(document)

    assert set(frames.frames) == {"room_kitchen", "room_hall"}
    assert frames.chain_for("room_attic") == ()
    assert frames.to_runtime("room_attic", (0.0, 0.0)) is None


def test_a_joint_whose_opening_is_missing_is_refused_by_name() -> None:
    """The doorway is the reason the join exists, so a join naming one nobody drew is a refusal."""
    document = _document()
    document["joints"] = [_joint(a_opening="door_nobody_drew")]

    result = validate_document(document)

    assert result.map is None
    problems = " ".join(result.problems)
    assert "door_nobody_drew" in problems
    assert "a_opening" in problems


def test_a_joint_with_no_opening_key_is_refused_by_field() -> None:
    joint = _joint()
    del joint["b_opening"]

    result = validate_document(_document(joints=[joint]))

    assert result.map is None
    assert any("joints[0] has no b_opening" in problem for problem in result.problems)


def test_a_joint_naming_a_room_no_polygon_answers_is_refused() -> None:
    result = validate_document(_document(joints=[_joint(b_room="room_attic")]))

    assert result.map is None
    assert any(
        "room_attic" in problem and "drawn room" in problem for problem in result.problems
    )


def test_a_joint_that_joins_a_room_to_itself_is_refused() -> None:
    result = validate_document(_document(joints=[_joint(b_room="room_kitchen")]))

    assert result.map is None
    assert any("joins room_kitchen to itself" in problem for problem in result.problems)


@pytest.mark.parametrize(
    "transform",
    [None, "east", {"translate_cm": "east"}, {"translate_cm": [200, 0], "rotation_deg": "ninety"}],
)
def test_a_transform_that_does_not_say_where_the_room_sits_is_refused(transform: Any) -> None:
    """A guessed turn would move a room nobody asked to move, so an unreadable one is refused."""
    joint = _joint()
    if transform is None:
        del joint["transform"]
    else:
        joint["transform"] = transform

    result = validate_document(_document(joints=[joint]))

    assert result.map is None
    assert any("transform" in problem for problem in result.problems)


def test_a_disagreement_about_the_shared_wall_is_a_report_not_a_refusal() -> None:
    """Ten percent apart is a note: the two lengths are the user's and neither is rewritten."""
    document = _document()
    document["walls"][1]["b"] = [180, 200]

    result = validate_document(document)

    assert result.map is not None and not result.problems
    note = " ".join(result.notes)
    assert "disagree about the shared wall" in note
    assert "200 cm" in note and "180 cm" in note and "10% apart" in note
    assert result.map.sections["walls"][1]["b"] == [180, 200], "the drawing was rewritten"
    assert result.map.sections["walls"][0]["b"] == [0, 0]


def test_a_difference_inside_the_tolerance_is_not_reported() -> None:
    document = _document()
    document["walls"][1]["b"] = [195, 200]  # 2.5 % shorter than the kitchen's wall

    result = validate_document(document)

    assert result.map is not None
    assert not any("disagree" in note for note in result.notes)
    assert JOINT_DISAGREEMENT_TOLERANCE == 0.05


def test_a_doorway_no_wall_explains_is_not_measured_at_all() -> None:
    """A join that picked the nearest wall would report a disagreement between walls nobody shares."""
    document = _document()
    document["walls"][1]["b"] = [180, 200]
    document["openings"][1]["a"] = [100, 260]
    document["openings"][1]["b"] = [160, 260]

    result = validate_document(document)

    assert result.map is not None
    assert not any("disagree" in note for note in result.notes)

def test_a_second_join_for_the_same_room_keeps_the_first() -> None:
    """Two joins place the hall differently; the first stands, and the second is reported."""
    document = _document()
    document["joints"].append(_joint(id="joint_again", transform={"translate_cm": [900, 0]}))

    frames = _frames(document)

    hall = frames.frame_for("room_hall")
    assert hall is not None
    assert hall.transform.translate_cm == (200.0, 0.0)
    assert any("joint_again" in note and "joint_kitchen_hall" in note for note in frames.notes)


def test_joins_that_close_a_loop_report_and_move_nothing() -> None:
    """Two joins pointing at each other leave no room to start from, so neither drawing is moved."""
    document = _document()
    document["joints"].append(
        _joint(
            id="joint_hall_kitchen",
            a_room="room_hall",
            b_room="room_kitchen",
            a_opening="door_hall",
            b_opening="door_kitchen",
            transform={"translate_cm": [0, 200]},
        )
    )

    frames = _frames(document)

    for room_id in ("room_kitchen", "room_hall"):
        frame = frames.frame_for(room_id)
        assert frame is not None and frame.transform == RoomTransform()
    assert any("close a loop" in note for note in frames.notes)


def test_a_document_written_before_joints_reads_an_empty_list() -> None:
    """A v2 file has no `joints` key at all, and absent is empty rather than a refusal (H3)."""
    result = validate_document({"version": 2, "cells": {"1,2": 3}})

    assert result.map is not None
    assert result.map.sections["joints"] == []
    frames = resolve_room_frames(result.map.sections["joints"])
    assert frames.frames == {} and frames.notes == ()


def test_joints_survive_validation_into_both_spellings() -> None:
    """Joins are user data: the wire shape and the file shape both carry them verbatim."""
    result = validate_document(_document())

    assert result.map is not None
    for document in (result.map.to_document(), result.map.to_file_document()):
        assert document["joints"][0]["a_opening"] == "door_kitchen"
        assert document["joints"][0]["transform"]["translate_cm"] == [200, 0]


def test_a_join_is_resolved_without_the_walls_it_is_measured_against() -> None:
    """The chain needs no geometry; only the disagreement report does."""
    frames = resolve_room_frames([_joint()])

    hall = frames.frame_for("room_hall")
    assert hall is not None and hall.parent == "room_kitchen"
    assert frames.notes == ()


def test_the_resolver_never_raises_on_a_document_nobody_validated() -> None:
    for junk in (None, "joints", 7, [None, {"a_room": 3}, {"a_room": "a", "b_room": "a"}]):
        frames = resolve_room_frames(junk)
        assert frames.frames == {} and frames.notes == ()


def test_map_inspect_prints_the_transform_chain(tmp_path, capsys) -> None:
    path = tmp_path / "joined.json"
    path.write_text(json.dumps(_chain_document()), encoding="utf-8")

    assert map_inspect.main([str(path)]) == 0

    out = capsys.readouterr().out
    assert "joints:   2 joint(s); 3 room(s) placed" in out
    assert "frame:    room_kitchen = the home frame, (0, 0) cm, 0 deg" in out
    assert (
        "frame:    room_hall = room_kitchen through joint_kitchen_hall at (200, 0) cm, 0 deg" in out
    )
    assert (
        "frame:    room_dining = room_hall through joint_kitchen_hall then joint_hall_dining "
        "at (200, 120) cm, 90 deg" in out
    )


def test_map_inspect_reports_a_disagreement_and_still_draws_the_map(tmp_path, capsys) -> None:
    document = _document()
    document["walls"][1]["b"] = [180, 200]
    path = tmp_path / "disagreed.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert map_inspect.main([str(path)]) == 0

    out = capsys.readouterr().out
    assert "frame:    room_hall = room_kitchen through joint_kitchen_hall" in out
    assert "note:" in out
    assert "disagree about the shared wall" in out and "180 cm" in out

