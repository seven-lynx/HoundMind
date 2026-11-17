"""`tools.map_inspect` reads a map file with the runtime's own validator.

The tool's job is to answer "what is in this file" without a runtime, a HAL or a dog - so its tests
are the same: one legal fixture, one broken file, and the JSON mode that another tool can consume.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools import map_inspect

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "maps" / "tiny.json"


def test_it_reports_the_cells_and_the_nearest_wall(capsys) -> None:
    assert map_inspect.main([str(FIXTURE)]) == 0

    out = capsys.readouterr().out
    assert "version:  2" in out
    assert "cells:    5" in out
    assert "cm (capped at 300)" in out
    # The dog sits at the origin and the strongest wall is 50 cm ahead: the picture has to say so.
    assert "@" in out


def test_json_mode_is_the_document_not_a_picture(capsys) -> None:
    assert map_inspect.main([str(FIXTURE), "--json"]) == 0

    document = json.loads(capsys.readouterr().out)
    assert document["version"] == 2
    assert document["cells"]["0,5"] == 6
    assert document["samples"] == 1


def test_a_broken_file_exits_one_and_names_the_problem(tmp_path, capsys) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")

    assert map_inspect.main([str(broken)]) == 1

    out = capsys.readouterr().out
    assert "NOT LOADED" in out
    assert "not JSON" in out


def test_a_missing_file_says_there_is_none(tmp_path, capsys) -> None:
    assert map_inspect.main([str(tmp_path / "absent.json")]) == 1

    assert "no home map at" in capsys.readouterr().out
