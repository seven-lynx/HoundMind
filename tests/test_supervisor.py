"""The supervisor: who gets restarted, who gets given up on, and what is never a failure.

H-03 was not one bug. It was two modules watching the same heartbeats and a candidate list that
included modules which never heartbeat at all, so the stale set was never empty on a shipped
config. These tests pin the rules that replaced that.
"""

from __future__ import annotations

from houndmind_ai.kernel.supervisor import RestartPolicy, Supervisor


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def status(**overrides):
    base = {
        "enabled": True,
        "required": False,
        "started": True,
        "disabled_reason": None,
        "last_tick_ts": 999.0,
        "last_tick_duration_s": 0.001,
        "last_heartbeat_ts": 1000.0,
        "last_error": None,
    }
    base.update(overrides)
    return base


def build(**policy):
    clock = Clock()
    supervisor = Supervisor(RestartPolicy(**policy), clock=clock)
    return supervisor, clock


def test_backoff_is_exponential_and_capped() -> None:
    policy = RestartPolicy(base_delay_s=1.0, factor=2.0, max_delay_s=5.0)
    assert [policy.delay_for(attempt) for attempt in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 5.0]
    assert policy.delay_for(0) == 0.0


def test_a_healthy_module_is_left_alone() -> None:
    supervisor, _ = build()
    report = supervisor.decide({"scanning": status()}, timeout_s=4.0)
    assert report.restart == []
    assert report.failed == []


def test_a_stale_heartbeat_earns_one_restart() -> None:
    supervisor, clock = build()
    statuses = {"scanning": status(last_heartbeat_ts=clock.now)}
    clock.advance(10.0)
    report = supervisor.decide(statuses, timeout_s=4.0)
    assert report.restart == ["scanning"]
    assert report.reasons["scanning"] == "stale heartbeat"


def test_a_disabled_module_is_never_a_candidate() -> None:
    """This is H-03's second cause: disabled modules never heartbeat, so they were always stale."""
    supervisor, _ = build()
    report = supervisor.decide(
        {"safety": status(enabled=False, started=False, last_heartbeat_ts=None)},
        timeout_s=4.0,
    )
    assert report.restart == []
    assert report.failed == []


def test_a_module_that_disabled_itself_is_never_a_candidate() -> None:
    supervisor, _ = build()
    report = supervisor.decide(
        {"vision_pi4": status(started=False, disabled_reason="no camera")},
        timeout_s=4.0,
    )
    assert report.restart == []
    assert report.failed == []


def test_restarts_back_off_before_trying_again() -> None:
    supervisor, clock = build(base_delay_s=2.0, factor=2.0)
    statuses = {"scanning": status(last_heartbeat_ts=clock.now)}
    clock.advance(10.0)

    assert supervisor.decide(statuses, timeout_s=4.0).restart == ["scanning"]
    # Still stale, but the 2 s backoff has not elapsed.
    clock.advance(0.5)
    report = supervisor.decide(statuses, timeout_s=4.0)
    assert report.restart == []
    assert "backing off" in report.reasons["scanning"]

    clock.advance(2.0)
    assert supervisor.decide(statuses, timeout_s=4.0).restart == ["scanning"]


def test_a_module_is_eventually_left_failed() -> None:
    """A supervisor that retries forever hides the fault it exists to report."""
    supervisor, clock = build(max_restarts=2, base_delay_s=0.0)
    statuses = {"scanning": status(last_heartbeat_ts=clock.now)}
    clock.advance(10.0)

    assert supervisor.decide(statuses, timeout_s=4.0).restart == ["scanning"]
    assert supervisor.decide(statuses, timeout_s=4.0).restart == ["scanning"]

    report = supervisor.decide(statuses, timeout_s=4.0)
    assert report.restart == []
    assert report.failed == ["scanning"]
    assert "gave up" in report.reasons["scanning"]

    # And it stays failed until something resets it.
    clock.advance(3600.0)
    assert supervisor.decide(statuses, timeout_s=4.0).restart == []


def test_a_module_that_stays_up_earns_a_fresh_budget() -> None:
    supervisor, clock = build(max_restarts=1, base_delay_s=0.0, healthy_after_s=5.0)
    broken = {"scanning": status(last_heartbeat_ts=clock.now)}
    clock.advance(10.0)

    assert supervisor.decide(broken, timeout_s=4.0).restart == ["scanning"]
    assert supervisor.decide(broken, timeout_s=4.0).failed == ["scanning"]

    # It comes back and stays healthy for longer than `healthy_after_s`.
    for _ in range(6):
        clock.advance(1.0)
        supervisor.decide(
            {"scanning": status(last_heartbeat_ts=clock.now)}, timeout_s=4.0
        )

    report = supervisor.decide(
        {"scanning": status(last_heartbeat_ts=clock.now - 100.0)}, timeout_s=4.0
    )
    assert report.restart == ["scanning"], "the fresh budget should allow one more attempt"


def test_a_new_error_is_the_trigger_not_the_presence_of_one() -> None:
    """`ModuleStatus.last_error` is never cleared, so presence alone would restart forever."""
    supervisor, clock = build(base_delay_s=0.0, max_restarts=3)
    statuses = {"scanning": status(last_error="boom")}

    assert supervisor.decide(statuses, timeout_s=4.0).restart == ["scanning"]
    # The same error is still recorded; it must not be treated as a new one.
    assert supervisor.decide(statuses, timeout_s=4.0).restart == []
    # A different one is news.
    assert supervisor.decide({"scanning": status(last_error="bang")}, timeout_s=4.0).restart == [
        "scanning"
    ]


def test_the_monitor_allow_list_limits_the_candidates() -> None:
    supervisor, clock = build()
    statuses = {
        "scanning": status(last_heartbeat_ts=clock.now - 100.0),
        "event_log": status(last_heartbeat_ts=clock.now - 100.0),
    }
    report = supervisor.decide(statuses, timeout_s=4.0, monitor=["scanning"])
    assert report.restart == ["scanning"]


def test_reset_forgets_history() -> None:
    supervisor, clock = build(max_restarts=1, base_delay_s=0.0)
    statuses = {"scanning": status(last_heartbeat_ts=clock.now)}
    clock.advance(10.0)
    supervisor.decide(statuses, timeout_s=4.0)
    assert supervisor.decide(statuses, timeout_s=4.0).failed == ["scanning"]

    supervisor.reset()
    assert supervisor.watched == ()
    assert supervisor.decide(statuses, timeout_s=4.0).restart == ["scanning"]