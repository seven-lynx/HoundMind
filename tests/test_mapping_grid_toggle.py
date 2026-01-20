from houndmind_ai.mapping.mapper import MappingModule
from houndmind_ai.core.runtime import RuntimeContext


def test_grid_ingestion_respects_toggle():
    ctx = RuntimeContext()
    # Settings with grid disabled
    ctx.set("settings", {"mapping": {"grid_enabled": False, "cell_size_cm": 10}})
    module = MappingModule("mapping_test")
    # Provide a fake scan_latest angles dict
    ctx.set("scan_latest", {"angles": {"-30": 50.0, "0": 120.0, "30": 60.0}})
    # Initial mapping_state
    ctx.set("mapping_state", {"samples": []})
    # Tick should not populate mapping_state['grid'] when disabled
    module.tick(ctx)
    ms = ctx.get("mapping_state") or {}
    assert "grid" not in ms or not ms.get("grid"), "Grid should not be present when disabled"

    # Now enable grid and tick
    ctx.set("settings", {"mapping": {"grid_enabled": True, "cell_size_cm": 10, "grid_size": [20,20]}})
    module.tick(ctx)
    ms = ctx.get("mapping_state") or {}
    assert isinstance(ms.get("grid"), dict), "Grid should be created when enabled"
    cells = ms.get("grid", {}).get("cells", {})
    assert isinstance(cells, dict)
    assert len(cells) > 0, "At least one cell should be recorded from sample angles"
