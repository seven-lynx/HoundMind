"""The places file on disk: read it, keep what is valid, and write it back atomically.

A place is user data (`kernel/place.py`), and this store is the only thing that touches the file. It
answers two questions the runtime has to be able to ask: *which places may the dog go to right now*
(`load`) and *add/forget this one* (`add`, `remove`). Nothing here decides what a legal place is —
that is the model's job, and both callers reach it through the same validator, so a place the store
writes is a place `load` will read back.

Loading is **strict but quarantined**, the same rule `kernel/routine_store.py` applies to a
directory, applied here to a list:

- A missing file is not an error, and it is not created by a read. A fresh install has no places and
  must still boot; a read that writes is a surprise a support bundle cannot explain.
- One bad entry never costs the others. A bad heading, a name with a newline or an unreadable number
  is refused by index (`places[2].distance_cm`) and the rest of the file still loads — the same
  salvage pass a user editing JSON by hand needs.
- A file that is not JSON at all is one refusal, and **the bytes are left alone**.

Writing is where this store differs from the routine store, which only ever reads: a place can be
created (`POST /places` at P4 PL5), so `save` can overwrite a file it did not fully understand. The
guard is `keep_original`: when the load before a write refused anything, the previous file is copied
to `<path>.bak` first and the report names it, so a user's typo cannot be destroyed by a later
request. A corrupt file is therefore recoverable rather than merely reported.

Why here and not a `Module`: the navigator (`navigation/`) and the control plane (`services/`) both
read the same store, so it belongs on their shared side of the dependency rule (`services` →
`kernel`) and next to the model it validates. It is stateless — `load()` returns the report, the
caller keeps it — so "is the list stale?" has no answer to get wrong, and a write re-reads first.

Nothing here runs at import time: the path is resolved when a store is constructed.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from houndmind_ai.kernel.config_schema import Problem
from houndmind_ai.kernel.place import (
    DEFAULT_ANCHOR,
    Place,
    check_places_document,
    load_places,
    normalize_name,
    slug,
)

__all__ = [
    "DEFAULT_PLACES_PATH",
    "FORMAT_VERSION",
    "MAX_FILE_BYTES",
    "MAX_PLACES",
    "PlaceReport",
    "PlaceStore",
]

logger = logging.getLogger(__name__)

# `~/.houndmind/` is where the install keeps device-owned state (`services/auth.py::TokenStore`
# writes the token there, `kernel/routine_store.py` reads routines from it), so places join it
# instead of living in the tracked tree, where every place a user taught would be a dirty worktree.
DEFAULT_PLACES_PATH = "~/.houndmind/places.json"

# A place is a name and six numbers. 64 KB is thousands of them; the cap stops one enormous (or
# accidentally binary) file from being read into memory at boot.
MAX_FILE_BYTES = 64 * 1024

# A dog with 64 named places has a map, not a home. The cap is a bound on a runaway client, and it
# is checked on `add` rather than on load, because refusing to read a user's file would be worse.
MAX_PLACES = 64

FORMAT_VERSION = 1


@dataclass(frozen=True)
class PlaceReport:
    """What the file holds: places that passed, and a reason per entry that did not.

    `backup` is set when a write preserved a file that had been partly refused, so a caller can tell
    the user where the previous contents went instead of leaving them to guess.
    """

    path: Path
    places: tuple[Place, ...] = ()
    refusals: tuple[Problem, ...] = ()
    backup: Path | None = None

    @property
    def refused(self) -> int:
        """How many entries or lines were refused. Zero means the file is exactly what it says."""
        return len(self.refusals)

    def ids(self) -> tuple[str, ...]:
        return tuple(place.id for place in self.places)

    def get(self, place_id: str) -> Place | None:
        """The place with this id, or None. Ids are exact: a client stores what it was given."""
        for place in self.places:
            if place.id == place_id:
                return place
        return None

    def by_name(self, name: str) -> Place | None:
        """The place a user means by this name. Case and spacing are folded, for looking up only."""
        wanted = normalize_name(name)
        for place in self.places:
            if normalize_name(place.name) == wanted:
                return place
        return None


class PlaceStore:
    """The places file, read through `load()` and written through `add()`/`remove()`.

    `read_text` and `write_text` are injectable because the interesting failures — a permission
    denied, a device unplugged mid-read — are exactly the ones a test cannot provoke portably.
    `RoutineStore` and `PairingWindow` take their seams the same way, so this is the repo's own
    pattern rather than a mock. `clock` is injectable for the same reason: `created_ts` is the only
    clock in the format.
    """

    def __init__(
        self,
        path: str | Path = DEFAULT_PLACES_PATH,
        *,
        read_text: Callable[[Path], str] | None = None,
        write_text: Callable[[Path, str], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        # `~` is expanded once, here: a store built from config should never carry a literal tilde
        # into a log line or an error message.
        self.path = Path(path).expanduser()
        self._read_text = read_text or _read_utf8
        self._write_text = write_text or _write_utf8
        self._clock = clock or time.time

    # ------------------------------------------------------------------ reading

    def load(self) -> PlaceReport:
        """Read the file, keep the entries that pass, and report the ones that did not."""
        document, problems = self._read_document()
        if problems:
            for problem in problems:
                logger.warning("Places file %s: %s", self.path.name, problem)
            return PlaceReport(path=self.path, refusals=tuple(problems))
        if document is None:
            return PlaceReport(path=self.path)

        loaded = load_places(document)
        for problem in loaded.refusals:
            logger.warning("Place entry refused in %s: %s", self.path.name, problem)
        logger.info(
            "Places from %s: %d loaded, %d refused",
            self.path,
            len(loaded.places),
            len(loaded.refusals),
        )
        return PlaceReport(path=self.path, places=loaded.places, refusals=loaded.refusals)

    # ------------------------------------------------------------------ writing

    def add(
        self,
        name: str,
        *,
        heading_deg: float,
        distance_cm: float,
        anchor: str = DEFAULT_ANCHOR,
        confidence: float | None = None,
    ) -> tuple[Place | None, tuple[Problem, ...]]:
        """Create one place and persist it, or return the reasons it was refused.

        The candidate is checked by the same document validator `load` uses, over the current file
        plus the new entry — so a duplicate name, a heading outside the range and a second place with
        the same id are all one pass, and there is no second rule to keep in step.

        Problems are returned rather than raised, because they are answers a client shows a user
        (`POST /places` at P4 PL5), not exceptions.
        """
        report = self.load()
        if len(report.places) >= MAX_PLACES:
            return None, (
                Problem(
                    "places",
                    f"{len(report.places)} places already; the limit is {MAX_PLACES}",
                ),
            )

        clean_name = name.strip() if isinstance(name, str) else ""
        candidate = Place(
            id=slug(clean_name),
            name=clean_name,
            heading_deg=heading_deg,
            distance_cm=distance_cm,
            anchor=anchor.strip() if isinstance(anchor, str) and anchor.strip() else DEFAULT_ANCHOR,
            confidence=confidence,
            created_ts=self._clock(),
        )
        document = [place.to_dict() for place in report.places]
        document.append(candidate.to_dict())
        problems = check_places_document(document)
        if problems:
            return None, tuple(problems)

        self.save((*report.places, candidate), keep_original=report.refused > 0)
        return candidate, ()

    def remove(self, place_id: str) -> tuple[Place | None, tuple[Problem, ...]]:
        """Forget one place and persist the rest, or say why nothing was removed.

        An unknown handle is a refusal with a message, never a silent success: P4 PL6 needs a second
        `DELETE` to be visibly a no-op (`404`, not `200`), and that starts here.
        """
        report = self.load()
        wanted = place_id.strip() if isinstance(place_id, str) else ""
        victim = report.get(wanted) if wanted else None
        if victim is None and wanted:
            # A name is accepted too: someone typing "kitchen" is not wrong about the place, only
            # about the handle, and the id is the slug of the name for every place this store wrote.
            victim = report.by_name(wanted)
        if victim is None:
            return None, (Problem("places", f"no place with id or name {place_id!r}"),)

        remaining = tuple(place for place in report.places if place.id != victim.id)
        self.save(remaining, keep_original=report.refused > 0)
        return victim, ()

    def save(self, places: Sequence[Place], *, keep_original: bool = False) -> PlaceReport:
        """Write the whole file atomically: a temporary file, then a rename.

        `keep_original` is the guard for the case the routine store never had: this store can write
        over a file it only partly understood. When the load before a write refused anything, the
        previous contents are copied to `<path>.bak` first, once per write, and the report names it.

        A failed write raises. Reporting success on a write that did not happen is the one thing a
        store must never do.
        """
        payload = {
            "version": FORMAT_VERSION,
            "places": [place.to_dict() for place in places],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)

        backup: Path | None = None
        if keep_original and self.path.exists():
            backup = self.path.with_suffix(".bak")
            try:
                self._write_text(backup, self._read_text(self.path))
            except (OSError, UnicodeDecodeError) as exc:
                # The write still proceeds: refusing to save because the backup failed would leave
                # the user unable to change anything. The log says the copy did not happen.
                logger.warning("Could not back up %s before writing: %s", self.path, exc)
                backup = None
            else:
                logger.warning(
                    "Places file %s had refused entries; its previous contents are in %s",
                    self.path.name,
                    backup.name,
                )

        tmp = self.path.with_suffix(".tmp")
        self._write_text(tmp, json.dumps(payload, indent=2) + "\n")
        tmp.replace(self.path)
        logger.info("Saved %d place(s) to %s", len(places), self.path)
        return PlaceReport(path=self.path, places=tuple(places), backup=backup)

    # ------------------------------------------------------------------ internals

    def _read_document(self) -> tuple[object | None, tuple[Problem, ...]]:
        """The file as a JSON document, `(None, ())` when there is no file, or the reason there isn't.

        Three outcomes, not two: a missing file is the normal state of a fresh install and must not
        read as a defect, while an unreadable or oversized one must.
        """
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            logger.info("Places file %s does not exist; no places loaded", self.path)
            return None, ()
        except OSError as exc:
            return None, (Problem("places", f"could not be read: {exc}"),)
        if size > MAX_FILE_BYTES:
            return None, (Problem("places", f"{size} bytes; the limit is {MAX_FILE_BYTES}"),)
        try:
            text = self._read_text(self.path)
        except OSError as exc:
            return None, (Problem("places", f"could not be read: {exc}"),)
        except UnicodeDecodeError as exc:
            # Raised by the default reader on bytes that are not UTF-8, BOM or not.
            return None, (Problem("places", f"not UTF-8: {exc}"),)
        try:
            return json.loads(text), ()
        except ValueError as exc:
            # ValueError covers `JSONDecodeError` without importing the subclass for a message.
            return None, (Problem("places", f"not valid JSON: {exc}"),)


def _read_utf8(path: Path) -> str:
    """Read the places file, tolerating the BOM a Windows editor leaves behind.

    `utf-8-sig` decodes plain UTF-8 unchanged, so the only file it helps is one that would otherwise
    fail with a confusing "Expecting value: line 1 column 1".
    """
    return path.read_text(encoding="utf-8-sig")


def _write_utf8(path: Path, text: str) -> None:
    """Write UTF-8 without a BOM, whatever the platform default is (Windows is not UTF-8)."""
    path.write_text(text, encoding="utf-8")
