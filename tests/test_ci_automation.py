"""`.github/` automation the repository depends on: the Dependabot config and its one exemption.

#138: nothing proposed an action bump until a GitHub runtime deprecation broke a run, so the pins
aged silently and the first warning arrived on a run that was already red. `identity_guard` is a
required check, and a Dependabot commit is authored by `dependabot[bot]`, which no human account can
match - so a config with no exemption opens pull requests that can never merge, and an exemption with
no config protects nothing. These two assertions keep the pair together.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_dependabot_watches_the_action_pins_weekly_and_grouped() -> None:
    """One grouped pull request per week, not one per action, and only the action pins."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert 'package-ecosystem: "github-actions"' in text
    assert 'directory: "/"' in text
    assert 'interval: "weekly"' in text
    assert "groups:" in text and "patterns:" in text


def test_the_identity_guard_exempts_only_dependabot_pull_requests() -> None:
    """The exemption is deliberately narrow: one automation identity, on `pull_request` only."""
    text = CI.read_text(encoding="utf-8")
    assert "ACTOR: ${{ github.actor }}" in text
    assert '[ "$EVENT_NAME" = "pull_request" ] && [ "$ACTOR" = "dependabot[bot]" ]' in text
    # A human commit is still checked: the accepted-address list stays in the same job.
    assert "accepted='53497955\\+seven-lynx" in text
