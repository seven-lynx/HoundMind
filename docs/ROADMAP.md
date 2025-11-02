 # HoundMind Roadmap
> Living document of planned features and enhancements (updated 2025-11-01)

## Priorities (next major updates)

P1 — Live Web Dashboard + Telemetry (recommended first)
- Backend (FastAPI + WebSocket): `/status`, `/events` stream, `/control` (safe ops), map snapshot endpoint
- Data feeds: health, scans, face-lite events, audio levels, mapping stats
- Frontend: minimal (htmx/Alpine) Status + Events + Controls
- Security: LAN-only by default; optional basic auth
- Config: TELEMETRY_ENABLED; zero overhead when disabled
- Acceptance: live vitals/events visible; trigger a scan/head move; no Pi 3B regressions when disabled

P2 — TFLite Face Embeddings Backend (accuracy upgrade, still light)
- `FACE_BACKEND = "tflite"`; quantized MobileFaceNet-lite (or similar) + cosine similarity
- Keep Haar detection; replace LBPH when selected
- Trainer + thresholds; migration notes from LBPH
- Acceptance: Pi 3B ~1–2s detect+recognize cadence with better identity stability

P3 — Simulation‑backed CI + smoke tests
- GH Actions: imports, orchestrator boot (sim), short service ticks; logs as artifacts
- Coverage + lint (relaxed for enum/typing quirks); badge in README

P4 — Goal‑directed Navigation v2 (labels/anchors, doorway biasing)
- Goal API: go-to anchor/label; room labeling workflow; doorway/safe-path bias
- Basic docking/return-to-base behavior

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
- [ ] Goal-directed Navigation v2 (P4)
  - [ ] Anchors/labels as goals; doorway and safe-path biasing in planner
  - [ ] Labeling workflow; room graph abstraction
  - [ ] Basic docking/return-to-base behavior; acceptance tests

## Voice & Audio
- Hotword customization; offline STT option; noise-robust VAD tuning helpers
- Audio event profiles (alarm, environmental patterns) with behavior hooks

## Face Recognition (future backends)
- [ ] TFLite embeddings backend (P2)
  - [ ] Add `FACE_BACKEND = "tflite"` and include quantized model weights
  - [ ] Embedding store + cosine similarity; thresholds and trainer CLI
  - [ ] Keep Haar detection; swap LBPH only when `tflite` selected
  - [ ] Validate on Pi 3B: ~1–2s cadence; CPU within budget; doc migration

## UI, Telemetry & Reporting
- [ ] Local web dashboard (P1): status, logs, map preview, recent scans, service health
  - [ ] FastAPI + WebSocket backend (`/status`, `/events`, `/control`, `/map/snapshot.png`)
  - [ ] Orchestrator hooks: publish health, scan summaries, face-lite events, audio level
  - [ ] Minimal frontend (htmx/Alpine) showing Status, Recent Events, Controls
  - [ ] Config-gated (TELEMETRY_ENABLED, intervals); LAN-only by default; optional basic auth
  - [ ] Docs + troubleshooting
- [ ] Exportable patrol reports with charts; session comparisons

## Developer Experience
- Config validation CLI; diff/apply presets; override files for site-local changes
- Rich logging setup (JSON + human logs) with rotation across modules
- Packaging & releases via GitHub Releases; optional pip extras for advanced services
- [ ] Simulation-backed CI (P3)
  - [ ] Action: run sim imports + orchestrators + short service ticks
  - [ ] Store logs as artifacts; optionally JSON status snapshot
  - [ ] Coverage + lint; add CI badge in README

## Documentation
- End-to-end tutorial: from first boot to autonomous exploration
- Troubleshooting playbook with common sensor/hardware issues
- API guides for extending services/behaviors and adding new modules
