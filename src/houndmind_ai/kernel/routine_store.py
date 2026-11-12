"""The routine files on disk: read once, validate every file, refuse the bad ones by name.

A routine is user data (`kernel/routine.py`), so the store exists to answer one question: which
routines may this dog run right now? It answers with a :class:`StoreReport` — the accepted routines
keyed by id, and a refusal per rejected *file* — and it never writes, because nothing in this phase
creates a routine over the API. The user edits files; the dog reads them.

Loading is **strict but quarantined**, which is the only shape that survives real user data:

- A missing directory is not an error. A fresh install has no routines and must still boot; the
  directory is not created here either, because a read that writes is a surprise a support bundle
  cannot explain.
- One bad file never costs the others. A malformed, unreadable, oversized or invalid document is
  recorded in `refusals` under its file name and the rest of the directory still loads. The runtime
  must start with a broken routine on disk.
- Two files claiming one id is a refusal, not a silent last-wins: the first file in sorted order
  keeps the id and the second says which file it collided with. Sorted order is what makes the
  winner reproducible between boots.
- The file name is a label, not the identity: `greeting.json` may declare `"id": "morning_greeting"`.
  An id is data a client stores; a rename must not break a routine.

Why here and not a `Module`: the runner (`behavior/`) and the control plane (`services/`) both read
the same store, so it belongs on their shared side of the dependency rule (`services` → `kernel`) and
next to the model it validates. It is stateless — `load()` returns the report, the caller keeps it —
so "is the list stale?" has no answer to get wrong.

Nothing here runs at import time: the directory is resolved when a store is constructed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from houndmind_ai.kernel.actions import Repertoire
from houndmind_ai.kernel.config_schema import Problem
from houndmind_ai.kernel.routine import Routine, check_routine, parse_routine

__all__ = [
    "DEFAULT_ROUTINES_DIR",
    "MAX_FILE_BYTES",
    "RoutineStore",
    "StoreReport",
]

logger = logging.getLogger(__name__)

# `~/.houndmind/` is where the install keeps device-owned state (`services/auth.py::TokenStore`
# writes the token there), so routines join it instead of living in the tracked tree, where every
# edit a user makes would be a dirty worktree.
DEFAULT_ROUTINES_DIR = "~/.houndmind/routines"

# A legal 64-step routine is around 10 KB. The cap stops one enormous (or accidentally binary) file
# from being read into memory at boot; it is not a size the format is expected to approach.
MAX_FILE_BYTES = 256 * 1024

_SUFFIX = ".json"


@dataclass(frozen=True)
class StoreReport:
    """What the directory holds: routines that passed, and files that did not.

    `refusals` is keyed by file name rather than flattened into one list so a client can show the
    reason next to the file a user has to edit. The :class:`Problem` paths inside each entry are the
    validator's own (`routine.steps[1].action`), kept untouched — rewriting them to embed the file
    name would make them unreadable to the code that produced them.
    """

    directory: Path
    routines: Mapping[str, Routine] = field(default_factory=lambda: MappingProxyType({}))
    refusals: Mapping[str, tuple[Problem, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def get(self, routine_id: str) -> Routine | None:
        """The routine with this id, or None when it was not loaded."""
        return self.routines.get(routine_id)

    def ids(self) -> tuple[str, ...]:
        """Every accepted id, sorted, so a listing does not reshuffle between requests."""
        return tuple(sorted(self.routines))

    @property
    def refused(self) -> int:
        """How many files were skipped."""
        return len(self.refusals)


class RoutineStore:
    """The routines directory, read through `load()`.

    `read_text` is injectable because the interesting failures — a permission denied, a device
    unplugged mid-read — are exactly the ones a test cannot provoke portably. `PairingWindow` takes
    its clock the same way (`services/auth.py`), so this is the repo's own seam rather than a mock.
    """

    def __init__(
        self,
        directory: str | Path = DEFAULT_ROUTINES_DIR,
        *,
        read_text: Callable[[Path], str] | None = None,
    ) -> None:
        # `~` is expanded once, here: a store built from config should never carry a literal tilde
        # into a log line or an error message.
        self.directory = Path(directory).expanduser()
        self._read_text = read_text or _read_utf8

    def load(self, repertoire: Repertoire) -> StoreReport:
        """Validate and parse every `.json` file, keeping the good ones and reporting the rest.

        `repertoire` is the one the runtime is running (`kernel/actions.py::repertoire_from_settings`),
        never a table invented here — the menu a client builds a routine from has to be the menu that
        accepts it.
        """
        routines: dict[str, Routine] = {}
        sources: dict[str, str] = {}
        refusals: dict[str, tuple[Problem, ...]] = {}

        for path in self._files():
            name = path.name
            document, problems = self._read_document(path)
            if problems:
                refusals[name] = problems
                logger.warning("Routine file %s skipped: %s", name, problems[0])
                continue
            if document is None:  # pragma: no cover - `_read_document` pairs these
                continue

            problems = tuple(check_routine(document, repertoire))
            if problems:
                refusals[name] = problems
                logger.warning("Routine file %s skipped: %s", name, problems[0])
                continue

            routine = parse_routine(document)
            if routine is None:  # pragma: no cover - a clean check always parses
                refusals[name] = (
                    Problem("routine", "passed the check but could not be read as a routine"),
                )
                logger.warning("Routine file %s skipped: could not be read as a routine", name)
                continue

            earlier = sources.get(routine.id)
            if earlier is not None:
                refusals[name] = (
                    Problem(
                        "routine.id",
                        f"'{routine.id}' is already loaded from {earlier}; {name} was skipped",
                    ),
                )
                logger.warning(
                    "Routine file %s skipped: id '%s' already loaded from %s",
                    name,
                    routine.id,
                    earlier,
                )
                continue

            routines[routine.id] = routine
            sources[routine.id] = name

        logger.info(
            "Routines from %s: %d accepted, %d refused",
            self.directory,
            len(routines),
            len(refusals),
        )
        return StoreReport(
            directory=self.directory,
            routines=MappingProxyType(routines),
            refusals=MappingProxyType(refusals),
        )

    # ----------------------------------------------------------------- internals

    def _files(self) -> tuple[Path, ...]:
        """Every candidate file, sorted. An unlistable directory starts the runtime empty."""
        try:
            entries = sorted(self.directory.iterdir())
        except FileNotFoundError:
            logger.info(
                "Routines directory %s does not exist; no routines loaded", self.directory
            )
            return ()
        except OSError as exc:
            # Permission denied, or a path that is a file rather than a directory. Nothing here can
            # be refused by file name, because there is no file to name.
            logger.warning("Routines directory %s could not be read: %s", self.directory, exc)
            return ()
        # `is_file()` follows a symlink, so a routine linked in from elsewhere loads; a broken link
        # or a subdirectory that merely ends in `.json` does not.
        return tuple(
            entry for entry in entries if entry.suffix.lower() == _SUFFIX and entry.is_file()
        )

    def _read_document(self, path: Path) -> tuple[object | None, tuple[Problem, ...]]:
        """One file to a JSON document, or the reason it could not become one."""
        try:
            size = path.stat().st_size
        except OSError as exc:
            return None, (Problem("routine", f"could not be read: {exc}"),)
        if size > MAX_FILE_BYTES:
            return None, (Problem("routine", f"{size} bytes; the limit is {MAX_FILE_BYTES}"),)
        try:
            text = self._read_text(path)
        except OSError as exc:
            return None, (Problem("routine", f"could not be read: {exc}"),)
        except UnicodeDecodeError as exc:
            # Raised by the default reader on bytes that are not UTF-8, BOM or not.
            return None, (Problem("routine", f"not UTF-8: {exc}"),)
        try:
            return json.loads(text), ()
        except ValueError as exc:
            # ValueError covers `JSONDecodeError` without importing the subclass for a message.
            return None, (Problem("routine", f"not valid JSON: {exc}"),)


def _read_utf8(path: Path) -> str:
    """Read a routine file, tolerating the BOM a Windows editor leaves behind.

    `utf-8-sig` decodes plain UTF-8 unchanged, so the only file it helps is one that would
    otherwise fail with a confusing "Expecting value: line 1 column 1".
    """
    return path.read_text(encoding="utf-8-sig")
