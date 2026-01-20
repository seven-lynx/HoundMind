from houndmind_ai.optional.telemetry_dashboard import TelemetryDashboardModule
import json


def test_create_support_bundle_for_trace(tmp_path, monkeypatch):
    module = TelemetryDashboardModule("telemetry_dashboard", enabled=True)
    # Ensure collector writes to a temp folder; monkeypatching is handled inside helper
    path = module.create_support_bundle_for_trace("testbundle-1")
    assert path is not None
    # open the zip file and verify metadata trace_id
    from zipfile import ZipFile

    with ZipFile(path, "r") as z:
        meta = json.loads(z.read("metadata.json").decode("utf-8"))
    assert meta.get("trace_id") == "testbundle-1"
