from __future__ import annotations
import asyncio
import importlib
from typing import Dict, Any

from .interfaces import Behavior, BehaviorContext, Event
from .bus import EventBus
from .state import StateStore
from .services.logging import LoggingService
from .services.hardware import HardwareService
from ..config.canine_config import PRESETS, CanineConfig
from .services.sensors import SensorService
from .services.motion import MotionService
from .services.emotions import EmotionService
from .services.voice import VoiceService
from .services.imu import IMUService
from .services.safety import SafetyService
from .services.battery import BatteryService
from .services.telemetry import TelemetryService
from .hooks import HookRegistry, default_hooks_factory
from .watchdog import BehaviorWatchdog
from .services.sensors_facade import SensorsFacade

class LegacyThreadBehavior:
    """Adapter to run legacy modules exposing start_behavior() in a thread.
    Stop is best-effort (not supported by legacy modules).
    """
    def __init__(self, dotted_path: str, name: str | None = None) -> None:
        self.module_path = dotted_path
        self.name = name or dotted_path.split(".")[-1]
        self._thread = None
        self._stop = False

    async def start(self, ctx: BehaviorContext) -> None:
        import threading
        mod = importlib.import_module(self.module_path)
        if not hasattr(mod, "start_behavior"):
            ctx.logger.error(f"Legacy module {self.module_path} has no start_behavior()")
            return
        target = getattr(mod, "start_behavior")
        self._stop = False
        # Start in thread; no args by convention
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()
        ctx.logger.info(f"Started legacy behavior: {self.name}")

    async def on_event(self, event: Event) -> None:
        # Legacy modules are not event-driven; ignore
        return

    async def stop(self) -> None:
        # Best-effort: cannot stop cleanly without behavior cooperation
        return

class Orchestrator:
    def __init__(self, config_path: str | None) -> None:
        # Use new Python-based config with optional preset string
        # If config_path matches a preset name, use that; otherwise default
        if isinstance(config_path, str) and config_path.lower() in PRESETS:
            self.config = PRESETS[config_path.lower()]()
        else:
            # Default config (class with sensible defaults)
            self.config = CanineConfig()
        self.bus = EventBus()
        self.state = StateStore()
        self.logger = LoggingService(prefix="Orchestrator")
        self.hardware = HardwareService()
        self._ctx = None
        self._active: Behavior | None = None
        self.hooks: HookRegistry | None = None
        # alias map for beginner-friendly names
        self.aliases: Dict[str, str] = {
            "idle_behavior": "canine_core.behaviors.idle_behavior",
            "smart_patrol": "canine_core.behaviors.smart_patrol",
            # smarter_patrol is now combined with smart_patrol
            "smarter_patrol": "canine_core.behaviors.smart_patrol",
            "voice_patrol": "canine_core.behaviors.voice_patrol",
            "guard_mode": "canine_core.behaviors.guard_mode",
            "whisper_voice_control": "canine_core.behaviors.whisper_voice_control",
            "find_open_space": "canine_core.behaviors.find_open_space",
            "reactions": "canine_core.behaviors.reactions",
            "event_hooks_demo": "canine_core.behaviors.event_hooks_demo",
            "hardware_smoke": "canine_core.behaviors.hardware_smoke",
        }

    async def init(self) -> None:
        # Initialize hardware
        try:
            self.hardware.init()
            self.logger.info("Hardware initialized")
        except Exception as e:
            self.logger.warning(f"Hardware init failed on this host: {e}")
        # Build context (services like sensors/emotions/memory could be added later)
        sensors = SensorService(self.hardware)
        motion = MotionService(self.hardware)
        emotions = EmotionService(self.hardware, enabled=getattr(self.config, "ENABLE_EMOTIONAL_SYSTEM", True))
        voice = VoiceService(
            wake_word=str(getattr(self.config, "WAKE_WORD", "pidog")),
            enabled=bool(getattr(self.config, "ENABLE_VOICE_COMMANDS", True)),
        )
        # Optional services controlled by flags
        imu = IMUService(self.hardware) if bool(getattr(self.config, "ENABLE_IMU_MONITOR", True)) else None
        safety = SafetyService(
            self.hardware,
            imu,
            publish=self.bus.publish,
            max_tilt_deg=float(getattr(self.config, "SAFETY_MAX_TILT_DEG", 45)),
            emergency_pose=str(getattr(self.config, "EMERGENCY_STOP_POSE", "crouch")),
        ) if bool(getattr(self.config, "ENABLE_SAFETY_SUPERVISOR", True)) else None
        battery = BatteryService(
            self.hardware,
            publish=self.bus.publish,
            low_pct=float(getattr(self.config, "LOW_BATTERY_THRESHOLD", 20)),
            critical_pct=float(getattr(self.config, "CRITICAL_BATTERY_THRESHOLD", 10)),
        ) if bool(getattr(self.config, "ENABLE_BATTERY_MONITOR", True)) else None
        telemetry = TelemetryService(
            self.hardware,
            logger=self.logger,
            interval_s=float(getattr(self.config, "LOG_STATUS_INTERVAL", 10)),
            imu=imu,
            battery=battery,
        ) if bool(getattr(self.config, "ENABLE_TELEMETRY", False)) else None
        sensors_facade = SensorsFacade(self.hardware) if bool(getattr(self.config, "ENABLE_SENSORS_FACADE", True)) else None
        self._ctx = BehaviorContext(
            hardware=self.hardware,
            sensors=sensors,
            emotions=emotions,
            motion=motion,
            voice=voice,
            memory=None,
            state=self.state,
            logger=self.logger,
            config=self.config,
            publish=self.bus.publish,
            safety=safety,
            battery=battery,
            imu=imu,
            telemetry=telemetry,
            sensors_facade=sensors_facade,
        )
        # Hooks: subscribe default handlers if enabled
        if bool(getattr(self.config, "ENABLE_DEFAULT_HOOKS", True)):
            self.hooks = HookRegistry(self.bus.publish, self.bus.subscribe)
            self.hooks.register_many(default_hooks_factory(self._ctx))
        # Optionally expose extra services on orchestrator for future use
        self.voice = voice
        self.motion = motion
        self.safety = safety
        self.battery = battery
        self.imu = imu
        self.telemetry = telemetry
        self.sensors_facade = sensors_facade

    def _resolve_behavior(self, spec: str) -> Behavior:
        """Resolve a behavior spec into a Behavior instance.

        Supports:
        - Alias names (e.g., "smart_patrol")
        - Dotted module path exposing BEHAVIOR_CLASS (e.g., canine_core.behaviors.idle_behavior)
        - Explicit class path with colon (e.g., module:ClassName)
        - Legacy modules exposing start_behavior() (wrapped)
        """
        dotted = self.aliases.get(spec, spec)
        # Explicit class reference: module:Class
        if ":" in dotted:
            mod_name, cls_name = dotted.split(":", 1)
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            inst: Behavior = cls()  # type: ignore[call-arg]
            return inst
        # Module with BEHAVIOR_CLASS or get_behavior()
        try:
            mod = importlib.import_module(dotted)
            if hasattr(mod, "BEHAVIOR_CLASS"):
                cls = getattr(mod, "BEHAVIOR_CLASS")
                return cls()  # type: ignore[call-arg]
            if hasattr(mod, "get_behavior"):
                return mod.get_behavior()  # type: ignore[no-any-return]
            if hasattr(mod, "start_behavior"):
                return LegacyThreadBehavior(dotted_path=dotted)
        except Exception:
            # Fallback to legacy adapter
            pass
        return LegacyThreadBehavior(dotted_path=dotted)

    async def run(self) -> None:
        await self.init()
        # Determine which behaviors to run:
        # Prefer explicit behavior_queue if present; otherwise use AVAILABLE_BEHAVIORS
        queue = getattr(self.config, "behavior_queue", None)
        if not queue:
            queue = list(getattr(self.config, "AVAILABLE_BEHAVIORS", ["idle_behavior"]))
        # Simple loop over configured/available behaviors
        for spec in queue:
            beh = self._resolve_behavior(spec)
            self._active = beh
            # mypy: _ctx is initialized in init()
            assert self._ctx is not None
            # Start behavior with watchdog enforcement
            enable_wd = bool(getattr(self.config, "ENABLE_BEHAVIOR_WATCHDOG", True))
            max_sec = float(getattr(self.config, "WATCHDOG_MAX_BEHAVIOR_S", 45.0))
            base_dur = float(getattr(self.config, "BEHAVIOR_MIN_DWELL_S", 10.0))
            dur = min(base_dur, max_sec) if enable_wd else base_dur
            name = getattr(beh, "name", str(spec))
            wd = BehaviorWatchdog(max_dwell_s=dur if enable_wd else 0.0,
                                   max_errors=int(getattr(self.config, "WATCHDOG_MAX_ERRORS", 1)),
                                   logger=self.logger) if enable_wd else None
            # Start
            try:
                await beh.start(self._ctx)
            except Exception as e:
                self.logger.error(f"Behavior {name} start() failed: {e}")
                if wd:
                    wd.record_error("start", e)
            if wd:
                wd.start(name)
            # Sleep in small slices to allow early stop if watchdog triggers
            try:
                slept = 0.0
                slice_s = 0.5
                total = dur
                while total <= 0 or slept < total:
                    if wd and wd.should_stop():
                        self.logger.info(f"Watchdog stopping {name} after {wd.elapsed_s:.1f}s")
                        break
                    await asyncio.sleep(slice_s)
                    slept += slice_s
            except asyncio.CancelledError:
                pass
            # Stop
            try:
                await beh.stop()
            except Exception as e:
                self.logger.error(f"Behavior {name} stop() failed: {e}")
                if wd:
                    wd.record_error("stop", e)
        self.logger.info("Orchestration loop complete")

    async def run_single(self, spec: str, duration: float = 15.0) -> None:
        await self.init()
        beh = self._resolve_behavior(spec)
        assert self._ctx is not None
        enable_wd = bool(getattr(self.config, "ENABLE_BEHAVIOR_WATCHDOG", True))
        max_sec = float(getattr(self.config, "WATCHDOG_MAX_BEHAVIOR_S", 45.0))
        dur = min(duration, max_sec) if enable_wd else duration
        name = getattr(beh, "name", str(spec))
        wd = BehaviorWatchdog(max_dwell_s=dur if enable_wd else 0.0,
                               max_errors=int(getattr(self.config, "WATCHDOG_MAX_ERRORS", 1)),
                               logger=self.logger) if enable_wd else None
        try:
            await beh.start(self._ctx)
        except Exception as e:
            self.logger.error(f"Behavior {name} start() failed: {e}")
            if wd:
                wd.record_error("start", e)
        if wd:
            wd.start(name)
        try:
            slept = 0.0
            slice_s = 0.5
            while dur <= 0 or slept < dur:
                if wd and wd.should_stop():
                    self.logger.info(f"Watchdog stopping {name} after {wd.elapsed_s:.1f}s")
                    break
                await asyncio.sleep(slice_s)
                slept += slice_s
        finally:
            try:
                await beh.stop()
            except Exception as e:
                self.logger.error(f"Behavior {name} stop() failed: {e}")
                if wd:
                    wd.record_error("stop", e)

    async def run_sequence(self, specs: list[str], durations: list[float] | None = None) -> None:
        await self.init()
        durations = durations or [15.0] * len(specs)
        for spec, dur_in in zip(specs, durations):
            beh = self._resolve_behavior(spec)
            assert self._ctx is not None
            enable_wd = bool(getattr(self.config, "ENABLE_BEHAVIOR_WATCHDOG", True))
            max_sec = float(getattr(self.config, "WATCHDOG_MAX_BEHAVIOR_S", 45.0))
            dur = min(dur_in, max_sec) if enable_wd else float(dur_in)
            name = getattr(beh, "name", str(spec))
            wd = BehaviorWatchdog(max_dwell_s=dur if enable_wd else 0.0,
                                   max_errors=int(getattr(self.config, "WATCHDOG_MAX_ERRORS", 1)),
                                   logger=self.logger) if enable_wd else None
            try:
                await beh.start(self._ctx)
            except Exception as e:
                self.logger.error(f"Behavior {name} start() failed: {e}")
                if wd:
                    wd.record_error("start", e)
            if wd:
                wd.start(name)
            try:
                slept = 0.0
                slice_s = 0.5
                while dur <= 0 or slept < dur:
                    if wd and wd.should_stop():
                        self.logger.info(f"Watchdog stopping {name} after {wd.elapsed_s:.1f}s")
                        break
                    await asyncio.sleep(slice_s)
                    slept += slice_s
            finally:
                try:
                    await beh.stop()
                except Exception as e:
                    self.logger.error(f"Behavior {name} stop() failed: {e}")
                    if wd:
                        wd.record_error("stop", e)

    async def run_random_cycle(self, choices: list[str], min_sec: float = 20, max_sec: float = 45) -> None:
        import random
        await self.init()
        history: list[str] = []
        while True:
            pick = random.choice([c for c in choices if c not in history[-2:]] or choices)
            dur_pick = random.randint(int(min_sec), int(max_sec))
            beh = self._resolve_behavior(pick)
            assert self._ctx is not None
            enable_wd = bool(getattr(self.config, "ENABLE_BEHAVIOR_WATCHDOG", True))
            cap = float(getattr(self.config, "WATCHDOG_MAX_BEHAVIOR_S", 45.0))
            dur = min(float(dur_pick), cap) if enable_wd else float(dur_pick)
            name = getattr(beh, "name", str(pick))
            wd = BehaviorWatchdog(max_dwell_s=dur if enable_wd else 0.0,
                                   max_errors=int(getattr(self.config, "WATCHDOG_MAX_ERRORS", 1)),
                                   logger=self.logger) if enable_wd else None
            try:
                await beh.start(self._ctx)
            except Exception as e:
                self.logger.error(f"Behavior {name} start() failed: {e}")
                if wd:
                    wd.record_error("start", e)
            if wd:
                wd.start(name)
            self.logger.info(f"Running {pick} for up to {dur:.1f}s")
            try:
                slept = 0.0
                slice_s = 0.5
                while dur <= 0 or slept < dur:
                    if wd and wd.should_stop():
                        self.logger.info(f"Watchdog stopping {name} after {wd.elapsed_s:.1f}s")
                        break
                    await asyncio.sleep(slice_s)
                    slept += slice_s
            finally:
                try:
                    await beh.stop()
                except Exception as e:
                    self.logger.error(f"Behavior {name} stop() failed: {e}")
                    if wd:
                        wd.record_error("stop", e)
            history.append(pick)

async def main_async(config_preset: str | None = None) -> None:
    # Optionally pass a preset name from PRESETS; defaults to CanineConfig
    orch = Orchestrator(config_preset)
    await orch.run()

def main(config_preset: str | None = None) -> None:
    asyncio.run(main_async(config_preset))

if __name__ == "__main__":
    main()
