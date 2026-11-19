"""The room the dog can name, and the four answers when it cannot (H1).

The point of these is the distinction: "no pose", "a pose in the wrong units", "a map with no rooms"
and "a pose outside every room" are four different states, and a key that collapsed them into one
`valid: false` would tell a client "unknown" when the truth is "your map is empty".
"""

from __future__ import annotations

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.navigation.room_context import RoomContextModule

KITCHEN = [[0, 0], [400, 0], [400, 300], [0, 300]]
# A room on the left-hand side of the document. `forward_cm` 50 / `left_cm` 250 is inside it *after*
# the swap and outside it without one, which is what makes the frame test able to fail (#347).
LEFT_ROOM = [[200, 0], [300, 0], [300, 100], [200, 100]]


def _document(*rooms: dict) -> dict:
    return {"rooms": list(rooms)}


def _tick(document, *, tier="dead_reckoning", frame="odometry", pose=None):
    context = RuntimeContext()
    if document is not None:
        context.set("home_map", document)
    context.set("localization", {"tier": tier, "frame": frame, "pose": pose, "confidence": 0.9})
    RoomContextModule("room_context").tick(context)
    return context.get("current_room")


def test_a_pose_inside_the_kitchen_names_the_kitchen() -> None:
    room = _tick(
        _document({"id": "kitchen", "name": "Kitchen", "polygon": KITCHEN}),
        pose={"x": 150.0, "y": 200.0, "yaw_deg": 0.0},
    )

    assert room == {
        "id": "kitchen",
        "name": "Kitchen",
        "valid": True,
        "source": "odometry",
        "reason": None,
    }


def test_a_pose_outside_every_room_says_so() -> None:
    room = _tick(
        _document({"id": "kitchen", "name": "Kitchen", "polygon": KITCHEN}),
        pose={"x": 900.0, "y": 900.0},
    )

    assert room["valid"] is False
    assert room["reason"] == "outside_every_room"
    assert room["id"] is None and room["name"] is None


def test_an_empty_map_is_not_the_same_answer_as_being_outside() -> None:
    room = _tick(_document(), pose={"x": 10.0, "y": 10.0})

    assert room["valid"] is False
    assert room["reason"] == "no_rooms"


def test_a_missing_map_is_no_rooms_too() -> None:
    assert _tick(None, pose={"x": 10.0, "y": 10.0})["reason"] == "no_rooms"


def test_the_runtime_pose_is_swapped_before_the_polygon_test() -> None:
    """Without `runtime_point_to_document` this pose lands in the neighbouring room (#347)."""
    room = _tick(
        _document({"id": "den", "name": "Den", "polygon": LEFT_ROOM}),
        pose={"x": 50.0, "y": 250.0},
    )

    assert room["valid"] is True
    assert room["name"] == "Den"


def test_the_source_is_the_tier_that_earned_the_pose() -> None:
    document = _document({"id": "kitchen", "name": "Kitchen", "polygon": KITCHEN})
    pose = {"x": 150.0, "y": 200.0}

    assert _tick(document, tier="user", pose=dict(pose))["source"] == "user_pose"
    assert _tick(document, tier="place", pose=dict(pose))["source"] == "place"
    assert _tick(document, tier="dead_reckoning", pose=dict(pose))["source"] == "odometry"


def test_a_slam_pose_is_named_but_not_tested_against_the_drawing() -> None:
    """rtabmap reports metres; testing one against a centimetre drawing invents a confident room."""
    room = _tick(
        _document({"id": "kitchen", "name": "Kitchen", "polygon": KITCHEN}),
        tier="slam",
        frame="slam",
        pose={"x": 1.5, "y": 2.0},
    )

    assert room["valid"] is False
    assert room["reason"] == "pose_frame:slam"
    assert room["source"] == "odometry", "a slam pose is a measurement, not a fourth source"


def test_no_pose_at_all_is_no_pose() -> None:
    room = _tick(
        _document({"id": "kitchen", "name": "Kitchen", "polygon": KITCHEN}),
        tier="reactive",
        frame=None,
        pose=None,
    )

    assert room == {"id": None, "name": None, "valid": False, "source": None, "reason": "no_pose"}


def test_a_pose_with_an_unreadable_coordinate_is_not_the_origin() -> None:
    room = _tick(
        _document({"id": "kitchen", "name": "Kitchen", "polygon": KITCHEN}),
        pose={"x": "forward", "y": 200.0},
    )

    assert room["valid"] is False
    assert room["reason"] == "no_pose"


def test_a_keep_out_room_is_still_named() -> None:
    """Keep-out is a rule about walking, not about where the dog is standing."""
    room = _tick(
        _document({"id": "stairs", "name": "Stairs", "polygon": KITCHEN, "keep_out": True}),
        pose={"x": 150.0, "y": 200.0},
    )

    assert room["valid"] is True
    assert room["name"] == "Stairs"


def test_overlapping_rooms_answer_the_first_one_drawn() -> None:
    """The map is not a partition, so the rule is the same first-match-wins as `keep_out_room_at`."""
    room = _tick(
        _document(
            {"id": "hall", "name": "Hall", "polygon": KITCHEN},
            {"id": "kitchen", "name": "Kitchen", "polygon": KITCHEN},
        ),
        pose={"x": 150.0, "y": 200.0},
    )

    assert room["name"] == "Hall"


def test_the_key_carries_exactly_the_five_fields() -> None:
    room = _tick(
        _document({"id": "kitchen", "name": "Kitchen", "polygon": KITCHEN}),
        pose={"x": 150.0, "y": 200.0},
    )

    assert set(room) == {"id", "name", "valid", "source", "reason"}
