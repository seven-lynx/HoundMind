"""The HAL reports a sound the vendor could not find (#81).

`docs/pidog/PIDOG-EXPRESSION.md:81`: an unknown name makes the vendor print `No sound found` and
return `False`. `PidogHAL.sound()` and `.speak()` return `None` on both paths, so before this the
only trace of a typo'd cue name — or an incomplete `sounds/` directory — was nothing at all. That
matters because `settings.behavior.state_expressions.<state>.sound` rides this call, so a silent
device and a working one looked identical from every surface the runtime exposes.

`_play` is called directly rather than through the queue: the reporting is what is under test, and
the worker thread is one indirection away from it. `PidogHAL` takes an injected `dog`, which is how
this runs without importing `pidog` on a workstation.
"""

from __future__ import annotations

import logging

from houndmind_ai.hal.vendor import PidogHAL

LOGGER = "houndmind_ai.hal.vendor"


class StubDog:
    """A vendor stand-in whose `speak` returns exactly what a real one might."""

    def __init__(self, result: object = True, accept_volume: bool = True) -> None:
        self.result = result
        self.accept_volume = accept_volume
        self.calls: list[tuple[str, int | None]] = []

    def speak(self, text: str, volume: int | None = None) -> object:
        if volume is not None and not self.accept_volume:
            raise TypeError("speak() takes 2 positional arguments but 3 were given")
        self.calls.append((text, volume))
        return self.result


def missing_sound_warnings(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER and record.levelno == logging.WARNING
    ]


def test_a_missing_sound_is_reported_once(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    dog = StubDog(result=False)
    hal = PidogHAL(settings={}, dog=dog)

    hal._play("no such effect", 70)
    hal._play("no such effect", 70)

    assert len(dog.calls) == 2, "the vendor is still called; only the report is deduped"
    messages = missing_sound_warnings(caplog)
    assert len(messages) == 1, "one warning per name, not one per cue"
    assert "no such effect" in messages[0]


def test_two_missing_names_are_each_reported(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    hal = PidogHAL(settings={}, dog=StubDog(result=False))

    hal._play("first", 70)
    hal._play("second", 70)

    messages = missing_sound_warnings(caplog)
    assert len(messages) == 2
    assert "first" in messages[0] and "second" in messages[1]


def test_a_sound_the_vendor_found_is_never_reported(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    hal = PidogHAL(settings={}, dog=StubDog(result=True))

    hal._play("bark", 70)

    assert missing_sound_warnings(caplog) == []


def test_a_text_only_vendor_build_still_reports_a_missing_sound(caplog) -> None:
    """Older builds take the text alone; the `TypeError` retry must not lose the verdict."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    dog = StubDog(result=False, accept_volume=False)
    hal = PidogHAL(settings={}, dog=dog)

    hal._play("no such effect", 70)

    assert dog.calls == [("no such effect", None)], "the retry drops the volume, not the call"
    assert len(missing_sound_warnings(caplog)) == 1


def test_a_vendor_without_speak_stays_a_debug_line(caplog) -> None:
    """No audio path at all is a build difference, not a defect: no warning for it."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    hal = PidogHAL(settings={}, dog=object())

    hal._play("bark", 70)

    assert missing_sound_warnings(caplog) == []
