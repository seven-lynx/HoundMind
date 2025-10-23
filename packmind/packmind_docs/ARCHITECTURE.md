# PackMind Modular Architecture

This document outlines the target modular architecture for the PackMind subsystem.

## Goals
- Orchestrator acts as a thin coordinator (lifecycle + state transitions).
- Pluggable behaviors and services via small registries/dependency injection.
- Hardware-safe on non-Pi hosts (graceful guards, no hard imports).
- Clear public API and single config source.

## Modules

- core/
  - context.py: AIContext (shared state)
  - types.py: enums and dataclasses
  - registry.py: lightweight registries for behaviors/services (decorators)
  - container.py: service container/DI (start/stop lifecycles)

- behaviors/
  - base_behavior.py
  - idle_behavior.py
  - patrolling_behavior.py
  - exploring_behavior.py
  - interacting_behavior.py
  - resting_behavior.py
  - playing_behavior.py
  - avoiding_behavior.py

- services/
  - sensor_service.py: polls hardware to produce SensorReading at a fixed rate (passive)
  - scanning_service.py: active ultrasonic/head scanning patterns (3-way, sweep, 360); returns structured scan data; always returns head to center; strict hardware-first (raises on missing readings; no PC fallbacks)
  - obstacle_service.py: consumes scanning outputs, performs analysis/avoidance, optional background loop during motion
  - energy_service.py: energy accounting + speed helpers
  - emotion_service.py: emotion computation + LED/sound feedback hooks
  - voice_service.py: intent registry + text processing
  - asr_service.py: microphone + wake-word + STT (optional)
  - navigation_service.py: SLAM + pathfinding + localization + calibration
  - log_service.py: in-memory ring + file append + report generation

- packmind_config.py: presets and validation
- orchestrator.py: init/start/stop, tick loop, state transitions, delegates to services/behaviors

## Dependency Injection

- BehaviorRegistry provides a simple map from BehaviorState -> Behavior instance.
- ServiceContainer centralizes service construction; orchestrator sources ScanningService and ObstacleService from the container by default.

## Configuration

- Single source of truth: `packmind/packmind_config.py` via `load_config` and `validate_config`.
- The orchestrator no longer provides an embedded fallback configuration.

## Contracts

- SensorService
  - start()/stop(), read_once() -> SensorReading, on_reading callback
- ObstacleService
  - analyze(scan)->metrics, avoid(scan)
  - optional start()/stop() background loop that requests scans from ScanningService while walking
  
- ScanningService
  - scan_three_way() -> dict[str, float]  (forward/left/right)
  - sweep_scan(angles: list[int], samples: int) -> dict[str|int, float]
  - start_continuous(mode: str, interval: float, on_scan: callable)
  - stop()
- EmotionService
  - compute_base_emotion(context, interaction_count, last_interaction, now)->EmotionalState
  - set_emotion(context, emotion, dog)
- EnergyService
  - update(context, reading, ts)
  - get_walk_speed/get_turn_speed(context, config)
- Voice/ASR
  - VoiceService.register(key,str->action), process_text(text, context)->bool
  - ASR service produces text and feeds VoiceService
- NavigationService
  - wrap SLAM/pathfinding/localizer; expose calibrate/show_map/navigate

## State Machine
- Orchestrator owns BehaviorState and swaps current behavior object (from registry).
- Each behavior implements execute(context) and optional on_enter/on_exit.

## Recent changes
- Extracted ScanningService and ObstacleService; orchestrator now delegates scanning, analysis, and avoidance.
- Added new behaviors: exploring, interacting, resting, playing.
- Introduced BehaviorRegistry and ServiceContainer; orchestrator uses them to assemble behaviors and services.
- Normalized configuration import to `packmind/packmind_config.py` and removed fallback in orchestrator.

## Error/edge cases
- dog is None or missing capabilities (host PC): services return safe defaults and avoid hardware calls.
- Timeouts and thread shutdown via stop events.
- Config toggles disable services cleanly.

## Public API
- Export Orchestrator, AIContext, BehaviorState, EmotionalState, and useful services from `packmind.__init__`.
