from pathlib import Path
import json

import pytest

from houndmind_ai.core import config as cfg


def test_load_jsonc_allows_comments_and_trailing_commas(tmp_path: Path):
    p = tmp_path / "settings.jsonc"
    text = '''{
        // This is a line comment
        "loop": {
            "tick_hz": 10,
            /* block comment */
            "max_cycles": 5,
        },
    }'''
    p.write_text(text, encoding="utf-8")
    data = cfg._load_jsonc(p)
    assert isinstance(data, dict)
    assert data["loop"]["tick_hz"] == 10
    assert data["loop"]["max_cycles"] == 5


def test_load_jsonc_unterminated_block_comment_raises(tmp_path: Path):
    p = tmp_path / "bad.jsonc"
    text = '{ /* unterminated block comment...\n "loop": { "tick_hz": 5 } }'
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        cfg._load_jsonc(p)
    assert "Unterminated block comment" in str(excinfo.value)
