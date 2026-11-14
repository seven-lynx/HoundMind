"""Which Raspberry Pi this is, read from the device tree.

One question, asked once, with one right answer, so that a profile can be chosen from it. The
package holds no policy: `board` says "this is a Pi 5", and `config/settings.jsonc` plus
`kernel/config_schema.py` decide what that permits.

Before this existed the runtime never asked: `profile` was whatever the shipped file said, and
the installer reported a Pi 5 as `"pi4"`. A Pi 5 edition would have been a claim rather than a
fact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from houndmind_ai.board.rules import classify_text

logger = logging.getLogger(__name__)

__all__ = ["MODEL_PATH", "SUPPORTED_KINDS", "BoardInfo", "classify_model", "detect"]

# The kernel's own words. Present on every Raspberry Pi with a device tree, absent on a
# workstation, a container and CI - which is why "absent" is `unknown` and not an error.
MODEL_PATH = Path("/proc/device-tree/model")

# The two editions this project ships. Anything else a Pi says about itself is either a board
# we dropped (Pi 3 and older) or a board we have no measurement for.
SUPPORTED_KINDS: tuple[str, ...] = ("pi4", "pi5")

# The generation table is `board/rules.py`, which the installer loads by path as well: it runs
# before this package is installed and cannot import it, so a copy here is how the two answers
# drifted apart (#31).


@dataclass(frozen=True)
class BoardInfo:
    """What the device tree said.

    ``kind`` is ``"pi4"``, ``"pi5"``, ``"unsupported"`` (a Pi we deliberately dropped) or
    ``"unknown"`` (no device tree, or a model string we do not recognise). ``model`` is the raw
    string, kept verbatim so a support bundle can show it without a re-read.
    """

    kind: str
    model: str = ""

    @property
    def supported(self) -> bool:
        return self.kind in SUPPORTED_KINDS


def classify_model(model: str) -> str:
    """Map a device-tree model string to a board kind.

    Pure: the caller supplies the string, so the mapping is testable without a Raspberry Pi. The
    rule itself is `board/rules.py`; this is the import-side spelling of it.
    """
    return classify_text(model)


def detect(path: Path | None = None) -> BoardInfo:
    """Read the model string and classify it.

    ``path`` exists for tests; production always reads :data:`MODEL_PATH`. A missing file is
    not an error — it is the normal state on CI, on a workstation and inside a container, and
    the runtime has to start on all three.
    """
    model_path = path or MODEL_PATH
    try:
        raw = model_path.read_bytes()
    except OSError as exc:
        logger.debug("No board model at %s: %s", model_path, exc)
        return BoardInfo(kind="unknown", model="")

    text = raw.decode("utf-8", errors="replace").replace("\x00", "").strip()
    return BoardInfo(kind=classify_model(text), model=text)