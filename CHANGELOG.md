# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and adheres to semantic-ish sections.

## [v2025.10.23] - 2025-10-23 - CanineCore stabilization, PackMind docs restructure, and legacy tests archived

### Added
- Centralized JSON logging in CanineCore via `utils/logging_setup.py` and `core/services/logging.py` with rotation controls (`LOG_FILE_MAX_MB`, `LOG_FILE_BACKUPS`).
- Expanded `canine_core/config/canine_config.py` with grouped options and presets (Simple, Patrol, Interactive).
- Control script (`canine_core/control.py`) supports running single behaviors, sequences, random cycles, and presets.

### Changed
- `core/orchestrator.py` now uses `CanineConfig` and optional preset selection instead of YAML; derives the run queue from `AVAILABLE_BEHAVIORS` when no explicit queue is provided.
- Documentation: updated `canine_core/README.md` and `canine_core/canine_core_config_guide.md` to reflect the Python-based config and remove YAML references.

### Deprecated
- `core/services/config.py` deprecated and replaced with a hard error directing users to `config/canine_config.py`.

### Removed
- YAML-based configuration loader pathway in CanineCore.

### Notes
- Legacy bridge modules under `canine_core/core/` (e.g., `global_state.py`, `memory.py`, `state_functions.py`, `master.py`) are retained for backward compatibility.
- Tests migrated to `legacy/` with `_test` suffix removed; README updated accordingly.

