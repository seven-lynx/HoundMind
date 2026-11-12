"""Places: a named pose a user teaches, checked before it is stored or navigated to.

A place is the answer to "go to the kitchen" â€” the feature the design says a user actually wants
(`robot-pet-design.md` Â§6.3, Â§5.2). The pose is **polar from an anchor**, not a map coordinate:
`heading_deg` and `distance_cm` from a named `anchor`, because that is the only pose this stack can
produce. `navigation/` has a heading, the mapper builds a *robot-centric* cell grid, and L0 is
"metres of drift, no loop closure" â€” a Cartesian place would be a number nothing can measure. The
local sequence that reaches a place (orient to the heading, move, re-scan, correct) is exactly what
these two numbers allow.

Three rules carry the design.

1. **A place is created by a person, never inferred.** A place the dog invented is a place the dog
   can be confidently wrong about; `confidence` is stored and shown for that reason, and it may be
   `null` â€” "55 % sure this is the kitchen" is honest, "the kitchen" at 55 % is a lie (Â§6.3).
2. **An id is data a client stores, so a rename must not break it.** The id is a slug of the name at
   creation and never changes; the name is the display string. `kernel/routine.py` makes the same
   split for the same reason.
3. **Every present key is checked for being known.** A typo'd `distance_cm` must not be silently
   ignored, because ignoring it leaves the place at the default and the dog walks somewhere else.
   `Problem` plus `difflib`, the hand-rolled shape `kernel/actions.py` and `kernel/routine.py` use.

Checking is split from loading: `check_*` explains what is wrong with a document, `load_places`
answers the store's question (*which entries may be kept, and what is refused*). Two functions rather
than one because one bad entry must not cost the others â€” the quarantine rule of
`kernel/routine_store.py` applied to a list instead of a directory.

No I/O, no clock, no config at import time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any

from houndmind_ai.kernel.config_schema import Problem

__all__ = [
    "DEFAULT_ANCHOR",
    "MAX_ANCHOR_CHARS",
    "MAX_DISTANCE_CM",
    "MAX_NAME_CHARS",
    "PLACE_KEYS",
    "Place",
    "PlaceLoad",
    "check_place_entry",
    "check_places_document",
    "load_places",
    "normalize_name",
    "parse_place",
    "slug",
]

# The keys a place may carry, in the order `robot-pet-design.md` Â§6.3 writes them. `id` first because
# it is what a client stores; `created_ts` and `visits` last because they are bookkeeping.
PLACE_KEYS: tuple[str, ...] = (
    "id",
    "name",
    "heading_deg",
    "distance_cm",
    "anchor",
    "confidence",
    "created_ts",
    "visits",
)

# The anchor every place starts with: the sonar baseline the mapper already samples. A free string
# rather than an enum, because the set of anchors is the navigation design's to grow.
DEFAULT_ANCHOR = "sonar_baseline"

# A name reaches a log line, an LED cue and a `GET /places` body, so it stays short. 40 characters is
# "the shelf by the window in the front room" with room to spare.
MAX_NAME_CHARS = 40
MAX_ANCHOR_CHARS = 32

# A place is taught from where the dog stands, so the distance is what the sonar reported plus
# however far it walked. 20 m is a sanity bound on a typo, not a range the sensor reaches.
MAX_DISTANCE_CM = 2000.0

# A place id is **not** a file name â€” `kernel/routine.py`'s strict ASCII pattern guards that, because
# there an id is a path. One file holds every place, so this pattern only has to survive a URL path
# segment, and it keeps `\w` so a name typed in a user's own language stays readable instead of being
# mangled to `caf`.
_ID_PATTERN = re.compile(r"^[\w][\w-]{0,63}$")

# Control characters would end a log line early and garble a JSON body. A `\n` in a place name is a
# paste accident, and there is no reading of it that is a name.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def normalize_name(name: str) -> str:
    """The lookup key for a name: trimmed, whitespace collapsed, case folded.

    Two places whose names differ only in case or spacing are the same place to a person, so the
    store refuses the second rather than letting "Kitchen" and "kitchen " both answer.
    """
    return " ".join(name.split()).casefold()


def slug(name: str) -> str:
    """The id a place is created with: lowercase, `_`-joined, at most 64 characters.

    Returns `""` for a name with no characters usable in an id (all punctuation), which the caller
    reports instead of writing a place nobody can address.
    """
    return re.sub(r"[\W_]+", "_", normalize_name(name)).strip("_")[:64]


def _is_number(value: Any) -> bool:
    """True for a JSON number, never for a bool: `True` is an int in Python, not a distance."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value: Any) -> float | None:
    """The value as a float, or None when it is not a JSON number."""
    if not _is_number(value):
        return None
    return float(value)


@dataclass(frozen=True)
class Place:
    """A validated place. Immutable: a visit is a new record the store writes, not a mutation."""

    id: str
    name: str
    heading_deg: float
    distance_cm: float
    anchor: str = DEFAULT_ANCHOR
    confidence: float | None = None
    created_ts: float = 0.0
    visits: int = 0

    def to_dict(self) -> dict[str, object]:
        """The stored form: every key of `PLACE_KEYS`, so a round-trip loses nothing."""
        return {
            "id": self.id,
            "name": self.name,
            "heading_deg": self.heading_deg,
            "distance_cm": self.distance_cm,
            "anchor": self.anchor,
            "confidence": self.confidence,
            "created_ts": self.created_ts,
            "visits": self.visits,
        }


@dataclass(frozen=True)
class PlaceLoad:
    """What a document yields: the entries that survive, and a reason per entry that did not.

    Each refusal is a `Problem` whose path names the entry (`places[2].distance_cm`), so a user
    editing the file is pointed at what to fix rather than told the file is wrong.
    """

    places: tuple[Place, ...] = ()
    refusals: tuple[Problem, ...] = ()


def check_places_document(raw: Any) -> list[Problem]:
    """Every problem with a places file, for a refusal that names what to fix.

    Accepts the stored form (`{"version": 1, "places": [...]}`) and a bare list, because the second
    is what a user copying the design document will write. An empty list means the document may be
    kept as written.
    """
    problems: list[Problem] = []
    entries = _entries(raw, problems)
    if entries is None:
        return problems

    seen_ids: dict[str, int] = {}
    seen_names: dict[str, int] = {}
    for index, entry in enumerate(entries):
        problems.extend(check_place_entry(entry, index))
        _check_unique(entry, index, seen_ids, seen_names, problems)
    return problems


def check_place_entry(entry: Any, index: int) -> list[Problem]:
    """Every problem with one entry, its paths rooted at `places[index]`.

    The index is the position in the file rather than an id, because an entry has to be refusable
    *before* it has a usable id â€” a refusal must be able to name something.
    """
    path = f"places[{index}]"
    problems: list[Problem] = []
    if not isinstance(entry, Mapping):
        return [Problem(path, f"expected a table with a 'name', got {entry!r}")]

    _check_known_keys(entry, PLACE_KEYS, path, problems)

    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append(
            Problem(f"{path}.name", "expected a non-empty string; it is what a user asks for")
        )
    else:
        problems.extend(_check_name_text(name, f"{path}.name"))

    identifier = entry.get("id")
    if identifier is not None:
        if not isinstance(identifier, str) or not identifier.strip():
            problems.append(
                Problem(f"{path}.id", f"expected a non-empty string, got {identifier!r}")
            )
        elif not _ID_PATTERN.match(identifier):
            problems.append(
                Problem(
                    f"{path}.id",
                    f"{identifier!r} is not an id: word characters or '-', at most 64",
                )
            )
    elif isinstance(name, str) and name.strip() and not slug(name):
        problems.append(
            Problem(
                f"{path}.id",
                f"no id can be made from {name!r}; give it one, or use letters, digits, '_' or '-'",
            )
        )

    heading = _number(entry.get("heading_deg"))
    if heading is None:
        problems.append(
            Problem(
                f"{path}.heading_deg",
                f"expected a number in -180..180, got {entry.get('heading_deg')!r}",
            )
        )
    elif not -180.0 <= heading <= 180.0:
        problems.append(
            Problem(
                f"{path}.heading_deg",
                f"{heading!r} is outside -180..180; a bearing is not wrapped for you, because 270 "
                "and -90 are the same direction to you and not obviously to the dog",
            )
        )

    distance = _number(entry.get("distance_cm"))
    if distance is None:
        problems.append(
            Problem(
                f"{path}.distance_cm",
                f"expected a number of centimetres, got {entry.get('distance_cm')!r}",
            )
        )
    elif not 0.0 < distance <= MAX_DISTANCE_CM:
        problems.append(
            Problem(
                f"{path}.distance_cm",
                f"{distance!r} is outside 0..{MAX_DISTANCE_CM:g} cm; a place is taught from where "
                "the dog stands, so this is a typo rather than a measurement",
            )
        )

    anchor = entry.get("anchor")
    if anchor is not None:
        if not isinstance(anchor, str) or not anchor.strip():
            problems.append(
                Problem(f"{path}.anchor", f"expected a non-empty string, got {anchor!r}")
            )
        elif len(anchor.strip()) > MAX_ANCHOR_CHARS:
            problems.append(
                Problem(
                    f"{path}.anchor",
                    f"{len(anchor.strip())} characters; the limit is {MAX_ANCHOR_CHARS}",
                )
            )

    confidence = entry.get("confidence")
    if confidence is not None:
        value = _number(confidence)
        if value is None:
            problems.append(
                Problem(
                    f"{path}.confidence",
                    f"expected a number in 0..1 or null, got {confidence!r}",
                )
            )
        elif not 0.0 <= value <= 1.0:
            problems.append(Problem(f"{path}.confidence", f"{confidence!r} is outside 0..1"))

    created = entry.get("created_ts")
    if created is not None:
        stamp = _number(created)
        if stamp is None or stamp < 0.0:
            problems.append(
                Problem(f"{path}.created_ts", f"expected a timestamp >= 0, got {created!r}")
            )

    visits = entry.get("visits")
    if visits is not None and (
        isinstance(visits, bool) or not isinstance(visits, int) or visits < 0
    ):
        problems.append(Problem(f"{path}.visits", f"expected a whole number >= 0, got {visits!r}"))

    return problems


def parse_place(entry: Any) -> Place | None:
    """Build one place from an entry, or return None when it cannot be built.

    Tolerant by design, like `kernel/actions.py::build_repertoire`: a value it cannot read falls back
    to the field's default instead of raising, because an entry reaches here from a file a user
    edited. Call it after a clean `check_place_entry` â€” what that function reports as an error this
    one will copy without complaint.
    """
    if not isinstance(entry, Mapping):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    clean_name = name.strip()

    identifier = entry.get("id")
    place_id = (
        identifier.strip()
        if isinstance(identifier, str) and identifier.strip()
        else slug(clean_name)
    )
    if not place_id:
        return None

    anchor = entry.get("anchor")
    confidence = entry.get("confidence")
    return Place(
        id=place_id,
        name=clean_name,
        heading_deg=_safe_float(entry.get("heading_deg"), 0.0),
        distance_cm=_safe_float(entry.get("distance_cm"), 0.0),
        anchor=anchor.strip() if isinstance(anchor, str) and anchor.strip() else DEFAULT_ANCHOR,
        confidence=_safe_float(confidence, 0.0) if confidence is not None else None,
        created_ts=_safe_float(entry.get("created_ts"), 0.0),
        visits=_safe_int(entry.get("visits"), 0),
    )


def load_places(raw: Any) -> PlaceLoad:
    """The entries a document can keep, and the reason per entry it cannot.

    The store's salvage pass: an entry that fails `check_place_entry` is refused by index and does
    not cost the others, and two entries claiming one id or name keep the first in file order â€” file
    order is the order the user wrote, so the winner is reproducible and explainable.
    """
    problems: list[Problem] = []
    entries = _entries(raw, problems)
    if entries is None:
        return PlaceLoad(refusals=tuple(problems))

    kept: list[Place] = []
    refusals: list[Problem] = list(problems)
    seen_ids: dict[str, int] = {}
    seen_names: dict[str, int] = {}

    for index, entry in enumerate(entries):
        entry_problems = check_place_entry(entry, index)
        if entry_problems:
            refusals.extend(entry_problems)
            continue
        duplicates: list[Problem] = []
        _check_unique(entry, index, seen_ids, seen_names, duplicates)
        if duplicates:
            refusals.extend(duplicates)
            continue
        place = parse_place(entry)
        if place is None:  # pragma: no cover - a clean entry always parses
            refusals.append(Problem(f"places[{index}]", "passed the check but could not be read"))
            continue
        seen_ids[place.id] = index
        seen_names[normalize_name(place.name)] = index
        kept.append(place)

    return PlaceLoad(places=tuple(kept), refusals=tuple(refusals))


# --------------------------------------------------------------------------- internals


def _entries(raw: Any, problems: list[Problem]) -> list[Any] | None:
    """The entry list from either accepted shape, or None with a problem recorded."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, Mapping):
        _check_known_keys(raw, ("version", "places"), "", problems)
        entries = raw.get("places")
        if isinstance(entries, list):
            return entries
        problems.append(Problem("places", f"expected a list of places, got {entries!r}"))
        return None
    problems.append(
        Problem("places", f"expected a table with a 'places' list, or a bare list, got {raw!r}")
    )
    return None


def _check_name_text(name: str, path: str) -> list[Problem]:
    """The parts of a name that are about the text, not about there being one."""
    clean = name.strip()
    if not clean:
        return []
    problems: list[Problem] = []
    if _CONTROL.search(clean):
        problems.append(
            Problem(path, "contains a control character; a name is one line of printable text")
        )
    if len(clean) > MAX_NAME_CHARS:
        problems.append(Problem(path, f"{len(clean)} characters; the limit is {MAX_NAME_CHARS}"))
    return problems


def _check_unique(
    entry: Any,
    index: int,
    seen_ids: dict[str, int],
    seen_names: dict[str, int],
    problems: list[Problem],
) -> None:
    """Report the second sighting of an id or a name, naming the entry that claimed it first."""
    if not isinstance(entry, Mapping):
        return
    name = entry.get("name")
    if isinstance(name, str) and normalize_name(name):
        key = normalize_name(name)
        earlier = seen_names.get(key)
        if earlier is not None:
            problems.append(
                Problem(
                    f"places[{index}].name",
                    f"{name.strip()!r} is already defined at places[{earlier}]; "
                    "two places cannot answer to one name",
                )
            )
        else:
            seen_names[key] = index

    identifier = entry.get("id")
    place_id = (
        identifier.strip()
        if isinstance(identifier, str) and identifier.strip()
        else slug(name) if isinstance(name, str) else ""
    )
    if not place_id:
        return
    earlier = seen_ids.get(place_id)
    if earlier is not None:
        problems.append(
            Problem(f"places[{index}].id", f"id {place_id!r} is already defined at places[{earlier}]")
        )
    else:
        seen_ids[place_id] = index


def _check_known_keys(
    entry: Mapping[Any, Any], allowed: tuple[str, ...], path: str, problems: list[Problem]
) -> None:
    """Report every key the format does not define, with a suggestion when one is close."""
    for key in entry:
        if not isinstance(key, str):
            problems.append(Problem(path or "places", f"keys must be strings, got {key!r}"))
            continue
        if key in allowed:
            continue
        matches = get_close_matches(key, list(allowed), n=1)
        problems.append(
            Problem(
                f"{path}.{key}" if path else key,
                "unknown key; it would be ignored",
                matches[0] if matches else None,
            )
        )


def _safe_float(value: Any, default: float) -> float:
    """A number from a JSON file or a vendor struct, or the default. Never `float(x)` bare."""
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN compares unequal to itself
        return default
    return number


def _safe_int(value: Any, default: int) -> int:
    """A whole number from a JSON file, or the default."""
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
