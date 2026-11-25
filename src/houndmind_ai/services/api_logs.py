"""The diagnostic exports, split out of `services/api.py` (AP5).

`GET /logs` and `GET /support-bundle` — the two routes an operator reaches for when the dog
misbehaved and asking it a question is no longer enough. They move together because they are one
job: hand somebody the device's own record, bounded and honest about what was not in it.

**The tail is a byte walk, not a read.** Unfiltered is one 64 KiB read from the end, so the default
panel view does not depend on the file's size; a filter walks backwards in chunks and stops at a
budget, which is why `truncated` is in the answer — "no lines" must not be readable as "nothing in
the log" when the window simply ran out (#171). The resolution of *which* file lives in
`core/logging_setup.py::log_file_path` because the WebSocket's live tail reads the same one (#170).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from houndmind_ai.core.logging_setup import log_file_path
from houndmind_ai.services.auth import AuthError
from houndmind_ai.services.http import _plane

if TYPE_CHECKING:
    from houndmind_ai.services.api import ControlPlane

# The level names `core/logging_setup.py::JsonFormatter` writes, and the whole accepted set for the
# `level` query parameter: an unknown one is a 400 rather than a silent "no lines match", because
# "your filter is misspelled" and "nothing matched" are different answers (#171).
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LOG_CHUNK = 64 * 1024
# A filtered read walks back further than the unfiltered tail, but the work has to be bounded: 4 MiB
# is hours of this runtime's log and still one comfortable read on a Pi's SD card.
_FILTER_BUDGET = 4 * 1024 * 1024


async def _logs(request: web.Request) -> web.Response:
    plane = _plane(request)
    tail = request.query.get("tail")
    try:
        count = max(1, min(int(tail), plane.settings.log_tail)) if tail else plane.settings.log_tail
    except (TypeError, ValueError):
        raise AuthError("bad_request", "tail must be an integer", status=400) from None
    level = (request.query.get("level") or "").strip().upper()
    if level and level not in _LOG_LEVELS:
        raise AuthError(
            "bad_request",
            f"level must be one of {', '.join(_LOG_LEVELS)}",
            status=400,
        )
    contains = (request.query.get("contains") or "").strip()
    found = _tail_lines(plane, count, level=level or None, contains=contains or None)
    if found is None:
        return web.json_response(
            {
                "error": "unavailable",
                "detail": "no log file is configured; set settings.logging.enable_file",
            },
            status=503,
        )
    lines, truncated = found
    return web.json_response(
        {
            "lines": lines,
            "filtered": bool(level or contains),
            # `truncated` means the walk stopped at its byte budget before reaching the start of the
            # file, so "no lines" is "no match in the window", not "no match in the log" (#171).
            "truncated": truncated,
        }
    )


def _log_path(plane: ControlPlane) -> Path | None:
    """The configured log file, or None when file logging is switched off.

    The resolution lives in `core/logging_setup.py::log_file_path` because the live tail on the
    WebSocket reads the same file (#170), and two answers to "which file" is one too many.
    """
    return log_file_path(plane.context.get("settings"))


def _tail_lines(
    plane: ControlPlane,
    count: int,
    *,
    level: str | None = None,
    contains: str | None = None,
) -> tuple[list[str], bool] | None:
    """The last `count` lines, optionally filtered. None means "no log file configured".

    Unfiltered is one 64 KiB read from the end: the default panel view must not depend on the file's
    size. A filter has to look further back or it lies in exactly the case it exists for — "the ERROR
    was ten minutes ago" (#171) — so it walks backwards in 64 KiB chunks, stopping once it has
    `count` matches or has read `_FILTER_BUDGET` bytes.

    The second element is `truncated`: the walk stopped at the budget rather than at the start of the
    file, so an empty answer honestly means "nothing matched in the window".
    """
    path = _log_path(plane)
    if path is None:
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(0, io.SEEK_END)
            end = handle.tell()
            if level is None and not contains:
                handle.seek(max(0, end - _LOG_CHUNK))
                chunk = handle.read().decode("utf-8", errors="replace")
                return chunk.splitlines()[-count:], False
            budget = min(end, _FILTER_BUDGET)
            window = b""
            kept: list[str] = []
            while end > 0 and len(window) < budget:
                step = min(_LOG_CHUNK, end)
                end -= step
                handle.seek(end)
                window = handle.read(step) + window
                lines = window.decode("utf-8", errors="replace").splitlines()
                if end > 0:
                    # The first element is cut at the window edge; the next iteration completes it.
                    lines = lines[1:]
                kept = _matching_lines(lines, count, level, contains)
                if len(kept) >= count:
                    break
    except OSError:
        return None
    return kept[-count:], end > 0


def _matching_lines(
    lines: list[str], count: int, level: str | None, contains: str | None
) -> list[str]:
    """The last `count` lines that match, walking backwards so the cost is the match, not the file.

    The file is one JSON object per line (`core/logging_setup.py::JsonFormatter`). A traceback's
    continuation lines carry no level of their own, so a `level` filter keeps record lines only -
    which is what the panel has always rendered. `contains` still matches continuation lines, because
    the stack trace is usually the thing being searched for.
    """
    needle = contains.lower() if contains else None
    kept: list[str] = []
    for line in reversed(lines):
        if needle is not None and needle not in line.lower():
            continue
        if level is not None and _line_level(line) != level:
            continue
        kept.append(line)
        if len(kept) >= count:
            break
    kept.reverse()
    return kept


def _line_level(line: str) -> str | None:
    """The `level` of a JSON log line, or None when the line is not a record."""
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("level")
    return str(value).upper() if value else None


async def _support_bundle(request: web.Request) -> web.Response:
    plane = _plane(request)
    body = plane.support_bundle()
    return web.Response(
        body=body,
        content_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="houndmind-support.zip"'},
    )
