"""The command path, end to end: HTTP → bus → gateway → interlock → HAL.

Every test here asserts something a user would notice if it broke: a forward reaches the servos,
an obstacle stops it with a reason, an expired command never runs, and two identical actions from
two sources are two commands (which the string-dedupe this replaced could not tell apart).
"""

from __future__ import annotations

import asyncio
import time

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.act.gateway import MotionGatewayModule
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.module import HalModule
from houndmind_ai.hal.motors import MotorModule
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.kernel.commands import Command, CommandBus, Source
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
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


class World:
    """A fake dog wired the way the runtime wires it, without the runtime."""

    def __init__(
        self,
        tmp_path,
        distance: float = 200.0,
        context_settings: dict | None = None,
    ) -> None:
        self.context = DummyContext(context_settings)
        self.hal = FakeDogHAL()
        self.hal.set_distance(distance)
        self.bus = CommandBus()
        HalModule("hal", hal=self.hal).start(self.context)
        # Publish a reading the way SensorModule does, so the gateway has a real snapshot.
        self.context.set("sensor_reading", SensorReading.from_snapshot(self.hal.read()))
        self.motors = MotorModule("hal_motors")
        self.motors.start(self.context)
        self.gateway = MotionGatewayModule("motion_gateway", bus=self.bus)
        # `start` is what publishes the intent board and hands the interlock the classification
        # from `settings.behavior.action_classes`; the runtime does it, so the test does too.
        self.gateway.start(self.context)
        settings = ApiSettings(
            host="127.0.0.1",
            port=0,
            token_path=str(tmp_path / "api_token"),
            command_ack_timeout_s=0.5,
        )
        self.plane = ControlPlane(self.context, settings, self.bus)

    @property
    def token(self) -> str:
        return self.plane.tokens.ensure()

    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def step(self) -> None:
        self.gateway.tick(self.context)
        self.motors.tick(self.context)

    async def tick_until(self, done) -> None:
        """Run the decision loop while an HTTP request waits on the verdict."""
        for _ in range(400):
            self.step()
            if done():
                return
            await asyncio.sleep(0.005)


def test_a_client_forward_reaches_the_hal(tmp_path) -> None:
    async def scenario() -> None:
        world = World(tmp_path)
        async with TestClient(TestServer(create_app(world.plane))) as client:
            request = asyncio.create_task(
                client.post(
                    f"{API_PREFIX}/command",
                    headers=world.auth(),
                    json={"id": "c1", "action": "forward", "ttl_ms": 300},
                )
            )
            await world.tick_until(request.done)
            response = await request
            body = await response.json()

        assert response.status == 202, body
        assert body["accepted"] is True
        assert ("forward", {}) in world.hal.calls, world.hal.calls
        assert world.plane.audit.recent(1)[0]["action"] == "forward"

    asyncio.run(scenario())


def test_an_obstacle_returns_409_with_a_reason_and_no_step(tmp_path) -> None:
    async def scenario() -> None:
        world = World(tmp_path, distance=5.0)
        async with TestClient(TestServer(create_app(world.plane))) as client:
            request = asyncio.create_task(
                client.post(
                    f"{API_PREFIX}/command",
                    headers=world.auth(),
                    json={"id": "c2", "action": "forward", "ttl_ms": 300},
                )
            )
            await world.tick_until(request.done)
            response = await request
            body = await response.json()

        assert response.status == 409, body
        assert body["accepted"] is False
        assert body["veto"] == "obstacle"
        assert body["detail"], "a veto without a reason is a bug"
        assert ("forward", {}) not in world.hal.calls

    asyncio.run(scenario())


def test_an_expired_command_never_reaches_the_hal(tmp_path) -> None:
    """The deadman is enforced by the interlock, not by the client's good behaviour."""
    world = World(tmp_path)
    stale = Command(
        action="forward",
        source=Source.CLIENT,
        issued_at=time.monotonic() - 5.0,
        ttl_ms=300,
    )
    assert world.bus.submit(stale) is True

    world.step()

    verdict = world.bus.wait(stale.id, timeout=0.1)
    assert verdict is not None
    assert verdict.accepted is False
    assert verdict.veto == "expired"
    assert ("forward", {}) not in world.hal.calls


def test_rest_mode_vetoes_client_motion_but_not_system_stop(tmp_path) -> None:
    async def scenario() -> None:
        world = World(tmp_path)
        world.plane.set_mode("rest")
        async with TestClient(TestServer(create_app(world.plane))) as client:
            request = asyncio.create_task(
                client.post(
                    f"{API_PREFIX}/command",
                    headers=world.auth(),
                    json={"id": "c3", "action": "forward"},
                )
            )
            await world.tick_until(request.done)
            response = await request
            body = await response.json()

            stopped = await client.post(f"{API_PREFIX}/stop", headers=world.auth())

        assert response.status == 409, body
        assert body["veto"] == "mode"
        assert stopped.status == 202, "the escape hatch can never be vetoed"

    asyncio.run(scenario())


def test_two_identical_actions_from_two_ids_are_two_commands(tmp_path) -> None:
    """H-10: the old gateway deduplicated on the action string and dropped the second."""
    world = World(tmp_path)
    now = time.monotonic()
    first = Command(action="forward", source=Source.CLIENT, issued_at=now)
    second = Command(action="forward", source=Source.NAVIGATION, issued_at=now)
    assert world.bus.submit(first) is True
    assert world.bus.submit(second) is True

    world.step()

    assert world.bus.wait(first.id, timeout=0.1) is not None
    assert world.bus.wait(second.id, timeout=0.1) is not None


def test_an_unknown_action_is_a_400_with_a_suggestion(tmp_path) -> None:
    async def scenario() -> None:
        world = World(tmp_path)
        async with TestClient(TestServer(create_app(world.plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/command",
                headers=world.auth(),
                json={"action": "forwrd"},
            )
            body = await response.json()

        assert response.status == 400
        assert body["error"] == "unknown_action"
        assert body["suggestion"] == "forward"

    asyncio.run(scenario())


# The classification as the runtime loads it: `actions.jsonc` -> settings.behavior.action_classes.
_CLASSES = {
    "behavior": {
        "action_classes": {
            "high five": {"class": "posture"},
            "sound": {"class": "non_motion", "params": ["name", "volume"]},
        }
    }
}


def test_a_classified_catalog_action_reaches_the_hal(tmp_path) -> None:
    """`high five` is data, not code: classifying it in the config is enough to command it."""

    async def scenario() -> None:
        world = World(tmp_path, context_settings=_CLASSES)
        async with TestClient(TestServer(create_app(world.plane))) as client:
            request = asyncio.create_task(
                client.post(
                    f"{API_PREFIX}/command",
                    headers=world.auth(),
                    json={"id": "c5", "action": "high five", "ttl_ms": 300},
                )
            )
            await world.tick_until(request.done)
            response = await request
            body = await response.json()

        assert response.status == 202, body
        assert body["action"] == "high_five"
        assert ("high_five", {}) in world.hal.calls, world.hal.calls

    asyncio.run(scenario())


def test_a_sound_command_carries_its_params_to_the_hal(tmp_path) -> None:
    """A `202` that plays nothing is worse than a refusal: the params are the whole command."""

    async def scenario() -> None:
        world = World(tmp_path, context_settings=_CLASSES)
        async with TestClient(TestServer(create_app(world.plane))) as client:
            request = asyncio.create_task(
                client.post(
                    f"{API_PREFIX}/command",
                    headers=world.auth(),
                    json={
                        "id": "c6",
                        "action": "sound",
                        "params": {"name": "angry", "volume": 80},
                        "ttl_ms": 300,
                    },
                )
            )
            await world.tick_until(request.done)
            response = await request
            body = await response.json()

        assert response.status == 202, body
        assert body["accepted"] is True
        assert ("sound", {"name": "angry", "volume": 80}) in world.hal.calls, world.hal.calls

    asyncio.run(scenario())


def test_the_repertoire_reports_every_action_the_device_can_run(tmp_path) -> None:
    """The menu is the device's, not the app's: class from the config, names from the HAL."""

    async def scenario() -> None:
        world = World(tmp_path, context_settings=_CLASSES)
        async with TestClient(TestServer(create_app(world.plane))) as client:
            response = await client.get(f"{API_PREFIX}/repertoire", headers=world.auth())
            body = await response.json()

        assert response.status == 200
        by_name = {entry["name"]: entry for entry in body["actions"]}
        assert body["count"] == len(body["actions"])
        # From the classification that was loaded (canonical spelling)...
        assert by_name["high_five"]["class"] == "posture"
        # ...and from the HAL's own list, which is the only thing that knows what it implements.
        assert by_name["forward"]["class"] == "locomotion"
        assert by_name["rgb"]["class"] == "non_motion"
        assert by_name["sound"]["params"] == ["name", "volume"]

    asyncio.run(scenario())


def test_a_command_without_a_live_decision_loop_is_503(tmp_path) -> None:
    """No ticker means no verdict: the route says so instead of pretending it was accepted."""
    async def scenario() -> None:
        world = World(tmp_path)
        async with TestClient(TestServer(create_app(world.plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/command",
                headers=world.auth(),
                json={"action": "forward"},
            )
            body = await response.json()

        assert response.status == 503
        assert body["error"] == "unavailable"

    asyncio.run(scenario())