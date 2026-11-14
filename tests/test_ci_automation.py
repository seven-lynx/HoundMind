"""`.github/` automation the repository depends on: the Dependabot pin schedule.

#138: nothing proposed an action bump until a GitHub runtime deprecation broke a run, so the pins
aged silently and the first warning arrived on a run that was already red. The schedule below is
what keeps that from recurring, and it is the only thing this module asserts.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPENDABOT = ROOT / ".github" / "dependabot.yml"


def test_dependabot_watches_the_action_pins_weekly_and_grouped() -> None:
    """One grouped pull request per week, not one per action, and only the action pins."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert 'package-ecosystem: "github-actions"' in text
    assert 'directory: "/"' in text
    assert 'interval: "weekly"' in text
    assert "groups:" in text and "patterns:" in text
