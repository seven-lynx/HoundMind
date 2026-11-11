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
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["MODEL_PATH", "SUPPORTED_KINDS", "BoardInfo", "classify_model", "detect"]

# The kernel's own words. Present on every Raspberry Pi with a device tree, absent on a
# workstation, a container and CI — which is why "absent" is `unknown` and not an error.
MODEL_PATH = Path("/proc/device-tree/model")

# The two editions this project ships. Anything else a Pi says about itself is either a board
# we dropped (Pi 3 and older) or a board we have no measurement for.
SUPPORTED_KINDS: tuple[str, ...] = ("pi4", "pi5")

# Matched against the lowercased model string, in order. Signs such as the CM5 and the Pi 500
# carry their generation in the name, so all three spellings of a generation belong together.
#
# Every pattern ends on a word boundary so a generation is matched as a whole token. The model
# string also carries a revision — "Raspberry Pi 4 Model B Rev 1.5" is a Pi 4 — so matching a
# bare digit, which is the obvious shortcut, silently invents a Pi 5.
_GENERATIONS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "pi5",
        tuple(
            re.compile(pattern)
            for pattern in (
                r"raspberry pi 5\b",
                r"raspberry pi 500\b",
                r"compute module 5\b",
            )
        ),
    ),
    (
        "pi4",
        tuple(
            re.compile(pattern)
            for pattern in (
                r"raspberry pi 4\b",
                r"raspberry pi 400\b",
                r"compute module 4\b",
            )
        ),
    ),
    (
        # Named rather than merely unrecognised: these boards are a refusal, not a shrug.
        "unsupported",
        tuple(
            re.compile(pattern)
            for pattern in (
                r"raspberry pi 3\b",
                r"raspberry pi 2\b",
                r"raspberry pi 1\b",
                r"raspberry pi zero",
                r"compute module 3\b",
                r"compute module 1\b",
            )
        ),
    ),
)


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

    Pure: the caller supplies the string, so the mapping is testable without a Raspberry Pi.
    """
    # The attribute is NUL-terminated; some kernels also pad it. Normalise before matching.
    text = " ".join(model.replace("\x00", " ").split()).lower()
    if not text:
        return "unknown"
    for kind, patterns in _GENERATIONS:
        if any(pattern.search(text) for pattern in patterns):
            return kind
    return "unknown"


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