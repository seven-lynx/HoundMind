import os
import json
from zipfile import ZipFile

from tools.collect_support_bundle import main as collect_main


def test_collect_support_bundle_includes_env_trace(tmp_path, monkeypatch):
    out = tmp_path / "support.zip"
    monkeypatch.setenv("HOUNDMIND_TRACE_ID", "env-trace-abc")
    res = collect_main([str(out)])
    assert res == 0
    assert out.exists()
    with ZipFile(out, "r") as z:
        meta = json.loads(z.read("metadata.json").decode("utf-8"))
    assert meta.get("trace_id") == "env-trace-abc"
