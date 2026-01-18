import pytest
from packmind.services.obstacle_service import ObstacleService
from packmind.core.context import AIContext
from packmind.core.types import BehaviorState


class ConfigStub:
    OBSTACLE_IMMEDIATE_THREAT = 25.0
    OBSTACLE_APPROACHING_THREAT = 40.0
    TURN_STEPS_NORMAL = 2
    TURN_STEPS_SMALL = 1
    TURN_STEPS_LARGE = 4
    BACKUP_STEPS = 3
    SPEED_EMERGENCY = 220
    SPEED_TURN_NORMAL = 200
    SPEED_TURN_FAST = 220
    SPEED_FAST = 200
    SPEED_NORMAL = 120
    WALK_STEPS_SHORT = 1


class FakeDog:
    def __init__(self):
        self.actions = []
        self.accData = (0, 0, 0)

    def body_stop(self):
        self.actions.append(("body_stop",))

    def do_action(self, name, step_count=1, speed=100):
        self.actions.append((name, step_count, speed))

    def wait_all_done(self):
        pass


@pytest.fixture
def ctx():
    c = AIContext()
    c.dog = FakeDog()
    c.behavior_state = BehaviorState.PATROLLING
    return c


def analyze_scan_levels(ctx):
    cfg = ConfigStub()
    svc = ObstacleService()
    assert (
        svc.analyze_scan({"forward": 20.0, "left": 50.0, "right": 50.0}, cfg)
        == "IMMEDIATE"
    )
    assert (
        svc.analyze_scan({"forward": 30.0, "left": 50.0, "right": 50.0}, cfg)
        == "APPROACHING"
    )
    assert (
        svc.analyze_scan({"forward": 100.0, "left": 50.0, "right": 50.0}, cfg) is None
    )


def maybe_avoid_executes_turn(ctx):
    cfg = ConfigStub()
    svc = ObstacleService()
    scan = {"forward": 10.0, "left": 80.0, "right": 20.0}
    svc.maybe_avoid(ctx, scan, cfg, turn_speed=150)
    # Should stop and turn left (more clearance)
    names = [a[0] for a in ctx.dog.actions]
    assert "body_stop" in names
    assert any(a[0] in ("turn_left", "turn_right") for a in ctx.dog.actions)
