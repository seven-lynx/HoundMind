from __future__ import annotations
from typing import Callable, Dict, List, Any


class HookRegistry:
    """Lightweight registry that attaches handlers to EventBus events.

    Usage:
      hooks.register('battery_low', handler)
      hooks.register_many({'battery_critical': on_crit, 'safety_emergency_tilt': on_tilt})
    """

    def __init__(self, publish: Callable[[str, dict], None], subscribe: Callable[[str, Callable[[dict], None]], None]):
        self._publish = publish
        self._subscribe = subscribe
        self._handlers: Dict[str, List[Callable[[dict], None]]] = {}

    def register(self, event_type: str, handler: Callable[[dict], None]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)
        self._subscribe(event_type, handler)

    def register_many(self, mapping: Dict[str, Callable[[dict], None]]) -> None:
        for et, h in mapping.items():
            self.register(et, h)


def default_hooks_factory(ctx) -> Dict[str, Callable[[dict], None]]:
    """Create default handlers bound to a BehaviorContext-like object.

    Expects fields: emotions, motion, logger, config
    """
    log = ctx.logger
    emo = getattr(ctx, 'emotions', None)
    motion = getattr(ctx, 'motion', None)

    def on_battery_low(data: dict) -> None:
        pct = data.get('pct')
        try:
            log.warning(f"battery_low: {pct}%")
            if emo:
                emo.update((255, 165, 0))  # orange
            # Apply optional speed reduction factor via MotionService, if configured
            try:
                factor = float(getattr(ctx.config, 'LOW_BATTERY_REDUCE_SPEED_FACTOR', 1.0))
            except Exception:
                factor = 1.0
            if motion and factor and factor > 0.0:
                try:
                    getter = getattr(motion, 'get_speed_scale', None)
                    setter = getattr(motion, 'set_speed_scale', None)
                    if callable(getter) and callable(setter):
                        val = getter()
                        if isinstance(val, (int, float)):
                            current = float(val)
                        else:
                            current = 1.0
                        # choose the minimum of current and configured factor to avoid raising speed
                        new_scale = min(current, factor)
                        setter(new_scale)
                        log.info(f"Applied low-battery speed scale: {new_scale:.2f}")
                except Exception:
                    pass
        except Exception:
            pass

    def on_battery_critical(data: dict) -> None:
        pct = data.get('pct')
        try:
            log.error(f"battery_critical: {pct}% — critical battery")
            if emo:
                emo.update((255, 0, 0))  # red
            # Honor config flag for rest behavior on critical battery
            rest_ok = bool(getattr(ctx.config, 'CRITICAL_BATTERY_REST_BEHAVIOR', True))
            if rest_ok and motion:
                motion.act('lie', speed=getattr(ctx.config, 'SPEED_SLOW', 60))
                motion.wait()
        except Exception:
            pass

    def on_safety_tilt(data: dict) -> None:
        try:
            log.error("safety_emergency_tilt: triggering safe pose")
            if emo:
                emo.update((255, 0, 0))
            if motion:
                motion.act(getattr(ctx.config, 'EMERGENCY_STOP_POSE', 'crouch'), speed=getattr(ctx.config, 'SPEED_SLOW', 60))
                motion.wait()
        except Exception:
            pass

    return {
        'battery_low': on_battery_low,
        'battery_critical': on_battery_critical,
        'safety_emergency_tilt': on_safety_tilt,
    }
