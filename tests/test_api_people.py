"""`GET /api/v1/people`: who the dog has been taught, and why it cannot say.

`tests/test_api_routes.py` proves the route is declared, scoped and refuses anonymous callers.
This file covers the two answers that matter: a roster of ids and names with nothing biometric in
it, and an explicit *reason* when there is no roster — because identity ships `enabled: false` and
`people: []` would otherwise read as "nobody is enrolled".

The module half is tested against `FaceRecognitionModule` directly: `_publish_roster` is the only
writer of the context key the route reads, so it is where a stale roster would come from.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.optional.face_recognition import FaceRecognitionModule
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
from houndmind_ai.services.auth import Principal
from houndmind_ai.services.settings import ApiSettings


class DummyContext:
    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {"settings": settings or {}}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


def module_status(**overrides) -> dict:
    """The shape `build_modules` reads: enabled/started/disabled_reason/last_error."""
    status = {"enabled": False, "required": False, "started": False, "disabled_reason": None}
    status.update(overrides)
    return status


def plane_for(
    tmp_path: Path,
    *,
    roster: dict | None = None,
    status: dict | None = None,
) -> ControlPlane:
    context = DummyContext(load_config().settings)
    if status is not None:
        context.set("module_statuses", {"face_recognition": status})
    if roster is not None:
        context.set("identity_roster", roster)
    settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        pairing_enabled=False,
    )
    return ControlPlane(context, settings, CommandBus())


def auth(plane: ControlPlane) -> dict[str, str]:
    return {"Authorization": f"Bearer {plane.tokens.ensure()}"}


def roster_of(**kwargs) -> dict:
    """What `_publish_roster` publishes, in the shape the route reads."""
    body = {"backend": "face_recognition", "path": "/tmp/face_embeddings.json", "people": []}
    body.update(kwargs)
    return body


def test_identity_off_is_a_200_that_says_so(tmp_path) -> None:
    """Disabled is the shipped default, so it cannot be an error status on a screen."""

    async def scenario() -> None:
        plane = plane_for(
            tmp_path,
            status=module_status(
                disabled_reason="identity is disabled; enable modules.face_recognition"
            ),
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/people", headers=auth(plane))
            body = await response.json()

            assert response.status == 200
            assert body["identity"]["enabled"] is False
            assert "modules.face_recognition" in body["identity"]["reason"]
            assert body["people"] == []
            assert body["path"] is None

    asyncio.run(scenario())


def test_identity_off_repeats_the_modules_own_reason(tmp_path) -> None:
    """A missing dlib and a switched-off module are different problems; the module knows which."""

    async def scenario() -> None:
        plane = plane_for(
            tmp_path,
            status=module_status(disabled_reason="missing dependency: face_recognition (dlib)"),
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            body = await (await client.get(f"{API_PREFIX}/people", headers=auth(plane))).json()

            assert body["identity"]["reason"] == "missing dependency: face_recognition (dlib)"

    asyncio.run(scenario())


def test_every_way_of_having_no_roster_names_itself(tmp_path) -> None:
    """Three different absences, three different sentences — never one shrug for all of them."""

    async def scenario() -> None:
        for status, expected in (
            (None, "not registered"),
            (module_status(enabled=True, started=True), "published no roster"),
            (module_status(enabled=True, started=True, last_error="cv2 exploded"), "cv2 exploded"),
        ):
            plane = plane_for(tmp_path, status=status)
            async with TestClient(TestServer(create_app(plane))) as client:
                body = await (await client.get(
                    f"{API_PREFIX}/people", headers=auth(plane)
                )).json()
            assert expected in body["identity"]["reason"], (status, body)

    asyncio.run(scenario())


def test_the_roster_is_ids_and_names_and_nothing_biometric(tmp_path) -> None:
    """The criterion, as a string search: an embedding must not be able to sneak into the body."""

    async def scenario() -> None:
        people = [{"id": "alex", "name": "Alex"}, {"id": "sam", "name": "Sam"}]
        plane = plane_for(
            tmp_path,
            roster=roster_of(
                path=str(tmp_path / "face_references.json"),
                people=people,
            ),
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/people", headers=auth(plane))
            body = await response.json()

            assert response.status == 200
            assert body["identity"] == {
                "enabled": True,
                "backend": "face_recognition",
                "reason": None,
            }
            assert body["path"] == str(tmp_path / "face_references.json")
            assert body["people"] == people
            assert set(body["people"][0]) == {"id", "name"}
            # Scoped to the people entries on purpose: `path` legitimately names the file the
            # embeddings live in, which is not the same as leaking one.
            entries = json.dumps(body["people"])
            assert "embedding" not in entries
            assert "0.0" not in entries  # no vector under another key either

    asyncio.run(scenario())


def test_a_paired_client_cannot_enumerate_the_roster(tmp_path) -> None:
    """`admin`, per the canon: who lives here is not a phone's business, even a paired one."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, roster=roster_of(people=[{"id": "alex", "name": "Alex"}]))
        client_token, principal = plane.authorizer.issue_client_token("Pixel 8")
        assert isinstance(principal, Principal) and not principal.may("admin")

        async with TestClient(TestServer(create_app(plane))) as client:
            refused = await client.get(
                f"{API_PREFIX}/people", headers={"Authorization": f"Bearer {client_token}"}
            )
            assert refused.status == 403

            # And the same roster is readable with the device token, or the refusal would be
            # indistinguishable from a broken route.
            allowed = await client.get(f"{API_PREFIX}/people", headers=auth(plane))
            assert allowed.status == 200

    asyncio.run(scenario())


def test_meta_does_not_advertise_that_people_are_enrolled(tmp_path) -> None:
    """`/meta` is unauthenticated. Announcing the roster there would undo the `admin` scope."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, roster=roster_of(people=[{"id": "alex", "name": "Alex"}]))
        async with TestClient(TestServer(create_app(plane))) as client:
            meta = await (await client.get(f"{API_PREFIX}/meta")).json()

            assert "people" not in meta["capabilities"]
            assert "alex" not in json.dumps(meta)

    asyncio.run(scenario())


# ---- the module half: `_publish_roster` is the only writer of the key the route reads


def published(context: DummyContext) -> dict:
    return context.get("identity_roster")


def test_the_roster_slugs_names_and_collapses_repeats(tmp_path) -> None:
    """Two reference faces under one name are one person — which is how the detector sees them."""

    module = FaceRecognitionModule("face_recognition")
    module.backend = "face_recognition"
    module._known_names = ["Alex Kim", "Alex Kim", "Sam"]
    module._embeddings_path = tmp_path / "face_references.json"
    context = DummyContext()

    module._publish_roster(context)

    assert published(context) == {
        "backend": "face_recognition",
        "path": str(tmp_path / "face_references.json"),
        # `slug` is the rule `Place.id` follows: lowercase, `_`-joined (`kernel/place.py:109`).
        "people": [{"id": "alex_kim", "name": "Alex Kim"}, {"id": "sam", "name": "Sam"}],
    }


def test_the_roster_follows_whichever_backend_holds_the_names(tmp_path) -> None:
    """LBPH identifies out of its label map; the Haar cascade alone never names anybody."""

    module = FaceRecognitionModule("face_recognition")
    module.backend = "opencv"
    module._label_map = {0: "Alex", 1: "Sam"}
    module._label_map_path = tmp_path / "face_labels.json"
    context = DummyContext()

    module._publish_roster(context)

    roster = published(context)
    assert roster["backend"] == "opencv"
    assert roster["path"] == str(tmp_path / "face_labels.json")
    assert [person["id"] for person in roster["people"]] == ["alex", "sam"]


def test_a_backend_that_names_nobody_publishes_an_empty_roster() -> None:
    """`stub` is a running module, so it answers — with a backend a client can recognise."""

    module = FaceRecognitionModule("face_recognition")
    module.backend = "stub"
    context = DummyContext()

    module._publish_roster(context)

    assert published(context) == {"backend": "stub", "path": None, "people": []}


def test_a_name_with_no_usable_characters_is_not_a_person(tmp_path) -> None:
    """`slug` can come back empty; an empty id would be a hole in `DELETE /people/{id}`."""

    module = FaceRecognitionModule("face_recognition")
    module.backend = "face_recognition"
    module._known_names = ["///", "   ", "Alex"]
    context = DummyContext()

    module._publish_roster(context)

    assert [person["id"] for person in published(context)["people"]] == ["alex"]

