"""`/meta` reports the board — a contract field that had nothing behind it.

`docs/CONTROL_API.md` promised `device_id` and `board` from the day the control plane shipped,
while nothing detected a board and no schema accepted `settings.device.device_id`, so both were
permanently `null`. The last test here is the one that keeps the row and the payload equal.
"""

from __future__ import annotations

import re
from pathlib import Path

from houndmind_ai.core.config import Config, load_config
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.main import publish_identity
from houndmind_ai.services.api import ControlPlane
from houndmind_ai.services.settings import ApiSettings

DOC = Path(__file__).resolve().parents[1] / "docs" / "CONTROL_API.md"


class DummyContext:
    def __init__(self) -> None:
        self.data: dict = {"settings": {}, "module_statuses": {}, "trace_id": "trace123"}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def __contains__(self, key):
        return key in self.data


def make_plane(context: DummyContext, tmp_path) -> ControlPlane:
    settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        pairing_enabled=False,
    )
    return ControlPlane(context, settings, CommandBus())


def test_meta_reports_the_detected_board_and_the_applied_profile(tmp_path) -> None:
    context = DummyContext()
    context.set("device_id", "houndmind-dev")
    context.set("board", "pi5")
    context.set("profile", "pi5")

    meta = make_plane(context, tmp_path).meta()

    assert meta["board"] == "pi5"
    assert meta["profile"] == "pi5"
    assert meta["device_id"] == "houndmind-dev"


def test_the_boot_time_device_id_wins_over_the_config_default(tmp_path) -> None:
    """`main` sets `device_id` from the config or the hostname; `/meta` must show what is in use."""
    context = DummyContext()
    context.data["settings"] = {"device": {"device_id": ""}}
    context.set("device_id", "from-hostname")

    meta = make_plane(context, tmp_path).meta()

    assert meta["device_id"] == "from-hostname"


def test_publish_identity_reports_a_fact_and_a_decision() -> None:
    config = load_config()
    context = DummyContext()

    board = publish_identity(context, config)

    assert context.get("board") == board.kind
    assert context.get("board_model") == board.model
    assert context.get("profile") == config.profile


def test_the_profile_is_published_even_when_it_is_forced() -> None:
    """An operator override changes the decision, not what the device tree says."""
    context = DummyContext()
    forced = Config.from_dict({"loop": {"tick_hz": 5}}, profile="pi4")

    board = publish_identity(context, forced)

    assert context.get("profile") == "pi4"
    assert context.get("board") == board.kind


def test_the_contract_row_lists_exactly_the_fields_meta_returns(tmp_path) -> None:
    """A field added here without a contract row is invisible to both clients."""
    documented = None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("| `GET` | `/api/v1/meta`"):
            documented = set(re.findall(r"`([a-z_]+)`", line))
            break
    assert documented, "no /meta row in docs/CONTROL_API.md"

    assert documented == set(make_plane(DummyContext(), tmp_path).meta())