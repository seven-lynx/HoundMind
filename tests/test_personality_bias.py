import random
from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.behavior.registry import BehaviorRegistry


def test_personality_bias_high_curiosity():
    random.seed(0)
    module = BehaviorModule("behavior")
    registry = BehaviorRegistry()
    # register simple handlers that return their mode name
    for m in ["idle", "patrol", "explore", "interact", "play", "rest"]:
        registry.register(m, lambda m=m: m)
    module.registry = registry

    settings = {
        "autonomy_modes": ["idle", "patrol", "explore", "interact", "play", "rest"],
        # base equal weights
        "autonomy_weights": {m: 1.0 for m in ["idle", "patrol", "explore", "interact", "play", "rest"]},
        "autonomy_interval_s": 0.0,
    }

    # High curiosity should bias toward "explore"
    context = {
        "settings": {"personality": {"curiosity": 10.0, "sociability": 0.1, "activity": 0.1, "apply_to_autonomy": True}}
    }

    explore_count = 0
    trials = 200
    for _ in range(trials):
        # force fresh selection by clearing last mode/timestamp
        module._autonomy_mode = None
        module._last_autonomy_ts = 0
        mode = module._select_autonomy_mode(settings, context)
        if mode == "explore":
            explore_count += 1

    assert explore_count > (trials * 0.7), f"explore_count={explore_count} not sufficiently dominant"
