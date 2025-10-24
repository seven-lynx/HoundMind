# CanineCore 🔧
> Author: 7Lynx · Doc Version: 2025.10.24

Modern, modular behavior framework for PiDog. CanineCore provides an async orchestrator, shared services, and a clean Behavior interface so you can compose, run, and extend dog behaviors without wiring hardware details in every module.

Independence: CanineCore and PackMind are related but distinct projects. They do not import or call into each other.

## 📁 System Architecture

```
canine_core/
├── core/
│   ├── orchestrator.py      # Wires services, resolves aliases, runs behaviors
│   ├── interfaces.py        # Behavior, BehaviorContext, Event contracts
│   ├── state.py             # Validated StateStore (no legacy global state)
│   ├── bus.py memory.py emotions.py global_state.py (legacy bridge if present)
│   └── services/            # sensors.py, motion.py, emotions.py, voice.py, hardware.py, logging.py
├── behaviors/               # Class-based behaviors (auto-discovered)
├── config/                  # Defaults + presets
└── control.py               # Beginner-friendly interactive launcher
```

## 🔄 How It Works

1) Orchestrator (`core/orchestrator.py`)
- Loads behaviors by alias or explicit module:Class
- Injects shared services via BehaviorContext
- Manages lifecycle: start → on_event → stop

2) State & Services
- `state.py` provides a validated central store
- Services expose hardware-safe capabilities (sim-safe where possible)
- Access through `BehaviorContext` only-avoid direct hardware imports

3) Behaviors
- Class-based, discoverable via `BEHAVIOR_CLASS` or a `get_behavior()` factory
- Use MotionService, SensorService, EmotionService, VoiceService

## 🚀 Run It

From the project root:

```powershell
python main.py                # Orchestrator default
python canine_core/control.py # Interactive control menu
```

## 🎮 Interactive Control

- Automatic mode cycles behaviors intelligently
- Press the interruption key to select behaviors manually
## What’s inside

- Orchestrator (async) to run one or many behaviors
- Event bus and validated state store
- Shared services (sim‑safe): Sensors, Motion, Emotions (RGB), Voice, Hardware, Logging, Config
- Behavior v2 contract with simple lifecycle start/on_event/stop and auto‑discovery via BEHAVIOR_CLASS

Directory highlights:

```
canine_core/
├─ behaviors/           # First‑class behaviors (class‑based)
├─ config/              # Python config with presets
├─ core/
│  ├─ orchestrator.py   # Wires services, resolves aliases, runs behaviors
│  ├─ interfaces.py     # Behavior, BehaviorContext, Event contracts
│  ├─ state.py          # Validated StateStore (no legacy global state)
│  └─ services/         # sensors.py, motion.py, emotions.py, voice.py, hardware.py, logging.py
└─ control.py           # Beginner‑friendly interactive launcher
```

## Run it (interactive)

```powershell
python canine_core/control.py
```

You’ll be prompted to run a single behavior, a sequence, a random cycle, or a preset. The launcher uses beginner‑friendly aliases that the orchestrator resolves:

- idle_behavior
- smart_patrol (smarter_patrol is internally mapped here)
- voice_patrol
- whisper_voice_control
- guard_mode
- find_open_space
- reactions

## Configuration

- Canonical file: `canine_core/config/canine_config.py` (Python class with sensible defaults and presets: simple, patrol, interactive, safety-first)
- Presets are provided via `canine_core/config/canine_config.py` (Simple, Patrol, Interactive, Safety-First)
- Presets expose an `AVAILABLE_BEHAVIORS` list used by `control.py`
- See the detailed guide: `docs/canine_core_config_guide.md`

Key concepts used by behaviors:

- Movement speeds and step counts (WALK_STEPS_*, TURN_STEPS_*, SPEED_*)
- Obstacle thresholds and scan timing (OBSTACLE_*, HEAD_SCAN_*, OBSTACLE_SCAN_INTERVAL)
- Voice settings (WAKE_WORD, VOICE_* volumes)
- Feature toggles (ENABLE_* flags)

Safety-First preset highlights:
- Enables Safety, IMU, Battery monitors and default hooks
- Slower movement, wider safe distances, and "no scan while moving"
- Narrower head scan range with longer settle time

## Behavior contract (v2)

Implement a class with the lifecycle and expose it via `BEHAVIOR_CLASS`:

```python
from canine_core.core.interfaces import Behavior, BehaviorContext, Event

class MyBehavior(Behavior):
    async def start(self, ctx: BehaviorContext) -> None:
        ctx.logger.info("MyBehavior starting")
        ctx.emotions.set_color((0, 64, 255))

    async def on_event(self, event: Event) -> None:
        pass

    async def stop(self) -> None:
        pass

BEHAVIOR_CLASS = MyBehavior
```

The orchestrator auto‑discovers behaviors via `BEHAVIOR_CLASS` or a `get_behavior()` factory. It also supports explicit `module:Class` references and friendly aliases.

## Services you can use

- SensorService: read distances in centimeters (cm), basic head sweeps (sim‑safe)
- MotionService: `act(action, **kwargs)`, `wait()` for actions
- EmotionService: LED color/effects with safety and an `update(color, effect_name=None)` helper
- VoiceService: async command stream with optional wake word
- HardwareService: wraps Pidog/RGB when available; safe no‑ops on dev hosts
- LoggingService: simple, prefixed logging
- NEW — IMUService: optional accelerometer/gyro readings; simple tilt checks
- NEW — SafetyService: tilt emergency detection with safe pose and event publish
- NEW — BatteryService: battery read + low/critical event publish (if hardware supports it)
- NEW — TelemetryService: periodic lightweight snapshots to the logger
- NEW — SensorsFacade: wrappers for sound direction (ears) and dual touch (sim-safe)
 - NEW — EnergyService: simple 0..1 energy model with decay/recovery and interaction boosts (optional)
 - NEW — BalanceService: IMU-based stability assessment with events (optional; requires IMU)
 - NEW — AudioProcessingService: optional VAD/noise helpers (uses webrtcvad if available)
 - NEW — ScanningCoordinator: head sweep helper that publishes scan_start/scan_end and samples distances (optional)

Access these via `BehaviorContext` (injected by the orchestrator) to avoid direct hardware imports.

## Included behaviors

- IdleBehavior: subtle ambient actions
- SmartPatrolBehavior: unified smart/smarter patrol
- GuardModeBehavior: simple forward proximity alert/scan
- ReactionsBehavior: quick IMU/touch/sound reactions (config‑driven)
- FindOpenSpaceBehavior: scan‑select‑move toward open direction
- VoicePatrolBehavior: wake‑word voice control
- WhisperVoiceControlBehavior: free‑form voice control (wake word optional)
 - HardwareSmokeBehavior: minimal OK/FAIL checks for sensors, IMU, battery, ears/touch, and optional limited motion

## Migration notes (legacy → CanineCore)

- Removed legacy global state, master.py, memory/emotions/state_functions, and all legacy behaviors
- No `actions.py` dependency: use MotionService, SensorService, and EmotionService instead
- `smarter_patrol` consolidated into `smart_patrol` (orchestrator keeps the alias)
- For a one‑off PiDog method inventory, see `docs/listing_pidog_functions.md`

## Troubleshooting

- On development machines without PiDog hardware, hardware‑backed calls become safe no‑ops and will log a warning on init
- Voice behavior requires audio stack on the host; disable via `ENABLE_VOICE_COMMANDS=False` or choose a non‑voice preset

## Quick Pi checkup

Run on the PiDog to verify CanineCore installs and basic hardware access:

```powershell
python tools/caninecore_checkup.py --scope import
python tools/caninecore_checkup.py --scope services               # instantiate services
python tools/caninecore_checkup.py --scope all --move             # include limited motion/head sweep
```

## See also

- Config guide: `docs/canine_core_config_guide.md`
- Function inventory script: `docs/listing_pidog_functions.md`
- Standalone AI (PackMind): `packmind/` for ready‑to‑run experiences
