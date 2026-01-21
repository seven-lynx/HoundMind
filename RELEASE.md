# HoundMind Release Checklist

Version: v2026.01.18 • Author: 7Lynx

This checklist provides a minimal, repeatable release process for Pi3 and Pi4 presets.

## Pre-release
- [ ] Update version in pyproject.toml
- [ ] Run unit tests (pytest)
- [ ] Run smoke test on hardware (tools/smoke_test.py)
- [ ] Run hardware checkup (tools/hardware_checkup.py)
 - [ ] Run smoke test on hardware (src/tools/smoke_test.py)
 - [ ] Run hardware checkup (src/tools/hardware_checkup.py)
 - [ ] Run smoke test on hardware (`python -m tools.smoke_test`)
 - [ ] Run hardware checkup (`python -m tools.hardware_checkup`)
- [ ] Verify config defaults (config/settings.jsonc)
- [ ] Update README.md with any behavior/config changes

## Packaging
- [ ] Build a source distribution and wheel (python -m build)
- [ ] Validate install from wheel on a clean venv
- [ ] Verify requirements-lite.txt on Pi3

## Tagging
- [ ] Create a git tag (e.g., v0.1.0)
- [ ] Push tag to remote

## Release Notes
- [ ] Summarize changes since last release
- [ ] Include known limitations (Pi3 vs Pi4)
- [ ] Note any breaking config changes
