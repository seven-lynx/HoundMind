"""The places file: a bad entry is refused by index and never costs the others.

A place is user data a person typed, so every test here is about the quarantine rule: one broken
entry must not stop a dog from booting, a corrupt file must not be silently rewritten, and the entry
a user has to fix must be named in the report. The files are written into `tmp_path` the way a user
would write them, and the shipped `settings.jsonc` is loaded once to prove the config key names the
same default the store does.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.place import (
    DEFAULT_ANCHOR,
    MAX_NAME_CHARS,
    Place,
    check_places_document,
    normalize_name,
    slug,
)
from houndmind_ai.kernel.place_store import (
    DEFAULT_PLACES_PATH,
    MAX_FILE_BYTES,
    MAX_PLACES,
    PlaceStore,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "config" / "settings.jsonc"

CREATED = 1_700_000_000.0


def store(tmp_path: Path, **kwargs) -> PlaceStore:
    """A store on a path inside `tmp_path`, with a fixed clock so `created_ts` is assertable."""
    return PlaceStore(tmp_path / "places.json", clock=lambda: CREATED, **kwargs)


def entry(**overrides) -> dict:
    """One valid place, spelled the way the design document writes it."""
    doc: dict = {
        "name": "kitchen",
        "heading_deg": 92.0,
        "distance_cm": 310.0,
        "anchor": DEFAULT_ANCHOR,
        "confidence": 0.55,
        "created_ts": 0,
        "visits": 3,
    }
    doc.update(overrides)
    return doc


def written(path: Path, payload: object) -> Path:
    """Write a places file the way a user would."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ------------------------------------------------------------- a file and nothing else


def test_a_missing_file_is_an_empty_report_and_is_not_created(tmp_path: Path) -> None:
    """A fresh install has no places and still boots; a read must not create the file."""
    subject = store(tmp_path)
    report = subject.load()

    assert report.places == ()
    assert report.refusals == ()
    assert report.ids() == ()
    assert not subject.path.exists()


def test_a_missing_parent_directory_is_still_empty(tmp_path: Path) -> None:
    """`~/.houndmind` may not exist yet; that is not a reason to refuse to start."""
    nested = tmp_path / "houndmind" / "places.json"
    report = PlaceStore(nested).load()

    assert report.places == ()
    assert not nested.parent.exists()


def test_a_valid_file_round_trips_every_field(tmp_path: Path) -> None:
    """Every key of the format survives a read, and the model is immutable."""
    subject = store(tmp_path)
    written(subject.path, {"version": 1, "places": [entry(id="kitchen")]})

    (place,) = subject.load().places

    assert place == Place(
        id="kitchen",
        name="kitchen",
        heading_deg=92.0,
        distance_cm=310.0,
        anchor=DEFAULT_ANCHOR,
        confidence=0.55,
        created_ts=0.0,
        visits=3,
    )
    assert place.to_dict() == entry(id="kitchen")
    with pytest.raises(FrozenInstanceError):
        place.name = "hall"  # type: ignore[misc]


def test_the_stored_shape_and_a_bare_list_are_both_accepted(tmp_path: Path) -> None:
    """The wrapped form is what this store writes; a bare list is what a user copies by hand."""
    subject = store(tmp_path)
    written(subject.path, [entry()])
    assert subject.load().ids() == ("kitchen",)

    written(subject.path, {"version": 1, "places": [entry(name="hall", id="hall")]})
    assert subject.load().ids() == ("hall",)


def test_unknown_keys_are_reported_rather_than_ignored(tmp_path: Path) -> None:
    """A typo'd `distance` must not leave the place at the default and the dog elsewhere."""
    problems = check_places_document({"places": [entry(distance=310.0)]})

    assert [problem.path for problem in problems] == ["places[0].distance"]


def test_one_bad_entry_does_not_cost_the_others(tmp_path: Path) -> None:
    """The salvage pass: the good entry loads, the bad one is refused by index."""
    subject = store(tmp_path)
    written(
        subject.path,
        {"version": 1, "places": [entry(), entry(name="hall", distance_cm=0)]},
    )

    report = subject.load()

    assert report.ids() == ("kitchen",)
    assert [problem.path for problem in report.refusals] == ["places[1].distance_cm"]
    assert report.refused == 1


def test_a_duplicate_name_in_the_file_keeps_the_first(tmp_path: Path) -> None:
    """File order is the order the user wrote, so the winner is reproducible and explainable."""
    subject = store(tmp_path)
    written(
        subject.path,
        {
            "version": 1,
            "places": [entry(), entry(name="Kitchen ", heading_deg=10.0)],
        },
    )

    report = subject.load()

    assert len(report.places) == 1
    assert report.places[0].heading_deg == 92.0
    assert "already defined at places[0]" in str(report.refusals[0])


def test_a_corrupt_file_is_one_refusal_and_the_bytes_are_untouched(tmp_path: Path) -> None:
    """Not JSON at all: report it, keep nothing, and leave the file for the user to fix."""
    subject = store(tmp_path)
    subject.path.write_text("{not json", encoding="utf-8")

    report = subject.load()

    assert report.places == ()
    assert len(report.refusals) == 1
    assert "not valid JSON" in str(report.refusals[0])
    assert subject.path.read_text(encoding="utf-8") == "{not json"


def test_a_write_over_a_partly_refused_file_backs_it_up_first(tmp_path: Path) -> None:
    """The one guard the routine store never needed: this store can write over a file it half read."""
    subject = store(tmp_path)
    original = json.dumps(
        {"version": 1, "places": [entry(), entry(name="hall", heading_deg=999)]}
    )
    subject.path.write_text(original, encoding="utf-8")

    place, problems = subject.add("garage", heading_deg=0.0, distance_cm=120.0)

    assert problems == ()
    assert place is not None
    backup = subject.path.with_suffix(".bak")
    assert backup.read_text(encoding="utf-8") == original, "the user's typo is recoverable"
    assert subject.load().ids() == ("kitchen", "garage")


def test_a_clean_file_is_not_backed_up(tmp_path: Path) -> None:
    """The backup is for a file that had something to lose, not for every write."""
    subject = store(tmp_path)
    written(subject.path, {"version": 1, "places": [entry()]})

    subject.add("hall", heading_deg=0.0, distance_cm=120.0)

    assert not subject.path.with_suffix(".bak").exists()


def test_a_bom_is_tolerated(tmp_path: Path) -> None:
    """A Windows editor leaves one behind, and `utf-8-sig` decodes plain UTF-8 unchanged."""
    subject = store(tmp_path)
    subject.path.write_text(
        "\ufeff" + json.dumps({"version": 1, "places": [entry()]}), encoding="utf-8"
    )

    assert subject.load().ids() == ("kitchen",)


def test_an_oversized_file_is_refused(tmp_path: Path) -> None:
    """One enormous or accidentally binary file must not be read into memory at boot."""
    subject = store(tmp_path)
    subject.path.write_text("[" + "0" * (MAX_FILE_BYTES + 1) + "]", encoding="utf-8")

    report = subject.load()

    assert report.places == ()
    assert "the limit is" in str(report.refusals[0])


def test_an_unreadable_file_is_refused_with_its_reason(tmp_path: Path) -> None:
    """A permission denied is the failure a test cannot provoke portably, so the seam supplies it."""

    def denied(path: Path) -> str:
        raise OSError("permission denied")

    subject = store(tmp_path, read_text=denied)
    written(subject.path, {"version": 1, "places": [entry()]})

    report = subject.load()

    assert report.places == ()
    assert "could not be read" in str(report.refusals[0])


# ------------------------------------------------------------- creating and forgetting


def test_add_writes_the_file_and_a_second_store_sees_it(tmp_path: Path) -> None:
    """Persistence is the whole point: a place taught once is a place after a reboot."""
    subject = store(tmp_path)
    place, problems = subject.add(
        "The Kitchen", heading_deg=92.0, distance_cm=310.0, confidence=0.55
    )

    assert problems == ()
    assert place is not None
    assert (place.id, place.created_ts, place.visits) == ("the_kitchen", CREATED, 0)
    (reloaded,) = PlaceStore(subject.path).load().places
    assert reloaded == place


def test_add_refuses_a_duplicate_name_ignoring_case_and_spacing(tmp_path: Path) -> None:
    """Two places whose names differ only in case are one place to a person, so the second is refused."""
    subject = store(tmp_path)
    subject.add("Kitchen", heading_deg=0.0, distance_cm=100.0)
    before = subject.path.read_text(encoding="utf-8")

    place, problems = subject.add(" kitchen ", heading_deg=10.0, distance_cm=50.0)

    assert place is None
    assert "already defined" in str(problems[0])
    assert subject.path.read_text(encoding="utf-8") == before, "a refused add writes nothing"


def test_add_refuses_a_heading_outside_the_range(tmp_path: Path) -> None:
    """270 is the same direction as -90 to a person; wrapping it for them hides a real mistake."""
    subject = store(tmp_path)

    place, problems = subject.add("hall", heading_deg=270.0, distance_cm=100.0)

    assert place is None
    assert problems[0].path == "places[0].heading_deg"


def test_add_refuses_a_name_no_id_can_be_made_from(tmp_path: Path) -> None:
    """A place nobody can address is not a place, and a silent empty id would be unfindable."""
    subject = store(tmp_path)

    place, problems = subject.add("!!!", heading_deg=0.0, distance_cm=100.0)

    assert place is None
    assert problems[0].path == "places[0].id"


def test_add_refuses_a_name_longer_than_the_limit(tmp_path: Path) -> None:
    """A name reaches a log line and an LED cue, so it stays one short line."""
    subject = store(tmp_path)

    place, problems = subject.add("x" * (MAX_NAME_CHARS + 1), heading_deg=0.0, distance_cm=100.0)

    assert place is None
    assert problems[0].path == "places[0].name"


def test_the_cap_refuses_one_place_too_many(tmp_path: Path) -> None:
    """A runaway client is stopped at the store, not by a file the device cannot read."""
    subject = store(tmp_path)
    written(
        subject.path,
        {"version": 1, "places": [entry(name=f"place {i}") for i in range(MAX_PLACES)]},
    )

    place, problems = subject.add("one more", heading_deg=0.0, distance_cm=100.0)

    assert place is None
    assert "the limit is" in str(problems[0])


def test_remove_deletes_one_place_and_persists(tmp_path: Path) -> None:
    subject = store(tmp_path)
    subject.add("kitchen", heading_deg=0.0, distance_cm=100.0)
    subject.add("hall", heading_deg=10.0, distance_cm=200.0)

    removed, problems = subject.remove("hall")

    assert problems == ()
    assert removed is not None and removed.name == "hall"
    assert PlaceStore(subject.path).load().ids() == ("kitchen",)


def test_remove_of_an_unknown_handle_is_a_refusal_not_a_silent_success(tmp_path: Path) -> None:
    """`DELETE /places/{id}` twice must be visibly a no-op: the second call removes nothing."""
    subject = store(tmp_path)
    subject.add("kitchen", heading_deg=0.0, distance_cm=100.0)

    removed, problems = subject.remove("kitchen")
    again, second_problems = subject.remove("kitchen")

    assert removed is not None and problems == ()
    assert again is None
    assert "no place with id or name" in str(second_problems[0])


def test_remove_accepts_a_name_as_well_as_an_id(tmp_path: Path) -> None:
    """Someone typing "Kitchen" is not wrong about the place, only about the handle."""
    subject = store(tmp_path)
    subject.add("The Kitchen", heading_deg=0.0, distance_cm=100.0)

    removed, problems = subject.remove("The Kitchen")

    assert problems == ()
    assert removed is not None and removed.id == "the_kitchen"


def test_no_tmp_file_is_left_behind_after_a_write(tmp_path: Path) -> None:
    """A crash between the write and the rename is the only case a `.tmp` may survive."""
    subject = store(tmp_path)
    subject.add("kitchen", heading_deg=0.0, distance_cm=100.0)

    assert not subject.path.with_suffix(".tmp").exists()


def test_the_shipped_config_points_at_the_store_default() -> None:
    """The key in `settings.jsonc` and the constant in the store must not drift apart."""
    settings = load_config(SETTINGS_FILE).settings

    assert settings["places"]["path"] == DEFAULT_PLACES_PATH
    assert PlaceStore(settings["places"]["path"]).path.is_absolute()


def test_slug_and_normalize_name() -> None:
    assert slug("The Kitchen") == "the_kitchen"
    assert slug("  Front  Room ") == "front_room"
    assert slug("!!!") == ""
    assert normalize_name(" Kitchen  ") == "kitchen"




# ------------------------------------------------------------------ visits and confidence


def stored_place(**overrides) -> Place:
    """A validated place, so `after_visit` can be reasoned about without a file."""
    body = {"name": "Kitchen", "heading_deg": 90.0, "distance_cm": 310.0, **overrides}
    return Place(
        id="kitchen",
        name=body["name"],
        heading_deg=body["heading_deg"],
        distance_cm=body["distance_cm"],
        anchor=body.get("anchor", DEFAULT_ANCHOR),
        confidence=body.get("confidence"),
        created_ts=CREATED,
        visits=body.get("visits", 0),
    )


def test_an_arrival_counts_a_visit_and_starts_a_confidence() -> None:
    """One arrival is one measurement: the first confidence is `step`, not a hopeful 1.0."""
    after = stored_place().after_visit(arrived=True)
    assert after.visits == 1
    assert after.confidence == pytest.approx(0.1)


def test_a_measured_confidence_climbs_to_one_and_stops() -> None:
    after = stored_place(confidence=0.95, visits=4).after_visit(arrived=True)
    assert after.confidence == 1.0
    assert after.visits == 5


def test_a_failed_approach_decays_a_measured_confidence_only() -> None:
    """A blocked path is not evidence about the place: unmeasured stays unmeasured."""
    assert stored_place(confidence=0.5).after_visit(arrived=False).confidence == pytest.approx(0.4)
    assert stored_place(confidence=0.05).after_visit(arrived=False).confidence == 0.0
    assert stored_place().after_visit(arrived=False).confidence is None
    assert stored_place(confidence=0.5).after_visit(arrived=False).visits == 0


def test_the_store_persists_a_visit_once_and_names_an_unknown_place(tmp_path: Path) -> None:
    places = store(tmp_path)
    places.add(name="Kitchen", heading_deg=90.0, distance_cm=310.0)

    updated, problems = places.record_visit("kitchen", arrived=True)
    assert problems == ()
    assert updated is not None and updated.visits == 1
    assert json.loads((tmp_path / "places.json").read_text(encoding="utf-8"))["places"][0][
        "visits"
    ] == 1

    missing, refusal = places.record_visit("garage", arrived=True)
    assert missing is None and refusal, "an unknown handle is a reason, never a silent success"

