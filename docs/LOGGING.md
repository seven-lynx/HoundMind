# Logging Runbook

This document describes how to collect logs, common troubleshooting commands, and quick `jq` examples for parsing JSON logs produced by HoundMind.

Paths
- Primary log directory: `logs/`
- Primary rotating log file: `logs/houndmind.log`
- Event JSONL (if enabled): `logs/events.jsonl`

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
- `logs/` files (rotated files and current file)
- `config/settings.jsonc` (current runtime settings)
- `pyproject.toml` and `README.md` for environment context
- `metadata.json` with timestamp and git commit (if available)

Privacy
- Support bundles may include local config and logs. Review and remove any personally identifiable data before sharing externally.
