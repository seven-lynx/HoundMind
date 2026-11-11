## Summary

<!-- What changed and why, in one or two sentences. "Closes #<n>" if it resolves an issue. -->

## Verification

- [ ] `python -m ruff check src` — clean
- [ ] `$env:PYTHONPATH='src'; python -m pytest -q` — <n> passed, <n> skipped
- [ ] `mypy src --ignore-missing-imports` — clean
- [ ] device: <what was run on the Pi, or "not run — needs hardware">

## Motion impact

<!-- One of: none / dry-run only / commands servos -->

## Authorship

<!--
Everything in this repository is published under a human name, and the record has to read that
way. Before opening the pull request:

- the author and committer of every commit are your own Git identity, and the message carries no
  trailer crediting a tool or a model;
- the title, this description, and any review comment or reply say nothing about how the text
  was produced;
- no token, WiFi credential or device hostname appears in the diff or the description;
- the branch lives on this repository rather than on a fork — a pull request opened from a fork
  is published under the fork owner, and nothing here can correct that afterwards.

A reviewer sends the pull request back if any of that is not true, and rewording a message is
cheaper than rewriting history.
-->
