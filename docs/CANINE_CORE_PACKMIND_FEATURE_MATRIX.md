# CanineCore ⇄ PackMind Feature Matrix (2025.10.30)
> Author: 7Lynx · Doc Version: 2025.10.30

This matrix maps high-level capabilities across the two stacks. CanineCore exposes modular, user-configurable building blocks. PackMind delivers a turnkey companion experience built on those fundamentals. Entries marked **(planned)** or **(in progress)** indicate features that still need full implementation or integration in the noted stack.

## Core Principles

- **CanineCore**: modular sandbox for tinkering, education, and selective feature enablement.
- **PackMind**: cohesive AI pet that blends the same capabilities into a seamless “press start and enjoy” experience.
- **Bridge Philosophy**: improvements in PackMind should inspire modular equivalents in CanineCore, and CanineCore experiments can graduate into PackMind.

## Feature Comparison

| Capability | CanineCore Modules | PackMind Modules | Notes |
| --- | --- | --- | --- |
| Autonomous patrol & obstacle handling | `behaviors/smart_patrol.py` | `behaviors/patrolling_behavior.py`, `nav/pathfinding.py` | PackMind uses advanced pathfinding; CanineCore patrol still needs person detection integration **(planned)** |
| Sensor fusion mapping & localization | (some experiments in `core/services/scanning.py`, `core/services/imu.py`) **(planned)** | `mapping/home_mapping.py`, `localization/sensor_fusion_localization.py` | Full sensor fusion not yet exposed in CanineCore |
| Voice & audio interaction | `core/services/voice.py`, `behaviors/voice_patrol.py` | `services/voice_service.py`, `services/enhanced_audio_processing_service.py` | CanineCore supports modular voice, PackMind layers NLP and enhanced audio pipeline |
| Emotion & LED system | `core/services/emotions.py`, `behaviors/reactions.py` | `services/emotion_service.py` | LED reactions aligned conceptually; PackMind may need API hooks for educational parity |
| Touch / IMU reactions | `behaviors/reactions.py` | Integrated into PackMind orchestrator **(planned)** | PackMind needs the refined reaction set ported from CanineCore |
| Hardware self-test | `behaviors/hardware_smoke.py` **(in progress)** | `services/calibration_service.py`, `services/health_monitor.py` | CanineCore self-test pending; PackMind health monitor exists but calibration UI still maturing |
| Open-space exploration | `behaviors/find_open_space.py` **(in progress)** | `behaviors/exploring_behavior.py`, `mapping/home_mapping.py` | PackMind exploration uses mapping; CanineCore needs ultrasonic/camera integration |
| Safety & watchdog | `core/services/safety.py`, `core/watchdog.py` | `services/safety_watchdog.py`, `orchestrator` safeguards | Both stacks cover safety; logic should remain consistent |
| Learning & memory | `core/services/learning.py`, `core/memory.py` | `core/context.py`, `services/dynamic_balance_service.py` (historical learning), `orchestrator` | APIs diverge; alignment roadmap needed |
| Visualization & exports | `tools/caninecore_checkup.py` **(planned)** | `visualization/map_visualization.py` | CanineCore lacks real-time visualization |
| Energy & battery management | `core/services/energy.py`, `core/services/battery.py` | `services/energy_service.py` | Ensure telemetry parity |

## Roadmap & Gaps

- **CanineCore parity enhancements**: sensor fusion mapping, person-aware patrol, open-space finder, visualization tooling.
- **PackMind refinements**: adopt latest CanineCore reactions, expose modular hooks for advanced users.
- **Shared documentation**: update this matrix alongside CalVer releases to keep the ecosystem transparent.
- **Educational path**: highlight how PackMind features translate into CanineCore lessons/modules for users who want to tinker.

## Updating This Matrix

1. When a feature graduates from “planned” to “implemented,” update the status and CalVer.
2. If new capabilities appear in either stack, add a row.
3. Keep notes concise, pointing to canonical module paths.
4. For major releases, mention the matrix in release notes so users know what’s new.

---
Last updated: 2025.10.30
