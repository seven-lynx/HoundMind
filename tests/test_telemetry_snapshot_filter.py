from houndmind_ai.optional.telemetry_dashboard import TelemetryDashboardModule


def test_get_snapshot_for_trace_matches():
    module = TelemetryDashboardModule("telemetry_dashboard", enabled=True)
    module._snapshot = {"timestamp": 1.0, "trace_id": "match-1", "data": {}}
    assert module.get_snapshot_for_trace("match-1") is module._snapshot
    assert module.get_snapshot_for_trace("different") is None
