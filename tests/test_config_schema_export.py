"""The settings tree is described once, and the document says the same thing the loader enforces."""

from __future__ import annotations

import json

from houndmind_ai.kernel import config_schema
from tools.schema_export import main


def test_the_document_declares_draft_2020_12_and_the_top_level() -> None:
    document = config_schema.json_schema()

    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert document["type"] == "object"
    assert set(document["properties"]) == {
        "profile",
        "profiles",
        "loop",
        "modules",
        "settings",
    }
    # A document an editor cannot parse is worse than none.
    json.dumps(document)


def test_every_settings_section_the_loader_knows_is_named() -> None:
    properties = config_schema.json_schema()["properties"]["settings"]["properties"]

    assert set(properties) == set(config_schema._SETTINGS_SECTIONS)
    assert properties["watchdog"]["type"] == "object"


def test_unknown_keys_are_refused_the_way_the_loader_refuses_them() -> None:
    settings = config_schema.json_schema()["properties"]["settings"]

    assert settings["additionalProperties"] is False
    assert settings["properties"]["watchdog"]["additionalProperties"] is False


def test_a_numeric_key_carries_its_bounds_and_nullability() -> None:
    loop = config_schema.json_schema()["properties"]["loop"]["properties"]

    assert loop["tick_hz"] == {"type": "integer", "minimum": 1, "maximum": 100}
    assert loop["max_cycles"] == {"type": ["integer", "null"], "minimum": 1}


def test_a_profile_override_has_the_same_shape_as_the_top_level() -> None:
    profiles = config_schema.json_schema()["properties"]["profiles"]

    assert profiles["type"] == "object"
    assert set(profiles["additionalProperties"]["properties"]) == {
        "loop",
        "modules",
        "settings",
    }


def test_the_tool_writes_the_document(tmp_path, capsys) -> None:
    out = tmp_path / "settings.schema.json"

    assert main(["--out", str(out)]) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["properties"]["loop"]["properties"]["tick_hz"]["maximum"] == 100
    assert "[schema] wrote" in capsys.readouterr().out


def test_the_tool_prints_without_writing(capsys) -> None:
    assert main([]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["title"] == "HoundMind settings"
