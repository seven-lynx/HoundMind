"""The board rule itself: which Raspberry Pi a device-tree model string names.

Separate from `detect.py` for one reason. `scripts/installer_core.py` has to answer the same
question **before** the package is installed, so it cannot import `houndmind_ai`; it loads this
file by path instead. The two used to keep a copy each, which is how a Pi 5 was reported as a Pi 4
and nothing compared the answers (#31). One table, two callers.

Nothing here may import outside the standard library, and nothing may touch the filesystem or a
device: `detect.py` reads the model, the installer reads the model, and this module only classifies
the string it is handed.
"""

from __future__ import annotations

import re

__all__ = ["GENERATIONS", "classify_text"]

# Matched against the lowercased model string, in order. Signs such as the CM5 and the Pi 500
# carry their generation in the name, so all three spellings of a generation belong together.
#
# Every pattern ends on a word boundary so a generation is matched as a whole token. The model
# string also carries a revision - "Raspberry Pi 4 Model B Rev 1.5" is a Pi 4 - so matching a
# bare digit, which is the obvious shortcut, silently invents a Pi 5.
GENERATIONS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
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


def classify_text(model: str) -> str:
    """Map a device-tree model string to a board kind.

    Pure: the caller supplies the string, so the mapping is testable without a Raspberry Pi, and so
    the installer can ask the question about a model it read before anything was installed.
    """
    # The attribute is NUL-terminated; some kernels also pad it. Normalise before matching.
    text = " ".join(model.replace("\x00", " ").split()).lower()
    if not text:
        return "unknown"
    for kind, patterns in GENERATIONS:
        if any(pattern.search(text) for pattern in patterns):
            return kind
    return "unknown"
