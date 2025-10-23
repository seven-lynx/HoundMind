from __future__ import annotations
import asyncio
import importlib
from typing import Dict, Any

from .interfaces import Behavior, BehaviorContext, Event
from .bus import EventBus
from .state import StateStore
from .services.logging import LoggingService
from .services.hardware import HardwareService
from .services.config import load_config
from ..config.pidog_config import PRESETS, CanineConfig

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
        # Try YAML first; if missing, fall back to Python config defaults
        self.config = load_config(config_path or "canine_core/config/canine_core.yaml")
        self.bus = EventBus()
        self.state = StateStore()
        self.logger = LoggingService(prefix="Orchestrator")
        self.hardware = HardwareService()
        self._ctx = None
        self._active: Behavior | None = None
        # alias map for beginner-friendly names
        self.aliases: Dict[str, str] = {
            "idle_behavior": "canine_core.behaviors.idle_behavior",
            "smart_patrol": "canine_core.behaviors.smart_patrol",
            "smarter_patrol": "canine_core.behaviors.smarter_patrol",
            "voice_patrol": "canine_core.behaviors.voice_patrol",
            "guard_mode": "canine_core.behaviors.guard_mode",
            "whisper_voice_control": "canine_core.behaviors.whisper_voice_control",
            "find_open_space": "canine_core.behaviors.find_open_space",
            "reactions": "canine_core.behaviors.reactions",
        }

    async def init(self) -> None:
        # Initialize hardware
        try:
            self.hardware.init()
            self.logger.info("Hardware initialized")
        except Exception as e:
            self.logger.warning(f"Hardware init failed on this host: {e}")
        # Build context (services like sensors/emotions/memory could be added later)
        self._ctx = BehaviorContext(
            hardware=self.hardware,
            sensors=None,
            emotions=None,
            memory=None,
            state=self.state,
            logger=self.logger,
            config=self.config,
            publish=self.bus.publish,
        )

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
        # Simple loop over configured behaviors
        for spec in (self.config.behavior_queue or []):
            beh = self._resolve_behavior(spec)
            self._active = beh
            # mypy: _ctx is initialized in init()
            assert self._ctx is not None
            await beh.start(self._ctx)
            # Run each behavior for a fixed duration for now (10s), later policy-based
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass
            await beh.stop()
        self.logger.info("Orchestration loop complete")

    async def run_single(self, spec: str, duration: float = 15.0) -> None:
        await self.init()
        beh = self._resolve_behavior(spec)
        assert self._ctx is not None
        await beh.start(self._ctx)
        try:
            await asyncio.sleep(duration)
        finally:
            await beh.stop()

    async def run_sequence(self, specs: list[str], durations: list[float] | None = None) -> None:
        await self.init()
        durations = durations or [15.0] * len(specs)
        for spec, dur in zip(specs, durations):
            beh = self._resolve_behavior(spec)
            assert self._ctx is not None
            await beh.start(self._ctx)
            try:
                await asyncio.sleep(dur)
            finally:
                await beh.stop()

    async def run_random_cycle(self, choices: list[str], min_sec: float = 20, max_sec: float = 45) -> None:
        import random
        await self.init()
        history: list[str] = []
        while True:
            pick = random.choice([c for c in choices if c not in history[-2:]] or choices)
            dur = random.randint(int(min_sec), int(max_sec))
            beh = self._resolve_behavior(pick)
            assert self._ctx is not None
            await beh.start(self._ctx)
            self.logger.info(f"Running {pick} for {dur}s")
            try:
                await asyncio.sleep(dur)
            finally:
                await beh.stop()
            history.append(pick)

async def main_async(config_path: str | None = None) -> None:
    cfg = config_path or "canine_core/config/canine_core.yaml"
    orch = Orchestrator(cfg)
    await orch.run()

def main(config_path: str | None = None) -> None:
    asyncio.run(main_async(config_path))

if __name__ == "__main__":
    main()
