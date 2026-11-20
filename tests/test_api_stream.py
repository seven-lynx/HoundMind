"""The WebSocket half of the control plane: auth, telemetry, ping, and supersession.

The REST tests can pass while the stream is completely broken, so these cover the surface a phone
actually holds open: a token that is checked before anything is disclosed, `state` frames at the
configured rate, a ping that is answered, and the rule that one token drives one socket.
"""

from __future__ import annotations

import asyncio

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.behavior.routine_runner import RoutineRun
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.kernel.decisions import DecisionRecord
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
from houndmind_ai.services.settings import ApiSettings
from houndmind_ai.services.stream import LogTail


class DummyContext:
    def __init__(self) -> None:
        self.data: dict = {"settings": {}, "module_statuses": {}, "trace_id": "trace123"}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def __contains__(self, key):
        return key in self.data


def make_plane(tmp_path) -> ControlPlane:
    settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        state_hz=20.0,
    )
    return ControlPlane(DummyContext(), settings, CommandBus())


async def until(ws, kind: str, timeout: float = 5.0) -> dict:
    """Read frames until one of `kind` arrives. A missing frame fails with the type, not a hang."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        assert remaining > 0, f"no '{kind}' frame arrived in {timeout}s"
        frame = await asyncio.wait_for(ws.receive_json(), timeout=remaining)
        if frame.get("type") == kind:
            return frame


def test_a_bad_token_gets_one_error_and_no_data(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": "not-the-token"})

            frame = await until(ws, "error")

            assert frame["error"] == "unauthorized"
            assert "trace123" not in str(frame), "a rejected socket must learn nothing"

    asyncio.run(scenario())


def test_nothing_is_answered_before_hello(tmp_path) -> None:
    """An unauthenticated socket gets no frames at all: it is closed, not argued with."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "state", "data": {}})

            frame = await asyncio.wait_for(ws.receive(), timeout=5.0)

        assert frame.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED), frame.type

    asyncio.run(scenario())


def test_the_log_channel_tails_the_file_after_hello(tmp_path) -> None:
    """#170: the socket carries new lines, so the Logs panel does not have to poll for them."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        log_path = tmp_path / "houndmind.log"
        log_path.write_text('{"level": "INFO", "message": "written before connect"}\n', "utf-8")
        plane.context.set(
            "settings", {"logging": {"enable_file": True, "log_file_name": str(log_path)}}
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json(
                {"type": "hello", "token": plane.tokens.ensure(), "logs": True}
            )
            welcome = await until(ws, "welcome")
            assert welcome["data"]["logs"] is True

            # Let the pump take its first look at the file, so the offset is the current end and the
            # write below is unambiguously *new*. Without this the test would race the pump.
            await asyncio.sleep(0.2)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write('{"level": "WARNING", "message": "written after connect"}\n')

            frame = await until(ws, "log")

        assert any("written after connect" in line for line in frame["data"]["lines"])

    asyncio.run(scenario())


def test_a_token_without_admin_keeps_its_socket_and_gets_no_log_frames(tmp_path) -> None:
    """The channel is `admin`'s, like `GET /logs`; asking without it must not cost the stream."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        log_path = tmp_path / "houndmind.log"
        log_path.write_text("", "utf-8")
        plane.context.set(
            "settings", {"logging": {"enable_file": True, "log_file_name": str(log_path)}}
        )
        token, _principal = plane.authorizer.issue_client_token("Pen", scopes=["state:read"])
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": token, "logs": True})
            welcome = await until(ws, "welcome")
            assert welcome["data"]["logs"] is False

            with log_path.open("a", encoding="utf-8") as handle:
                handle.write('{"level": "ERROR", "message": "not for this token"}\n')

            # Several pump ticks with the file growing under them: state keeps arriving, log never.
            seen: list[str] = []
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 0.6
            while loop.time() < deadline:
                frame = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                seen.append(str(frame.get("type")))

        assert "state" in seen, "the socket is still a telemetry stream"
        assert "log" not in seen

    asyncio.run(scenario())


def test_log_tail_publishes_whole_lines_only(tmp_path) -> None:
    """A record is published once it is complete: no half-lines, and no re-reading the fragment."""
    path = tmp_path / "houndmind.log"
    path.write_text("first\n", "utf-8")
    context = DummyContext()
    context.set("settings", {"logging": {"enable_file": True, "log_file_name": str(path)}})
    tail = LogTail(context)

    assert tail.read_new() == [], "the first call starts at the end of the file, replaying nothing"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"level": "INFO", "message": "half')
    assert tail.read_new() == [], "a half-written record is not a line yet"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(' a line"}\n')
    assert tail.read_new() == ['{"level": "INFO", "message": "half a line"}']
    assert tail.read_new() == [], "nothing was written since"


def test_log_tail_follows_a_rotated_file(tmp_path) -> None:
    """A new file means a new offset: the old one would read from the middle of a different log."""
    path = tmp_path / "houndmind.log"
    path.write_text("old\n", "utf-8")
    context = DummyContext()
    context.set("settings", {"logging": {"enable_file": True, "log_file_name": str(path)}})
    tail = LogTail(context)
    assert tail.read_new() == []

    path.unlink()
    path.write_text("rotated\n", "utf-8")
    assert tail.read_new() == [], "a fresh file starts at its own end"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("after rotation\n")
    assert tail.read_new() == ["after rotation"]


def test_log_tail_does_not_read_a_rewritten_file_from_the_middle(tmp_path) -> None:
    """In-place rewrite, same inode: only the byte at the old offset proves it is still the same log.

    This is the case CI caught. A rotated file can be handed the inode of the one it replaced, so
    the identity check passes and the old offset lands mid-record - the tail published `"ted"`.
    """
    path = tmp_path / "houndmind.log"
    path.write_text("aaaa\n", "utf-8")
    context = DummyContext()
    context.set("settings", {"logging": {"enable_file": True, "log_file_name": str(path)}})
    tail = LogTail(context)
    assert tail.read_new() == []

    path.write_text("bbbbbbbb\n", "utf-8")  # longer than before, same inode on every filesystem
    assert tail.read_new() == [], "the old offset would have produced the fragment 'bbb'"

    with path.open("a", encoding="utf-8") as handle:
        handle.write("tail\n")
    assert tail.read_new() == ["tail"]


def test_a_good_token_gets_welcome_state_and_a_pong(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        token = plane.tokens.ensure()
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": token})

            welcome = await until(ws, "welcome")
            state = await until(ws, "state")
            await ws.send_json({"type": "ping"})
            pong = await until(ws, "pong")

        assert "state:read" in welcome["data"]["scopes"]
        assert "sensors" in state["data"], "the snapshot must be the documented one"
        assert "distance_valid" in state["data"]["sensors"]
        assert "ts" in pong

    asyncio.run(scenario())


def test_an_event_reaches_a_subscriber(tmp_path) -> None:
    """`command_vetoed` and friends are the reason a user knows why the dog refused."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        token = plane.tokens.ensure()
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": token})
            await until(ws, "state")

            plane.hub.publish_event("mode_changed", {"mode": "manual"})
            event = await until(ws, "event")

        assert event["data"]["name"] == "mode_changed"
        assert event["data"]["data"]["mode"] == "manual"

    asyncio.run(scenario())


def test_a_second_socket_with_the_same_token_evicts_the_first(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        token = plane.tokens.ensure()
        async with TestClient(TestServer(create_app(plane))) as client:
            first = await client.ws_connect(f"{API_PREFIX}/events")
            await first.send_json({"type": "hello", "token": token})
            await until(first, "welcome")

            second = await client.ws_connect(f"{API_PREFIX}/events")
            await second.send_json({"type": "hello", "token": token})

            evicted = await until(first, "error")
            await until(second, "welcome")

        assert evicted["error"] == "superseded"

    asyncio.run(scenario())


async def until_event(ws, name: str, timeout: float = 5.0) -> dict:
    """Read until the named `event` arrives, skipping state frames and other events."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        assert remaining > 0, f"no '{name}' event arrived in {timeout}s"
        frame = await asyncio.wait_for(ws.receive_json(), timeout=remaining)
        if frame.get("type") == "event" and frame.get("data", {}).get("name") == name:
            return frame


def event_names(frames: list[dict]) -> list[str]:
    return [frame["data"]["name"] for frame in frames if frame.get("type") == "event"]


class SteppingClock:
    """A clock the test moves by hand: the pump's sleep is real, a session's age is not."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


def test_a_quiet_client_loses_its_command_once(tmp_path) -> None:
    """#337: link loss is the deadman for clients, and it must not become an event storm.

    The pump finds the same silent session on every tick, so the `_quiet` bookkeeping is what
    keeps `command_expired` to one frame per client that actually went away.
    """

    async def scenario() -> None:
        clock = SteppingClock()
        settings = ApiSettings(
            host="127.0.0.1",
            port=0,
            token_path=str(tmp_path / "api_token"),
            state_hz=50.0,
            link_loss_s=2.0,
        )
        plane = ControlPlane(DummyContext(), settings, CommandBus(), clock=clock)
        published: list[tuple[str, dict]] = []
        publish = plane.hub.publish_event

        def record(name: str, data: dict | None = None) -> None:
            published.append((name, data or {}))
            publish(name, data)

        plane.hub.publish_event = record  # type: ignore[method-assign]
        # Connected, then silent: no ping for longer than `link_loss_s`.
        plane.sessions.attach("phone-token", "Phone", ["state:read"])
        await plane.hub.start()
        try:
            clock.t += 3.0
            await asyncio.sleep(0.2)
            await asyncio.sleep(0.2)  # still quiet, and still the same client
        finally:
            await plane.hub.stop()

        expired = [data for name, data in published if name == "command_expired"]
        assert len(expired) == 1, expired
        assert expired[0]["reason"] == "link_loss"
        assert expired[0]["client"], "the event names which client went quiet"

    asyncio.run(scenario())


def test_a_new_choice_is_published_as_a_decision_event(tmp_path) -> None:
    """The pump is the only producer, so the event has to come from it, not from a module."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": plane.tokens.ensure()})
            await until(ws, "welcome")

            plane.context.set(
                "decision_record",
                DecisionRecord(ts=1.0, mode="patrol", intent="forward", source="navigation"),
            )
            event = await until_event(ws, "decision")
            await ws.close()

        assert event["data"]["data"]["intent"] == "forward"
        assert event["data"]["data"]["ts"] == 1.0

    asyncio.run(scenario())


def test_a_new_reading_does_not_emit_a_second_decision_event(tmp_path) -> None:
    """A moved sensor is not a decision. Ten events a second would break the never-drop rule."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": plane.tokens.ensure()})
            await until(ws, "welcome")

            plane.context.set(
                "decision_record",
                DecisionRecord(ts=1.0, mode="patrol", intent="forward", source="navigation"),
            )
            await until_event(ws, "decision")

            # Same choice, next tick, a different reading.
            plane.context.set(
                "decision_record",
                DecisionRecord(
                    ts=2.0,
                    mode="patrol",
                    intent="forward",
                    source="navigation",
                    inputs={"distance_cm": 20.0, "distance_valid": True},
                ),
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 0.4
            frames: list[dict] = []
            while loop.time() < deadline:
                frames.append(await asyncio.wait_for(ws.receive_json(), timeout=1.0))
            await ws.close()

        assert "decision" not in event_names(frames)
        assert any(frame.get("type") == "state" for frame in frames), "the pump kept running"

    asyncio.run(scenario())

def test_a_new_step_is_published_as_a_routine_event(tmp_path) -> None:
    """The pump is the only producer, so a phone learns about a step without polling `/routines`."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": plane.tokens.ensure()})
            await until(ws, "welcome")

            plane.context.set(
                "routine_run",
                RoutineRun(routine_id="calm", name="calm", total=2, index=0, action="sit"),
            )
            event = await until_event(ws, "routine")
            await ws.close()

        assert event["data"]["data"]["id"] == "calm"
        assert event["data"]["data"]["index"] == 0
        assert event["data"]["data"]["state"] == "running"

    asyncio.run(scenario())


def test_an_unchanged_step_emits_no_second_routine_event(tmp_path) -> None:
    """The runner republishes `routine_run` every tick; the signature is what keeps it quiet."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": plane.tokens.ensure()})
            await until(ws, "welcome")

            plane.context.set(
                "routine_run",
                RoutineRun(routine_id="calm", name="calm", total=2, index=1, action="wag_tail"),
            )
            await until_event(ws, "routine")

            # Same step, next tick, republished unchanged.
            plane.context.set(
                "routine_run",
                RoutineRun(routine_id="calm", name="calm", total=2, index=1, action="wag_tail"),
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 0.4
            frames: list[dict] = []
            while loop.time() < deadline:
                frames.append(await asyncio.wait_for(ws.receive_json(), timeout=1.0))
            await ws.close()

        assert "routine" not in event_names(frames)
        assert any(frame.get("type") == "state" for frame in frames), "the pump kept running"

    asyncio.run(scenario())
