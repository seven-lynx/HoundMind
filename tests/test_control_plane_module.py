"""The module that owns the control plane's socket, thread and shutdown (D13).

`TestServer` covers the route table; this covers the part that would ship broken — a thread that
does not come up, a port already taken, a shutdown that hangs, and a stop that leaves the port
bound. All of it on loopback.
"""

from __future__ import annotations

import socket
import urllib.request

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.services.module import ControlPlaneModule
from houndmind_ai.services.settings import ApiSettings


class DummyContext:
    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {"settings": settings or {}, "module_statuses": {}}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def __contains__(self, key):
        return key in self.data


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def context_for(tmp_path, port: int) -> DummyContext:
    # The module builds its own `ApiSettings` from `settings.api`, which is the path a real
    # runtime takes; a test that constructed the settings itself would miss a broken reader.
    return DummyContext(
        {
            "api": {
                "host": "127.0.0.1",
                "port": port,
                "token_path": str(tmp_path / "api_token"),
            }
        }
    )


def test_the_plane_starts_serves_and_releases_the_port(tmp_path) -> None:
    port = free_port()
    context = context_for(tmp_path, port)
    module = ControlPlaneModule("api", bus=CommandBus())

    module.start(context)
    try:
        # `status.started` is the runtime's flag, not the module's; what matters here is that
        # start() neither disabled the module nor raised, and that the port answers.
        assert module.status.disabled_reason is None
        assert module.status.enabled is True

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=5) as reply:
            assert reply.status == 200
            assert b'"ok"' in reply.read()
    finally:
        module.stop(context)

    # The port must be free again: a leak here means a restart leaves the dog unreachable.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_a_taken_port_disables_the_module_instead_of_raising(tmp_path) -> None:
    port = free_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    module = ControlPlaneModule("api", bus=CommandBus())
    try:
        module.start(context_for(tmp_path, port))
    finally:
        blocker.close()
        module.stop(context_for(tmp_path, port))

    assert module.status.started is False
    assert module.status.disabled_reason is not None
    assert "cannot bind" in module.status.disabled_reason


def test_no_bus_means_a_disabled_module_not_a_crash(tmp_path) -> None:
    module = ControlPlaneModule("api")
    module.start(context_for(tmp_path, free_port()))

    assert module.status.disabled_reason == "no command bus; nothing could drive the dog anyway"


def test_a_disabled_module_never_binds(tmp_path) -> None:
    port = free_port()
    module = ControlPlaneModule("api", enabled=False, bus=CommandBus())
    module.start(context_for(tmp_path, port))

    assert module.status.started is False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_the_settings_reader_honours_the_shipped_section() -> None:
    """`ApiSettings.from_settings` is the only bridge from JSON to the plane; keep it honest."""
    settings = ApiSettings.from_settings(
        {"api": {"host": "127.0.0.1", "port": 9000, "state_hz": 5.0, "max_clients": 3}}
    )

    assert settings.host == "127.0.0.1"
    assert settings.port == 9000
    assert settings.state_hz == 5.0
    assert settings.max_clients == 3


def test_a_junk_port_falls_back_to_the_default_instead_of_crashing() -> None:
    settings = ApiSettings.from_settings({"api": {"port": "soon", "host": ""}})

    assert settings.port == ApiSettings.port
    assert settings.host == ApiSettings.host