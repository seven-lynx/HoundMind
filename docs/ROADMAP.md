# HoundMind Roadmap
> Living document of planned features and enhancements (updated 2025-11-01)

## Simulation & Testing
- Desktop PiDog simulation shim (drop-in replacement for `pidog.Pidog`)
  - Tier 0: no-op motion, fixed sensor values (for CI)
  - Tier 1: randomized time-varying signals with Gaussian noise
  - Tier 2: deterministic (seeded) for reproducible tests
  - Tier 3: (optional) ROS2/Gazebo or Webots physics integration
  - Activation: `HOUNDMIND_SIM=1` or config preset; keep orchestrators/services unchanged
- Simulator-backed unit/integration tests for PackMind and CanineCore
- GitHub Actions workflow to run tests on pushes/PRs

## Calibration & Orientation
- Voice-guided calibration flow with status prompts and LED cues
- Persisted per-surface calibration profiles (e.g., carpet, tile) with quick switch
- IMU orientation auto-biasing and drift monitoring

## Balance & Safety
- Minimal safe balance corrections on tilt (roll/pitch) with cooldowns and thresholds
- Safety modes: degraded-speed and scan-throttling under high CPU/temp/memory

## Mapping & Navigation
- Goal-directed exploration; frontier-based navigation
- Room identification and labeling; simple room graph for high-level goals
- Multi-session map merge with conflict resolution; export/import tools
- Path cost tuning UI and surface-aware speed adjustments

## Voice & Audio
- Hotword customization; offline STT option; noise-robust VAD tuning helpers
- Audio event profiles (alarm, environmental patterns) with behavior hooks

## UI, Telemetry & Reporting
- Local web dashboard: status, logs, map preview, recent scans, service health
- Exportable patrol reports with charts; session comparisons

## Developer Experience
- Config validation CLI; diff/apply presets; override files for site-local changes
- Rich logging setup (JSON + human logs) with rotation across modules
- Packaging & releases via GitHub Releases; optional pip extras for advanced services

## Documentation
- End-to-end tutorial: from first boot to autonomous exploration
- Troubleshooting playbook with common sensor/hardware issues
- API guides for extending services/behaviors and adding new modules
