"""Which room the dog is in, said with the source that earned the claim (H1).

`mapping/rooms.py` owns the geometry and `localization` owns the pose; this module is the join between
them. It reads the pose chosen this tick - it is registered immediately after `localization`, so that is
the same tick's pose - swaps it **once** into the document frame the rooms are drawn in
(`mapping/home_map.py::runtime_point_to_document`, #347), and publishes `current_room`.

Publishes `current_room`::

    {"id": str | None, "name": str | None, "valid": bool,
     "source": "user_pose" | "place" | "odometry" | None, "reason": str | None}

`source` is the reason the key exists at all. "You are in the Kitchen" from a position a human
confirmed, from a room a camera recognised, and from heading x counted steps are three different
claims, and a consumer that will act on the room has to know which one it was given:

- ``user_pose`` - the `user` tier: someone put the dog there on the console map (M5).
- ``place`` - the `place` tier: `place_recognition` matched a taught view (#297).
- ``odometry`` - any other pose. A `slam` pose is folded in here because it is a measurement too, not
  a confirmed fix - and see the frame rule below for what that costs it.

`valid: false` always carries a `reason`, and the reasons are distinct answers rather than one shrug:

- ``no_pose`` - `localization` is `reactive`, or published no usable pose. A pose missing a coordinate
  is not a pose at the origin.
- ``pose_frame:slam`` - the pose is in SLAM's own coordinates (rtabmap reports metres), not centimetres
  from the odometry origin, so it cannot be tested against a drawing measured in centimetres. Named
  rather than converted: a unit guess is exactly the confident wrong room this key must not give.
- ``no_rooms`` - the home map names no rooms. An empty map is not "outside every room", and a client
  that shows the two as one "unknown" hides a map that was never drawn.
- ``outside_every_room`` - a good pose that no drawn room contains.

Rooms may overlap and the map is not a partition: the first room in document order wins, the rule
`keep_out_room_at` already follows. Nothing here reads `keep_out` - a room the dog must stay out of is
still the room it is standing in - and nothing here moves the dog.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.mapping.home_map import runtime_point_to_document
from houndmind_ai.mapping.rooms import room_at, room_label

__all__ = ["POSE_FRAME", "SOURCE_BY_TIER", "RoomContextModule"]

#: The `source` each localization tier is reported as. `slam` folds into `odometry` because both are
#: measured poses rather than confirmed ones: this key's vocabulary is about how the claim was earned,
#: and a fourth name would split "the dog worked it out" in two without telling a client anything.
SOURCE_BY_TIER: dict[str, str] = {
    "user": "user_pose",
    "place": "place",
    "dead_reckoning": "odometry",
    "slam": "odometry",
}

#: The only frame a pose can be tested in. Rooms are drawn in centimetres from the odometry origin; a
#: `slam` pose is in the backend's own units from the backend's own origin, and no swap between those
#: two exists anywhere in this tree.
POSE_FRAME = "odometry"


def _number(value: Any) -> float | None:
    """A finite float, or `None`. `True` is not a coordinate and NaN is not a position."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _point(pose: Mapping[str, Any]) -> tuple[float, float] | None:
    """A runtime-frame `(forward_cm, left_cm)` from a `localization` pose, or `None`.

    Both numbers must be readable: a pose missing one is not a pose at the origin, which is a real
    place a room can contain.
    """
    forward = _number(pose.get("x"))
    left = _number(pose.get("y"))
    if forward is None or left is None:
        return None
    return forward, left


def _identifier(value: Any) -> str | None:
    """A room's own id as a client can show it, or `None` when it has none."""
    if value is None:
        return None
    return str(value) or None


def _has_rooms(document: Any) -> bool:
    """Does the document name any room at all? This is the distinction `no_rooms` exists for."""
    if not isinstance(document, Mapping):
        return False
    rooms = document.get("rooms")
    if not isinstance(rooms, Sequence) or isinstance(rooms, (str, bytes)):
        return False
    return bool(rooms)


class RoomContextModule(Module):
    """Name the room the pose falls in, and say which pose earned the name."""

    def __init__(
        self, name: str, enabled: bool = True, required: bool = False, **kwargs: object
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)

    def tick(self, context) -> None:
        localization = context.get("localization")
        data = localization if isinstance(localization, Mapping) else {}
        tier = str(data.get("tier") or "")
        source = SOURCE_BY_TIER.get(tier, "odometry")
        pose = data.get("pose")
        if tier == "reactive" or not isinstance(pose, Mapping):
            self._publish(context, None, source=None, reason="no_pose")
            return
        frame = data.get("frame")
        if frame != POSE_FRAME:
            self._publish(context, None, source=source, reason=f"pose_frame:{frame or 'unknown'}")
            return
        point = _point(pose)
        if point is None:
            self._publish(context, None, source=None, reason="no_pose")
            return
        document = context.get("home_map")
        if not _has_rooms(document):
            self._publish(context, None, source=source, reason="no_rooms")
            return
        room = room_at(runtime_point_to_document(point), document)
        if room is None:
            self._publish(context, None, source=source, reason="outside_every_room")
            return
        self._publish(context, room, source=source, reason=None)

    def _publish(
        self,
        context,
        room: Mapping[str, Any] | None,
        *,
        source: str | None,
        reason: str | None,
    ) -> None:
        context.set(
            "current_room",
            {
                "id": None if room is None else _identifier(room.get("id")),
                # `room_label` is the one spelling of a room's name this tree uses, so the console and
                # a refusal in the event log cannot disagree about what the room is called.
                "name": None if room is None else room_label(room),
                "valid": room is not None,
                "source": source,
                "reason": reason,
            },
        )
