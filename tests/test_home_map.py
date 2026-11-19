"""The home map: the format in both directions, and the mapper that now uses both.

The defect these hold still: `save_home_map` persisted a sample log with no grid in it, and nothing
ever loaded the file, so the dog could not remember a room across a restart (#286).
"""

from __future__ import annotations

import json

import pytest

from houndmind_ai.mapping.home_map import (
    CURRENT_VERSION,
    build_document,
    load_home_map,
    validate_document,
    write_document,
)
from houndmind_ai.mapping.mapper import MappingModule, nearest_wall


class _Context:
    """The smallest context the module reads and writes."""

    def __init__(self, values: dict | None = None) -> None:
        self.values = dict(values or {})

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def set(self, key: str, value) -> None:
        self.values[key] = value


def _write(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_document_carries_the_grid_and_the_sweep_not_only_samples() -> None:
    state = {
        "samples": [{"timestamp": 5.0, "distance_cm": 30}],
        "grid": {"cells": {"1,2": 3}},
        "last_sweep": {"angles": {"0": 120.0, "-30": -1.0, "30": 0}},
    }

    document = build_document(state, {"cell_size_cm": 10}, now=10.0)

    assert document["version"] == CURRENT_VERSION
    assert document["grid"]["cells"] == {"1,2": 3}
    # -1 is "no echo" and 0 is "no sample": neither is a distance, so neither becomes a cell.
    assert document["sweep"] == {"0": 120.0}
    assert document["meta"]["saved_at"] == 10.0
    assert len(document["samples"]) == 1


def test_build_document_caps_the_grid_and_says_it_did() -> None:
    cells = {f"{index},0": index for index in range(1, 6)}

    document = build_document({"grid": {"cells": cells}}, {"home_map_max_cells": 2})

    assert document["meta"]["cells_truncated"] is True
    assert document["grid"]["cells"] == {"5,0": 5, "4,0": 4}


def test_write_then_load_round_trips_and_leaves_no_temp_file(tmp_path) -> None:
    path = tmp_path / "home_map.json"
    document = build_document(
        {"grid": {"cells": {"2,3": 7}}, "samples": [{"timestamp": 1.0}]}, {}, now=1.0
    )

    write_document(path, document)
    result = load_home_map(path)

    assert result.ok and result.map is not None
    assert result.map.cells == {"2,3": 7}
    assert result.map.cell_size_cm == 10.0
    assert result.map.grid_size == (100, 100)
    assert sorted(item.name for item in tmp_path.iterdir()) == ["home_map.json"]


def test_a_missing_file_is_a_reason_not_a_crash(tmp_path) -> None:
    result = load_home_map(tmp_path / "absent.json")

    assert result.map is None
    assert result.problems == ()
    assert result.reason and "no home map" in result.reason


def test_malformed_json_names_the_problem(tmp_path) -> None:
    path = tmp_path / "home_map.json"
    path.write_text("{ this is not json", encoding="utf-8")

    result = load_home_map(path)

    assert result.map is None
    assert result.problems and "not JSON" in result.problems[0]


def test_a_byte_order_mark_is_read_not_blamed_on_the_json(tmp_path) -> None:
    """A backup a Windows editor has saved carries a BOM, and `json.loads` refuses it (#361)."""
    path = tmp_path / "home_map.json"
    document = json.dumps({"version": CURRENT_VERSION, "grid": {"cells": {}}})
    path.write_text("\ufeff" + document, encoding="utf-8")

    result = load_home_map(path)

    assert result.map is not None, result.problems
    assert result.problems == ()


def test_a_newer_version_is_refused_rather_than_guessed(tmp_path) -> None:
    path = tmp_path / "home_map.json"
    _write(path, {"version": CURRENT_VERSION + 1, "grid": {"cells": {}}})

    result = load_home_map(path)

    assert result.map is None
    assert result.problems and "reads up to" in result.problems[0]
    assert result.reason == "newer format"



def test_a_pre_grid_file_loads_as_samples_only_with_a_note(tmp_path) -> None:
    path = tmp_path / "home_map.json"
    _write(path, {"meta": {"saved_at": 1.0, "cell_size_cm": 10}, "samples": [{"timestamp": 1.0}]})

    result = load_home_map(path)

    assert result.ok and result.map is not None
    assert result.map.cells == {}
    assert any("pre-grid" in note for note in result.notes)


def test_entries_that_are_not_cells_are_dropped_with_a_note(tmp_path) -> None:
    path = tmp_path / "home_map.json"
    _write(
        path,
        {
            "version": CURRENT_VERSION,
            "meta": {},
            "grid": {"cells": {"1,2": 2, "nope": 5, "3,4": 0}},
        },
    )

    result = load_home_map(path)

    assert result.ok and result.map is not None
    assert result.map.cells == {"1,2": 2}
    assert any("dropped" in note for note in result.notes)


def test_a_scan_save_keeps_the_rev_and_the_users_sections() -> None:
    """A snapshot every 30 s must not erase an edit or invalidate the `rev` behind it (M1)."""
    previous = {
        "version": CURRENT_VERSION,
        "meta": {"rev": 4, "created_at": 1.0},
        "cells": {"9,9": 1},
        "rooms": [{"id": "r1", "name": "kitchen"}],
        "dog": {"x_cm": 10, "y_cm": 20},
    }

    document = build_document({"grid": {"cells": {"1,1": 2}}}, {}, now=50.0, previous=previous)

    assert document["meta"]["rev"] == 4
    assert document["meta"]["created_at"] == 1.0
    assert document["meta"]["updated_at"] == 50.0
    assert document["meta"]["source"] == "scan"
    assert document["rooms"] == [{"id": "r1", "name": "kitchen"}]
    assert document["dog"] == {"x_cm": 10, "y_cm": 20}
    assert document["grid"]["cells"] == {"1,1": 2}, "the scan owns the cells"


def test_a_scan_save_keeps_the_scale_source() -> None:
    """A dimension a person typed is user data, and `meta` is the one dict a scan rebuilds (H2)."""
    previous = {
        "version": CURRENT_VERSION,
        "meta": {"rev": 4, "created_at": 1.0, "scale_source": "user"},
        "cells": {"9,9": 1},
        "rooms": [{"id": "r1", "name": "kitchen", "size_cm": {"width_cm": 200, "depth_cm": 150}}],
    }

    document = build_document({"grid": {"cells": {"1,1": 2}}}, {}, now=50.0, previous=previous)

    assert document["meta"]["scale_source"] == "user"
    assert document["rooms"][0]["size_cm"] == {"width_cm": 200, "depth_cm": 150}


def test_a_scan_save_never_invents_a_scale() -> None:
    """No claim in, no claim out: a snapshot that defaults this would measure rooms nobody measured."""
    previous = {"version": CURRENT_VERSION, "meta": {"rev": 1, "created_at": 1.0}, "cells": {}}

    document = build_document({"grid": {"cells": {}}}, {}, now=50.0, previous=previous)

    assert "scale_source" not in document["meta"]


def test_validate_document_reads_both_spellings_of_the_cells() -> None:
    """The wire is flat and the file nests under `grid`; one validator has to read both (M1)."""
    wire = validate_document({"version": CURRENT_VERSION, "cells": {"1,2": 3}})
    stored = validate_document({"version": CURRENT_VERSION, "grid": {"cells": {"1,2": 3}}})

    assert wire.map is not None and stored.map is not None
    assert wire.map.cells == stored.map.cells == {"1,2": 3}
    assert stored.map.to_document()["cells"] == {"1,2": 3}
    assert stored.map.to_file_document()["grid"]["cells"] == {"1,2": 3}
    assert "cells" not in stored.map.to_file_document()


def test_validate_document_refuses_a_section_it_could_not_keep() -> None:
    result = validate_document({"version": CURRENT_VERSION, "walls": "drawn"})

    assert result.map is None
    assert result.problems and "walls must be a list of objects" in result.problems[0]


def _object(**overrides) -> dict:
    """A counter against a 200 cm wall, the shape the console writes (H3)."""
    entry = {
        "id": "obj_sink",
        "wall_id": "wall_kitchen",
        "start_cm": 20,
        "width_cm": 60,
        "depth_cm": 50,
        "kind": "counter",
        "source": "user",
    }
    entry.update(overrides)
    return entry


def _wall_map(**overrides) -> dict:
    document = {
        "version": CURRENT_VERSION,
        "walls": [{"id": "wall_kitchen", "a": [0, 0], "b": [200, 0], "source": "user"}],
        "objects": [_object()],
    }
    document.update(overrides)
    return document


def test_objects_survive_validation_into_both_spellings() -> None:
    """Objects are user data: the wire shape and the file shape both carry them verbatim (H3)."""
    result = validate_document(_wall_map())

    assert result.map is not None
    for document in (result.map.to_document(), result.map.to_file_document()):
        assert document["objects"][0]["wall_id"] == "wall_kitchen"
        assert document["objects"][0]["width_cm"] == 60
    assert result.map.sections["joints"] == [], "a v3 section nobody wrote yet is empty, not absent"


def test_objects_longer_than_their_wall_name_the_walls_length() -> None:
    """A clamp would draw furniture through the next room; the answer is a problem, by name."""
    result = validate_document(_wall_map(objects=[_object(start_cm=180, width_cm=60)]))

    assert result.map is None
    assert result.problems and "which is 200 cm long" in result.problems[0]


def test_objects_name_a_wall_and_a_kind_the_document_knows() -> None:
    result = validate_document(
        _wall_map(objects=[_object(wall_id="wall_nobody_drew", kind="hot_tub")])
    )

    assert result.map is None
    problems = " ".join(result.problems)
    assert "wall_nobody_drew" in problems
    # The vocabulary is closed, because nothing downstream may parse prose.
    assert "other" in problems


def test_a_document_written_before_objects_reads_an_empty_list() -> None:
    """A v2 file has no `objects` key at all, and absent is empty rather than a refusal (H3)."""
    result = validate_document({"version": 2, "cells": {"1,2": 3}})

    assert result.map is not None
    assert result.map.sections["objects"] == []
    assert result.map.to_document()["objects"] == []
    assert result.map.to_file_document()["joints"] == []


def test_start_without_a_configured_path_says_so() -> None:
    context = _Context({"settings": {"mapping": {}}})

    MappingModule("mapping").start(context)

    status = context.get("home_map_status")
    assert status["loaded"] is False
    assert "home_map_load_path" in status["reason"]


def test_a_broken_file_does_not_disable_the_module(tmp_path) -> None:
    path = tmp_path / "home_map.json"
    path.write_text("{oops", encoding="utf-8")
    context = _Context({"settings": {"mapping": {"home_map_load_path": str(path)}}})
    module = MappingModule("mapping")

    module.start(context)

    status = context.get("home_map_status")
    assert status["loaded"] is False and status["problems"]
    assert module.status.enabled is True


def test_start_loads_and_the_first_tick_seeds_the_grid(tmp_path) -> None:
    path = tmp_path / "home_map.json"
    write_document(path, build_document({"grid": {"cells": {"2,0": 4}}}, {}))
    context = _Context({"settings": {"mapping": {"home_map_load_path": str(path)}}})
    module = MappingModule("mapping")

    module.start(context)
    assert context.get("home_map_status")["loaded"] is True
    assert context.get("home_map")["cells"] == {"2,0": 4}

    module.tick(context)

    state = context.get("mapping_state")
    assert state["grid"]["cells"] == {"2,0": 4}
    # The point of loading it: the geometry queries answer from the persisted map. Cell (2,0) is
    # 20 cm to the dog's left, so that is the nearest wall after a restart.
    assert nearest_wall(state["grid"], (0.0, 0.0), 100.0) == pytest.approx(20.0)


def test_a_live_grid_wins_over_the_loaded_one(tmp_path) -> None:
    path = tmp_path / "home_map.json"
    write_document(path, build_document({"grid": {"cells": {"2,0": 4}}}, {}))
    context = _Context(
        {
            "settings": {"mapping": {"home_map_load_path": str(path)}},
            "mapping_state": {"samples": [], "grid": {"cells": {"0,9": 1}}},
        }
    )
    module = MappingModule("mapping")

    module.start(context)
    module.tick(context)

    # Merging would double every hit this process shares with the file, so the live grid stands.
    assert context.get("mapping_state")["grid"]["cells"] == {"0,9": 1}
