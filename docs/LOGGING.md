# Logging Runbook

Status: **runbook** — what to do once something has already gone wrong.
Pairs with: `docs/HOUNDMIND_PROGRAMMING_GUIDE.md` §10 (where logs come from),
`docs/CONTROL_API.md` §2 (`/logs`, `/support-bundle`)

This document describes how to collect logs, common troubleshooting commands, and quick `jq` examples
for parsing JSON logs produced by HoundMind.

Paths

- Primary log directory: `logs/` (`settings.logging.log_dir`, `config/settings.jsonc:1044`)
- Runtime log: `logs/houndmind.log` — the `logging` module, every level
  (`settings.logging.log_file_name`, `:1045`)
- Event JSONL: `logs/houndmind_events.jsonl` — the `event_log` module, one snapshot per interval,
  capped at `event_log_max_mb` (5) and then renamed to `.1`
  (`settings.logging.event_log_path`, `:1059-1062`)
- Decision JSONL: `logs/houndmind_decisions.jsonl` — the `decision_log` module, one record per tick
  with intent, source, vetoes and inputs (`settings.logging.decision_log_path`, `:1071`)

All three files are separate on purpose; which one you want depends on the question. The runtime log
says what the process did, the event log says what the dog's state was every half second, and the
decision log says why the tick chose what it chose.

Collect a support bundle (recommended):

1. Gather files into a zip (module available as `python -m tools.collect_support_bundle` — recommended after `pip install -e .` or with `PYTHONPATH=src`).

Quick manual commands

- Tail live console output:

  ```powershell
  Get-Content -Path logs\\houndmind.log -Wait -Tail 50
  ```

- Show last 200 lines of the main log (POSIX):

  ```bash
  tail -n 200 logs/houndmind.log
  ```

- Extract JSON fields with `jq` (assumes JSON lines):

  ```bash
  # Print timestamp and level for each entry
  jq -r '.timestamp + " " + .level + " " + .message' logs/houndmind.log
  ```

Troubleshooting tips
- If logs are missing, verify `settings.logging.log_dir` in `config/settings.jsonc`.
- Confirm file permissions and disk space on-device.
- To enable file logging, set `settings.logging.enable_file` to `true` (default is enabled for on-device installs).

Support bundle contents

There are **two** bundle producers and they do not carry the same files. Pick by what you need.

**From the shell** — `python -m tools.collect_support_bundle out.zip` (`src/tools/collect_support_bundle.py`).
This is the one to send when the problem is something the process logged.

- `metadata.json` — timestamp, git commit, and the trace id (taken from `HOUNDMIND_TRACE_ID` if set,
  otherwise found by scanning the newest log)
- every file in `logs/`, plus a `.tail.txt` for the large ones
- `config/settings.jsonc` — the runtime config as it was

**Over the network** — `GET /api/v1/support-bundle`, `admin` scope (`services/api.py:210`). No log
files; this is the one to ask a user for when you cannot reach the device yourself.

- `meta.json`, `state.json`, `modules.json` — identity, the live snapshot, module status
- `config.json` — the effective config with secrets redacted
- `audit.json`, `sessions.json` — the motion audit trail and live sessions
- `README.txt` — what the bundle is, and the note that file logs are not included yet

Privacy
- Both bundles may include local config and logs. Review and remove any personally identifiable data before sharing externally.
