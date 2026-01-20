from houndmind_ai.optional.telemetry_dashboard import TelemetryDashboardModule
from houndmind_ai.core.runtime import RuntimeContext


def test_trace_id_present_in_snapshot():
    module = TelemetryDashboardModule("telemetry_dashboard", enabled=True)
    ctx = RuntimeContext()
    # Provide minimal settings to enable tick snapshots without HTTP server
    ctx.set("settings", {"telemetry_dashboard": {"enabled": True, "snapshot_interval_s": 0}})
    # Set a known trace id and a small performance payload
    ctx.set("trace_id", "trace-test-123")
    ctx.set("runtime_performance", {"tick_hz_target": 10})

    module.start(ctx)
    # Force a tick to build the snapshot
    module.tick(ctx)
    assert hasattr(module, "_snapshot")
    assert module._snapshot.get("trace_id") == "trace-test-123"
