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
