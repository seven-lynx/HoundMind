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


# ---- DELETE: a forget is a mutation, and the exit criterion of P4 (canon `:444`, `:827`)


def identity_plane(
    tmp_path: Path,
    *,
    names: tuple[str, ...] = ("Alex", "Sam"),
    backend: str = "face_recognition",
) -> tuple[ControlPlane, FaceRecognitionModule]:
    """A plane whose module really is running the way `_become_ready` leaves it.

    Built from the module rather than a hand-written roster, so the route is tested against the
    writer that will publish it on the Pi — a fake roster would make the fake the thing under test.
    """
    context = DummyContext(load_config().settings)
    module = FaceRecognitionModule("face_recognition")
    module.backend = backend
    module._embeddings_path = tmp_path / "face_references.json"
    module._known_names = list(names)
    module._known_embeddings = [[0.25] * 4 for _ in names]
    module._save_embeddings()
    module._become_ready(context, backend)
    settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        pairing_enabled=False,
    )
    return ControlPlane(context, settings, CommandBus()), module


def names_on_disk(path: Path) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))["names"]


def test_forgetting_a_person_removes_them_from_disk_and_from_the_roster(tmp_path) -> None:
    """The exit criterion: gone from the file, gone from `/people`, and the answer says who."""

    async def scenario() -> None:
        plane, _ = identity_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.delete(f"{API_PREFIX}/people/alex", headers=auth(plane))
            body = await response.json()

            assert response.status == 200
            assert body["removed"] == {"id": "alex", "name": "Alex"}
            assert body["path"] == str(tmp_path / "face_references.json")
            assert names_on_disk(tmp_path / "face_references.json") == ["Sam"]

            roster = await (await client.get(f"{API_PREFIX}/people", headers=auth(plane))).json()
            assert [person["id"] for person in roster["people"]] == ["sam"]

    asyncio.run(scenario())


def test_a_second_delete_is_a_404_not_a_silent_success(tmp_path) -> None:
    """A client that retries must learn the person was already gone, or it will believe it failed."""

    async def scenario() -> None:
        plane, _ = identity_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            first = await client.delete(f"{API_PREFIX}/people/alex", headers=auth(plane))
            second = await client.delete(f"{API_PREFIX}/people/alex", headers=auth(plane))
            body = await second.json()

            assert first.status == 200
            assert second.status == 404
            assert body["error"] == "not_found"

    asyncio.run(scenario())


def test_a_paired_client_cannot_forget_anyone(tmp_path) -> None:
    """Forgetting is `admin`, and `move` is not `admin` — biometric data leaves only by the token."""

    async def scenario() -> None:
        plane, _ = identity_plane(tmp_path)
        client_token, _ = plane.authorizer.issue_client_token("Pixel 8")
        async with TestClient(TestServer(create_app(plane))) as client:
            refused = await client.delete(
                f"{API_PREFIX}/people/alex", headers={"Authorization": f"Bearer {client_token}"}
            )

            assert refused.status == 403
            assert names_on_disk(tmp_path / "face_references.json") == ["Alex", "Sam"]

    asyncio.run(scenario())


def test_forget_is_a_503_when_identity_is_not_running(tmp_path) -> None:
    """A write cannot say "removed" about a module that is not there; a read can say "nothing"."""

    async def scenario() -> None:
        plane = plane_for(
            tmp_path,
            status=module_status(
                disabled_reason="identity is disabled; enable modules.face_recognition"
            ),
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.delete(f"{API_PREFIX}/people/alex", headers=auth(plane))
            body = await response.json()

            assert response.status == 503
            assert body["error"] == "unavailable"
            assert "modules.face_recognition" in body["detail"]

    asyncio.run(scenario())


def test_a_name_that_slugs_alike_is_one_person_and_one_forget(tmp_path) -> None:
    """PL6 collapsed them into one id, so the delete has to take both or the id survives."""

    async def scenario() -> None:
        plane, module = identity_plane(tmp_path, names=("Alex Kim", "Alex  Kim", "Sam"))
        async with TestClient(TestServer(create_app(plane))) as client:
            before = await (await client.get(f"{API_PREFIX}/people", headers=auth(plane))).json()
            assert [person["id"] for person in before["people"]] == ["alex_kim", "sam"]

            response = await client.delete(f"{API_PREFIX}/people/alex_kim", headers=auth(plane))
            assert response.status == 200

            assert names_on_disk(tmp_path / "face_references.json") == ["Sam"]
            assert module._known_names == ["Sam"]
            after = await (await client.get(f"{API_PREFIX}/people", headers=auth(plane))).json()
            assert [person["id"] for person in after["people"]] == ["sam"]

    asyncio.run(scenario())


class FakeRecognizer:
    """Enough of `cv2.face.LBPHFaceRecognizer` to prove which object the module ends up holding."""

    def __init__(self) -> None:
        self.trained = False

    def train(self, faces, labels) -> None:
        self.trained = True

    def save(self, path) -> None:
        Path(path).write_text("model", encoding="utf-8")

    def read(self, path) -> None:
        return None


class FakeCv2:
    """Only what a forget reaches: a fresh recognizer factory."""

    class face:  # noqa: N801 - the attribute name cv2 itself uses
        @staticmethod
        def LBPHFaceRecognizer_create() -> FakeRecognizer:
            return FakeRecognizer()


def opencv_module(tmp_path: Path, people: tuple[str, ...] = ("Alex", "Sam")):
    """An LBPH module with images on disk, a label map, and a trained-model stand-in."""
    module = FaceRecognitionModule("face_recognition")
    module.backend = "opencv"
    module._cv2 = FakeCv2
    module._recognizer = FakeRecognizer()
    module._dataset_dir = tmp_path / "dataset"
    module._model_path = tmp_path / "face_model.yml"
    module._label_map_path = tmp_path / "face_labels.json"
    module._model_path.write_text("model", encoding="utf-8")
    module._label_map = {}
    for index, name in enumerate(people):
        person_dir = module._dataset_dir / name
        person_dir.mkdir(parents=True)
        (person_dir / "1.png").write_bytes(b"png")
        module._label_map[index] = name
    module._label_map_path.write_text(json.dumps(module._label_map), encoding="utf-8")
    return module


def test_forgetting_one_of_two_people_retrains_the_model(tmp_path) -> None:
    """The images go, the model is rebuilt from the rest, and the roster stops naming the person."""
    module = opencv_module(tmp_path)
    context = DummyContext()
    module._publish_roster(context)
    trained: list[Path] = []
    module._train_lbph_locked = lambda dataset, model, labels: trained.append(dataset)

    removed = module.forget("alex", context)

    assert removed == {"id": "alex", "name": "Alex"}
    assert not (tmp_path / "dataset" / "Alex").exists()
    assert (tmp_path / "dataset" / "Sam").exists()
    assert trained == [tmp_path / "dataset"]
    assert [person["id"] for person in published(context)["people"]] == ["sam"]


def test_forgetting_the_last_person_retires_the_trained_model(tmp_path) -> None:
    """`_train_lbph` returns early on an empty dataset; leaving the model keeps naming somebody."""
    module = opencv_module(tmp_path, people=("Alex",))
    context = DummyContext()
    module._publish_roster(context)
    old_recognizer = module._recognizer

    removed = module.forget("alex", context)

    assert removed == {"id": "alex", "name": "Alex"}
    assert not module._model_path.exists()
    assert json.loads(module._label_map_path.read_text(encoding="utf-8")) == {}
    assert module._label_map == {}
    # A fresh untrained object, not `None`: `_train_lbph_locked` refuses to train a `None`, so the
    # next enrolment would be silently anonymous for ever.
    assert module._recognizer is not old_recognizer
    assert isinstance(module._recognizer, FakeRecognizer)
    assert not module._recognizer.trained
    assert published(context)["people"] == []


def test_an_unknown_person_is_not_an_error_and_writes_nothing(tmp_path) -> None:
    """`None` is the signal the route turns into a 404; a stray write here would be a lie."""
    module = opencv_module(tmp_path, people=("Alex",))
    context = DummyContext()
    before = (tmp_path / "dataset" / "Alex" / "1.png").read_bytes()

    assert module.forget("nobody", context) is None
    assert (tmp_path / "dataset" / "Alex" / "1.png").read_bytes() == before


def test_a_configured_path_expands_home() -> None:
    """#104: `~` must not become a literal directory inside the install tree."""
    module = FaceRecognitionModule("face_recognition")

    resolved = module._resolve_path("~/.houndmind/face/face_references.json")

    assert resolved.is_absolute()
    assert resolved == Path.home() / ".houndmind" / "face" / "face_references.json"
    assert module.repo_root not in resolved.parents


def test_stopping_the_module_takes_the_forgetter_with_it() -> None:
    """A route that can still write through a stopped module is writing into nothing."""
    module = FaceRecognitionModule("face_recognition")
    module.backend = "stub"
    context = DummyContext()
    module._become_ready(context, "stub")
    assert context.get("identity_admin") is not None

    module.stop(context)

    assert context.get("identity_admin") is None
    assert context.get("identity_roster") is None
    assert module.available is False

