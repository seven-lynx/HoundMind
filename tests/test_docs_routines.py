"""The routine format doc stays true: its examples must validate, its keys must exist.

`docs/ROUTINES.md` is a `contract` doc — a client writes routine files against it — so an example the
device would refuse is the one doc bug a user cannot debug from the doc. `tests/test_api_routes.py`
already asserts a doc against the code; this is the same idea for the routine format, and the reason
the doc's examples are `json` fences and nothing else.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.routine import ROUTINE_KEYS, STEP_KEYS, check_routine

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "ROUTINES.md"
SETTINGS_FILE = REPO_ROOT / "config" / "settings.jsonc"

# Every `json` fence in the doc is a routine document a user may copy. A fence in another language
# (`text`, `powershell`) is prose, not an example, which is why the refusal shapes are cited from
# `CONTROL_API.md` instead of being pasted here.
FENCE = re.compile(r"```json\r?\n(.*?)```", re.DOTALL)


def examples() -> list[dict]:
    """The routine documents the doc ships. At least one, or the test proves nothing."""
    blocks = FENCE.findall(DOC.read_text(encoding="utf-8"))
    assert blocks, "docs/ROUTINES.md ships at least one example a user can copy"
    return [json.loads(block) for block in blocks]


def test_every_example_is_a_routine_the_device_accepts() -> None:
    """The shipped catalog decides; a doc example the validator refuses costs a user an evening."""
    repertoire = repertoire_from_settings(load_config(SETTINGS_FILE).settings)

    for document in examples():
        problems = check_routine(document, repertoire)
        assert problems == [], f"{document.get('id')!r}: {[p.path + ': ' + p.message for p in problems]}"


def test_the_doc_documents_every_key_the_validator_accepts() -> None:
    """A key added to `routine.py` without a row here is a format change nobody wrote down."""
    text = DOC.read_text(encoding="utf-8")

    for key in (*ROUTINE_KEYS, *STEP_KEYS):
        assert f"`{key}`" in text, f"{key} is accepted by the validator and absent from the doc"
