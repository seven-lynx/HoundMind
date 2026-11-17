"""The shipped corpus is contract data: it must load, pass, and assert only documented fields."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from houndmind_ai.kernel.decisions import DecisionRecord
from tools.replay_decisions import (
    EXPECTATION_KEYS,
    check_case,
    load_corpus,
    load_records,
    main,
    run_corpus,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = REPO_ROOT / "docs" / "fixtures" / "clients"
CONTRACT = REPO_ROOT / "docs" / "CONTROL_API.md"


def _cases():
    return load_corpus(CORPUS)


def test_every_shipped_case_passes() -> None:
    cases = _cases()

    assert [case.id for case in cases] == ["obstacle-veto", "command-accepted", "stale-reading"]
    for case in cases:
        assert check_case(case) == [], case.id


def test_every_fixture_line_is_a_record_the_reader_accepts() -> None:
    """A fixture the schema has outgrown must break here, not pass quietly."""
    for case in _cases():
        records, skipped = load_records(case.decisions)

        assert records, case.id
        assert skipped == 0
        for record in records:
            again = DecisionRecord.from_dict(json.loads(json.dumps(record.to_dict())))
            assert again.to_dict() == record.to_dict()


def test_the_shipped_expectations_are_documented_in_the_contract() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("## 11. Conformance corpus")
    documented = text[start:]

    for key in EXPECTATION_KEYS:
        assert f"`{key}`" in documented, key


def test_the_cli_runs_the_shipped_corpus(capsys) -> None:
    assert main(["--corpus", str(CORPUS)]) == 0

    out = capsys.readouterr().out
    assert "3/3 passed" in out


def test_a_case_that_lies_is_a_failure(tmp_path, capsys) -> None:
    shutil.copytree(CORPUS, tmp_path / "corpus")
    manifest = json.loads((tmp_path / "corpus" / "corpus.json").read_text(encoding="utf-8"))
    manifest["cases"][0]["expect"]["last_intent"] = "sit"
    (tmp_path / "corpus" / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert run_corpus(tmp_path / "corpus") == 1
    assert "FAIL" in capsys.readouterr().out


def test_an_unknown_expectation_key_is_refused(tmp_path, capsys) -> None:
    (tmp_path / "a.jsonl").write_text("", encoding="utf-8")
    manifest = {
        "version": 1,
        "cases": [{"id": "x", "decisions": "a.jsonl", "expect": {"vibes": "good"}}],
    }
    (tmp_path / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert run_corpus(tmp_path) == 2
    assert "unknown key" in capsys.readouterr().out


def test_a_path_outside_the_corpus_is_refused(tmp_path) -> None:
    manifest = {
        "version": 1,
        "cases": [{"id": "x", "decisions": "../CONTROL_API.md", "expect": {"records": 1}}],
    }
    (tmp_path / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert run_corpus(tmp_path) == 2


def test_a_log_and_a_corpus_together_are_refused(capsys) -> None:
    assert main(["logs/houndmind_decisions.jsonl", "--corpus", str(CORPUS)]) == 2
    assert "not both" in capsys.readouterr().out
