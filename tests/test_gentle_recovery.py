import time
import pytest
from houndmind_ai.navigation.obstacle_avoidance import ObstacleAvoidanceModule

class DummyContext(dict):
    def set(self, key, value):
        self[key] = value
    def get(self, key, default=None):
        return super().get(key, default)

def make_settings(stuck_count=3, cooldown=8.0, speed=80):
    return {
        "navigation": {
            "gentle_recovery_stuck_count": stuck_count,
            "gentle_recovery_cooldown_s": cooldown,
        },
        "movement": {
            "gentle_recovery_speed": speed,
        },
    }

def test_gentle_recovery_triggers_and_clears(monkeypatch):
    # Patch _scan_open_space to always return a valid scan result (direction, score, confirmed)
    module = ObstacleAvoidanceModule("test")
    monkeypatch.setattr(module, "_scan_open_space", lambda ctx, s, n: ("forward", 1.0, True))
    context = DummyContext()
    context["settings"] = make_settings()
    # Patch _check_stuck to always return True
    monkeypatch.setattr(module, "_check_stuck", lambda ctx, s, n: True)
    # Patch _apply_avoidance_strategy to do nothing
    monkeypatch.setattr(module, "_apply_avoidance_strategy", lambda ctx, s, a: None)
    monkeypatch.setattr(module, "_record_avoidance", lambda n: None)
    # Simulate repeated stuck events (gentle recovery triggers when threshold is reached)
    # Tick up to threshold, should remain inactive
    # First tick: should remain inactive
    module.tick(context)
    print(f"Tick 0: context={dict(context)}, _gentle_recovery_active={module._gentle_recovery_active}")
    assert context.get("gentle_recovery_active") is False
    # Gentle recovery should activate after the first tick
    module.tick(context)
    print(f"Tick 1: context={dict(context)}, _gentle_recovery_active={module._gentle_recovery_active}")
    assert context.get("gentle_recovery_active") is True
    assert module._gentle_recovery_active is True
    assert context.get("energy_speed_hint") == "slow"
    # Remain active for subsequent ticks
    module.tick(context)
    print(f"Tick 2: context={dict(context)}, _gentle_recovery_active={module._gentle_recovery_active}")
    assert context.get("gentle_recovery_active") is True
    # Simulate cooldown expiry
    now = time.time()
    module._gentle_recovery_until = now - 1
    module.tick(context)
    assert context.get("gentle_recovery_active") is False
    assert module._gentle_recovery_active is False
    assert context.get("energy_speed_hint") is None
