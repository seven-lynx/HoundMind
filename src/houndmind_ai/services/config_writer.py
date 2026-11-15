"""Rewrite live keys in `settings.jsonc` without touching the rest of the file (#174).

`PATCH /config` persists into the file the runtime read, and that file is JSONC: hand-written,
heavily commented, and those comments are the documentation for every key. Re-emitting it from a
parser would delete all of them, so the write is **surgical**: find the value's byte span and replace
only those bytes.

Finding it means scanning rather than searching for text. A comment that mentions `brightness`, a
string value that contains `"heading_deg"`, or a `brightness` inside a different section must not
answer for `led.brightness`, and a regex cannot tell those apart. `_iter_scalars` is a small JSONC
scanner that tracks object nesting, string escapes and both comment forms, and yields the offset of
every scalar with the key path that reaches it.

Conflict policy (G1, the owner's decision): the caller passes the file's stamp — `(mtime_ns, size,
digest)` from when it read the file — and a file that no longer matches is **refused with 409**.
Losing somebody's edit because "the runtime was running" is not a rule anyone agreed to.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterator, Mapping
from pathlib import Path

import json5

logger = logging.getLogger(__name__)

__all__ = ["ConfigWriteError", "find_value_span", "stamp_of", "write_settings_values"]

# `LIVE_CONFIG_KEYS` is dotted from the runtime's `settings` table, which is the file's `settings`
# object: `led.brightness` is `settings.led.brightness` on disk.
SETTINGS_ROOT = "settings"

Stamp = tuple[int, int, str]


class ConfigWriteError(Exception):
    """A write that did not happen. `status` is the HTTP answer the route should give."""

    def __init__(self, detail: str, *, status: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


def stamp_of(path: Path | None) -> Stamp | None:
    """`(mtime_ns, size, digest)` for the file, or None when it is not there.

    The digest is what makes the conflict check honest. `0.7` -> `0.6` is a same-length edit, and if
    it lands inside the filesystem's timestamp granularity the mtime and size both say "untouched" -
    which would let the runtime overwrite exactly the edit G1 says must win.
    """
    if path is None:
        return None
    try:
        raw = path.read_bytes()
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size, hashlib.blake2b(raw, digest_size=8).hexdigest()


def _skip_trivia(text: str, index: int) -> int:
    """Advance past whitespace, `//` line comments and `/* */` blocks."""
    size = len(text)
    while index < size:
        char = text[index]
        if char in " \t\r\n":
            index += 1
        elif char == "/" and index + 1 < size and text[index + 1] == "/":
            end = text.find("\n", index)
            index = size if end < 0 else end + 1
        elif char == "/" and index + 1 < size and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            index = size if end < 0 else end + 2
        else:
            break
    return index


def _string_span(text: str, index: int) -> tuple[int, str]:
    """The end offset of the string token at `index` and its decoded value."""
    size = len(text)
    cursor = index + 1
    while cursor < size:
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == '"':
            cursor += 1
            break
        cursor += 1
    token = text[index:cursor]
    try:
        return cursor, json.loads(token)
    except ValueError as exc:
        raise ConfigWriteError(
            f"settings.jsonc holds a string this writer cannot read: {exc}", status=500
        ) from exc

def _path_of(stack: list[dict[str, object]]) -> tuple[str, ...]:
    """The key path of whatever is currently open, object keys only."""
    return tuple(
        str(entry["key"]) for entry in stack if entry["kind"] == "obj" and entry["key"] is not None
    )


def _iter_scalars(text: str) -> Iterator[tuple[tuple[str, ...], int, int]]:
    """Every scalar value in the document: `(key path, start offset, end offset)`.

    Scalars inside an array are skipped: nothing this writer targets lives in one, and a path without
    indices could otherwise match an element by accident.
    """
    stack: list[dict[str, object]] = []
    index = 0
    size = len(text)
    while True:
        index = _skip_trivia(text, index)
        if index >= size:
            return
        char = text[index]
        if char == "{":
            stack.append({"kind": "obj", "key": None, "key_expected": True})
            index += 1
        elif char == "[":
            stack.append({"kind": "arr", "key": None, "key_expected": False})
            index += 1
        elif char in "}]":
            if not stack:
                raise ConfigWriteError("settings.jsonc closes a block it never opened", status=500)
            stack.pop()
            index += 1
        elif char == ",":
            if stack:
                stack[-1]["key_expected"] = stack[-1]["kind"] == "obj"
            index += 1
        elif char == ":":
            index += 1
        elif char == '"':
            end, value = _string_span(text, index)
            top = stack[-1] if stack else None
            if top is not None and top["kind"] == "obj" and top["key_expected"]:
                top["key"] = value
                top["key_expected"] = False
            elif not any(entry["kind"] == "arr" for entry in stack):
                yield _path_of(stack), index, end
            index = end
        else:
            end = index
            while end < size and text[end] not in ",]}/ \t\r\n":
                end += 1
            if end == index:
                raise ConfigWriteError(
                    f"settings.jsonc has an unexpected {char!r} at offset {index}", status=500
                )
            if not any(entry["kind"] == "arr" for entry in stack):
                yield _path_of(stack), index, end
            index = end


def find_value_span(text: str, dotted: str) -> tuple[int, int] | None:
    """Start and end offsets of the scalar at `dotted`, or None when it is not a scalar there.

    More than one match is a refusal rather than a guess: a duplicated key loads as whichever the
    parser reached last, and rewriting the other one would answer 200 while changing nothing.
    """
    wanted = (SETTINGS_ROOT, *dotted.split("."))
    found = [(start, end) for path, start, end in _iter_scalars(text) if path == wanted]
    if not found:
        return None
    if len(found) > 1:
        raise ConfigWriteError(
            f"{dotted} appears {len(found)} times in settings.jsonc; remove the duplicate first",
            status=409,
        )
    return found[0]


def _dig(document: object, path: tuple[str, ...]) -> object:
    current = document
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _atomic_write(path: Path, payload: bytes, mode: int) -> None:
    """Write a sibling temp file and rename it over the original: a crash leaves one or the other."""
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    except OSError as exc:
        raise ConfigWriteError(f"cannot write {path.name}: {exc}", status=500) from exc


def write_settings_values(
    path: Path,
    updates: Mapping[str, object],
    *,
    expected_stamp: Stamp | None = None,
) -> Stamp:
    """Persist `{dotted: value}` into `settings.jsonc` and return the file's new stamp.

    Every key is written in one pass, so a PATCH naming three keys cannot leave the file holding one
    of them: either every span is found and the rewritten document still loads with those values, or
    nothing is written at all.
    """
    before = stamp_of(path)
    if expected_stamp is not None and before != expected_stamp:
        raise ConfigWriteError(
            f"{path.name} changed on disk since the runtime started; restart the runtime to pick up "
            "the edit, then send this change again",
            status=409,
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigWriteError(f"cannot read {path.name}: {exc}", status=409) from exc
    if stamp_of(path) != before:
        raise ConfigWriteError(
            f"{path.name} changed while it was being read; try again", status=409
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigWriteError(f"{path.name} is not UTF-8: {exc}", status=500) from exc

    spans: list[tuple[int, int, str]] = []
    for dotted, value in updates.items():
        span = find_value_span(text, dotted)
        if span is None:
            raise ConfigWriteError(
                f"{dotted} is not written in {path.name}; add it there once, then PATCH it",
                status=409,
            )
        spans.append((*span, json.dumps(value)))

    # Right to left, so the offsets of the earlier spans stay valid as the text changes.
    rewritten = text
    for start, end, replacement in sorted(spans, reverse=True):
        rewritten = rewritten[:start] + replacement + rewritten[end:]

    # Prove the result before it replaces anything: it must load, and it must say what was asked.
    try:
        parsed = json5.loads(rewritten)
    except ValueError as exc:
        raise ConfigWriteError(
            f"the rewritten settings.jsonc would not load: {exc}", status=500
        ) from exc
    for dotted, value in updates.items():
        landed = _dig(parsed, (SETTINGS_ROOT, *dotted.split(".")))
        if landed != value:
            raise ConfigWriteError(f"the rewrite did not land on {dotted}", status=500)

    mode = path.stat().st_mode
    _atomic_write(path, rewritten.encode("utf-8"), mode)
    logger.info("Persisted %s into %s", ", ".join(updates), path.name)
    return stamp_of(path) or (0, 0, "")
