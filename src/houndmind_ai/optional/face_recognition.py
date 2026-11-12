from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.place import slug

logger = logging.getLogger(__name__)


class IdentityForgetter:
    """The one thing `DELETE /api/v1/people/{id}` is allowed to do (P4 PL7).

    Published under `identity_admin` while the module runs, and nothing else — a route that could
    reach `FaceRecognitionModule` itself could reach `_recognizer` and `_known_embeddings`, and a
    forget would then be one of many things a caller might do to biometric data. One method is the
    whole contract.
    """

    def __init__(self, module: FaceRecognitionModule, context: Any) -> None:
        self._module = module
        self._context = context

    def forget(self, person_id: str) -> dict[str, str] | None:
        """Remove every reference face filed under `person_id`; `None` if nobody matches."""
        return self._module.forget(person_id, self._context)


class FaceRecognitionModule(Module):
    """Pi4-focused face recognition module (backend-pluggable).

    Lite backend: OpenCV Haar detector with optional LBPH recognition.
    Heavy backend: face_recognition (dlib-based) with embeddings.

    Enrollment is driven from the runtime, not from an HTTP endpoint: publish
    `{"action": "enroll", "name": "Alice"}` under `face_recognition_command` and the next
    tick runs it against the newest `vision_frame`. The legacy port-8088 server (`/status`,
    `/faces`, `/enroll`) is gone; `/status` is now `GET /api/v1/modules` and the roster of
    enrolled people is `GET /api/v1/people`, published here under `identity_roster`.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.backend: str = "stub"
        self.available = False
        self.repo_root = Path(__file__).resolve().parents[3]

        self._cv2: Any | None = None
        self._cascade: Any | None = None
        self._recognizer: Any | None = None
        self._label_map: dict[int, str] = {}
        # Where those names came from, for `GET /api/v1/people` to report. The two backends keep
        # their identities in different files; only one of them is ever in use at a time.
        self._label_map_path: Path | None = None
        # LBPH needs all three to forget somebody: the images to delete, the model to retrain, and
        # the map it is retrained into (P4 PL7).
        self._dataset_dir: Path | None = None
        self._model_path: Path | None = None

        self._embeddings_path: Path | None = None
        self._known_embeddings: list[list[float]] = []
        self._known_names: list[str] = []
        # The control plane runs on its own thread (`services/module.py:73`), so a `DELETE` and a
        # `tick` touch these three containers from different threads. The lock makes one thing true:
        # the pair `(_known_names, _known_embeddings)` is always read as a pair, and every mutation
        # is seen whole or not at all. It is held across the mutation and across the *snapshot* a
        # reader takes, never across dlib or cv2 (P4 PL7).
        self._identity_lock = threading.Lock()

    def start(self, context) -> None:
        if not self.status.enabled:
            return

        settings = (context.get("settings") or {}).get("face_recognition", {})
        backend = settings.get("backend", "stub")
        self.backend = backend

        if backend == "stub":
            self._become_ready(context, backend)
            return

        if backend == "opencv":
            try:
                import cv2  # type: ignore
            except Exception as exc:  # noqa: BLE001
                self.disable(f"OpenCV backend unavailable: {exc}")
                return

            self._cv2 = cv2
            haar_path = settings.get("opencv_haar_path")
            if not haar_path:
                data_obj = getattr(self._cv2, "data", None)
                if data_obj is not None and getattr(data_obj, "haaracascades", None) is None:
                    # some cv2 distributions expose haarcascades under 'haaracascades' attribute
                    pass
                # best-effort default path when cv2 provides haarcascades
                if data_obj is not None and getattr(data_obj, "haarcascades", None) is not None:
                    haar_path = str(Path(data_obj.haarcascades) / "haarcascade_frontalface_default.xml")
                else:
                    haar_path = ""
            haar_path = self._resolve_path(haar_path)
            if not haar_path.exists():
                self.disable(f"Haar cascade not found: {haar_path}")
                return
            self._cascade = cv2.CascadeClassifier(str(haar_path))

            lbph_settings = settings.get("lbph", {})
            if lbph_settings.get("enabled", True) and hasattr(cv2, "face"):
                try:
                    self._recognizer = cv2.face.LBPHFaceRecognizer_create()  # type: ignore[attr-defined]
                except Exception as exc:  # noqa: BLE001
                    logger.warning("LBPH unavailable: %s", exc)
                    self._recognizer = None

            if self._recognizer is not None:
                model_path = self._resolve_path(
                    lbph_settings.get("model_path", "~/.houndmind/face/face_model.yml")
                )
                dataset_dir = self._resolve_path(
                    lbph_settings.get("dataset_dir", "~/.houndmind/face/dataset")
                )
                label_map_path = self._resolve_path(
                    lbph_settings.get("label_map_path", "~/.houndmind/face/face_labels.json")
                )
                # Kept for a forget: deleting a person's images is useless if the model built from
                # them stays trained, and the retrain needs the same three paths (P4 PL7).
                self._model_path = model_path
                self._dataset_dir = dataset_dir
                self._label_map = self._load_label_map(label_map_path)
                self._label_map_path = label_map_path
                if model_path.exists():
                    try:
                        self._recognizer.read(str(model_path))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to read LBPH model: %s", exc)
                elif dataset_dir.exists():
                    self._train_lbph(dataset_dir, model_path, label_map_path)

            self._become_ready(context, backend)
            return

        if backend == "face_recognition":
            try:
                import face_recognition  # type: ignore  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                self.disable(f"face_recognition backend unavailable: {exc}")
                return

            self._embeddings_path = self._resolve_path(
                settings.get("embeddings_path", "~/.houndmind/face/face_embeddings.json")
            )
            self._load_embeddings()
            self._become_ready(context, backend)
            return

        self.disable(f"Unknown face recognition backend: {backend}")

    def _become_ready(self, context, backend: str) -> None:
        """One place that says "this backend is up": status, the forgetter, then the roster.

        The three travel together. A client able to read the roster but not delete from it — or to
        delete from a module that never announced itself — is a state the API should not be able to
        observe, and splitting this across three call sites is how such a state appears (P4 PL7).
        """
        self.available = True
        context.set("face_recognition_status", {"status": "ready", "backend": backend})
        context.set("identity_admin", IdentityForgetter(self, context))
        self._publish_roster(context)

    def stop(self, context) -> None:
        """Take the forgetter and the roster down with the module.

        `place_store` clears at stop for the same reason: a route that can still write through a
        stopped module is writing into something nobody is running, and a stale roster is a claim
        about a detector that is no longer detecting.
        """
        self.available = False
        context.set("identity_admin", None)
        context.set("identity_roster", None)

    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return

        settings = (context.get("settings") or {}).get("face_recognition", {})
        if not settings.get("enabled", True):
            return

        command = context.get("face_recognition_command")
        if isinstance(command, dict):
            self._handle_command(command, context, settings)
            context.set("face_recognition_command", None)

        detections: list[dict[str, Any]] = []
        raw = context.get("vision_faces_raw")
        if isinstance(raw, list):
            detections = raw

        frame = context.get("vision_frame")
        if detections:
            context.set("faces", self._wrap_faces(context, detections))
            return

        if frame is None:
            return

        if self.backend == "opencv":
            detections = self._detect_opencv(frame, settings)
        elif self.backend == "face_recognition":
            detections = self._detect_face_recognition(frame, settings)
        else:
            detections = []

        context.set("faces", self._wrap_faces(context, detections))

    def _wrap_faces(self, context, detections: list[dict[str, Any]]) -> dict[str, Any]:
        # The frame's own time when the producer stamps one (`vision_pi4.py:172`), because
        # `settings.perception.occupancy` measures staleness against this value: a frozen frame has
        # to age even while this module keeps ticking on it. Without one, the tick is the worse
        # answer but still an answer (P4 PL4).
        stamp = context.get("vision_frame_ts")
        if stamp is None:
            stamp = context.get("tick_ts")
        return {
            "timestamp": stamp,
            "backend": self.backend,
            "detected": detections,
        }

    def _publish_roster(self, context) -> None:
        """Who this module can recognise, and which file taught it — names and ids only.

        The embeddings never leave this object: `GET /api/v1/people` is `admin` for exactly that
        reason (`robot-pet-design.md` §6.4), so the roster it serves is a list of people, not a
        list of biometrics (P4 PL6).

        The id is `slug(name)`, the rule `Place.id` already follows — an id is data a client stores,
        so it has to be stable while the name is (`kernel/place.py:16`). Two enrollments under one
        name are one person with two reference faces, which is how `_detect_face_recognition`
        already treats them. No count of those faces is published: `face_recognition` could report
        one and LBPH could not, and a field that is sometimes `null` is a field clients get wrong.

        Every mutation calls this. A new writer of `_known_names` or `_label_map` that forgets to
        leaves the roster stale while the detector keeps recognising a person the roster omits.

        Callers already holding `_identity_lock` use `_publish_roster_locked`: a plain `Lock` is not
        re-entrant, and a forget republishes while it holds the lock (P4 PL7).
        """
        with self._identity_lock:
            self._publish_roster_locked(context)

    def _publish_roster_locked(self, context) -> None:
        if self.backend == "face_recognition":
            names = list(self._known_names)
            path = self._embeddings_path
        elif self.backend == "opencv":
            # LBPH identifies too — `_detect_opencv` labels each face out of this map. It is the
            # Haar cascade alone that only ever answers "a person is here".
            names = list(self._label_map.values())
            path = self._label_map_path
        else:
            names, path = [], None

        people: dict[str, dict[str, str]] = {}
        for name in names:
            if not isinstance(name, str) or not name.strip():
                continue
            key = slug(name)
            if key and key not in people:
                people[key] = {"id": key, "name": name}
        context.set(
            "identity_roster",
            {
                "backend": self.backend,
                "path": str(path) if path is not None else None,
                "people": [people[key] for key in sorted(people)],
            },
        )

    def _detect_opencv(self, frame, settings: dict) -> list[dict[str, Any]]:
        if self._cv2 is None or self._cascade is None:
            return []
        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        scale_factor = float(settings.get("scale_factor", 1.1))
        min_neighbors = int(settings.get("min_neighbors", 5))
        min_face_px = int(settings.get("min_face_px", 60))

        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=scale_factor,
            minNeighbors=min_neighbors,
            minSize=(min_face_px, min_face_px),
        )

        results: list[dict[str, Any]] = []
        lbph_settings = settings.get("lbph", {})
        threshold = float(lbph_settings.get("confidence_threshold", 70.0))
        # One snapshot per frame: `_train_lbph` rebinds the map wholesale, so a held reference is a
        # consistent old view. Reading the attribute per face would let a forget land mid-loop and
        # name somebody the user has just removed (P4 PL7).
        with self._identity_lock:
            label_map = self._label_map
        for x, y, w, h in faces:
            entry: dict[str, Any] = {"bbox": [int(x), int(y), int(w), int(h)]}
            if self._recognizer is not None:
                face_roi = gray[y : y + h, x : x + w]
                try:
                    label_id, confidence = self._recognizer.predict(face_roi)
                    name = label_map.get(int(label_id), "unknown")
                    entry.update({"label": name, "confidence": float(confidence)})
                    if confidence > threshold:
                        entry["label"] = "unknown"
                except Exception as exc:  # noqa: BLE001
                    logger.debug("LBPH prediction failed: %s", exc)
            results.append(entry)
        return results

    def _detect_face_recognition(self, frame, settings: dict) -> list[dict[str, Any]]:
        try:
            import face_recognition  # type: ignore
        except ImportError as exc:
            # An empty list is a claim that nobody is in frame; this module cannot make that claim
            # when the wheel behind it is gone (`start` normally catches this first, PL4).
            self.disable(f"missing dependency: face_recognition ({exc})")
            return []

        rgb = frame[:, :, ::-1]
        locations = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, locations)
        threshold = float(settings.get("match_threshold", 0.6))
        results: list[dict[str, Any]] = []

        # The pair, read once and under the lock. `_known_names` and `_known_embeddings` are parallel
        # by contract, so reading them separately lets a forget land in between and leave the
        # distance array longer than the name list — `known_names[best_idx]` would then raise, or
        # worse, name the wrong person (P4 PL7).
        with self._identity_lock:
            known_embeddings = self._known_embeddings
            known_names = self._known_names

        for (top, right, bottom, left), encoding in zip(locations, encodings, strict=False):
            label = "unknown"
            confidence = None
            if known_embeddings:
                distances = face_recognition.face_distance(
                    known_embeddings, encoding
                )
                if len(distances) > 0:
                    best_idx = int(distances.argmin())  # type: ignore[attr-defined]
                    best_dist = float(distances[best_idx])
                    if best_dist <= threshold:
                        label = known_names[best_idx]
                        confidence = 1.0 - best_dist
            results.append(
                {
                    "bbox": [int(left), int(top), int(right - left), int(bottom - top)],
                    "label": label,
                    "confidence": confidence,
                }
            )
        return results

    def forget(self, person_id: str, context) -> dict[str, str] | None:
        """Delete every reference face filed under `person_id`; `None` when nobody matches.

        Matching is by `slug` over the raw names, not by the one name the roster publishes: PL6
        collapses `"Alex Kim"` and `"Alex  Kim"` into a single `alex_kim`, and a name-keyed delete
        would leave the second one alive under an id the client was just told it had removed.

        The two backends are handled where their identities actually live — dlib in a JSON of
        parallel lists, LBPH in a directory of images plus a trained model — because deleting the
        images and forgetting the model are different acts, and only the second stops the dog
        recognising the person (P4 PL7).
        """
        with self._identity_lock:
            return self._forget_locked(person_id, context)

    def _forget_locked(self, person_id: str, context) -> dict[str, str] | None:
        wanted = person_id.strip()
        if not wanted:
            return None

        if self.backend == "face_recognition":
            doomed = [name for name in self._known_names if slug(name) == wanted]
            if not doomed:
                return None
            kept = [
                (name, embedding)
                for name, embedding in zip(
                    self._known_names, self._known_embeddings, strict=False
                )
                if slug(name) != wanted
            ]
            self._known_names = [name for name, _ in kept]
            self._known_embeddings = [embedding for _, embedding in kept]
            self._save_embeddings_locked()
            self._publish_roster_locked(context)
            return {"id": wanted, "name": doomed[0]}

        if self.backend == "opencv":
            doomed = [name for name in self._label_map.values() if slug(name) == wanted]
            if not doomed:
                return None
            if self._dataset_dir is not None:
                for name in doomed:
                    # `ignore_errors`: a person can be forgotten when only the trained model
                    # survived a partial cleanup, and a missing directory is not a failure here.
                    shutil.rmtree(self._dataset_dir / name, ignore_errors=True)
            # Dropped from the map before any retrain, so a retrain that cannot run (no cv2, no
            # recognizer) still leaves a roster that does not name the person just forgotten.
            self._label_map = {
                label_id: name
                for label_id, name in self._label_map.items()
                if slug(name) != wanted
            }
            self._retrain_locked()
            self._publish_roster_locked(context)
            return {"id": wanted, "name": doomed[0]}

        return None

    def _retrain_locked(self) -> None:
        """Rebuild LBPH from the images that remain, or retire it when none do.

        `_train_lbph_locked` returns early on an empty dataset, which is right while enrolling — an
        enrol always adds a face — and wrong here: after the last person is forgotten the old model
        would stay trained and keep naming the person the user just deleted. So the empty case
        removes the model, empties the label map, and swaps in a fresh untrained recognizer: the
        module keeps detecting faces and simply stops naming them. It is not set to `None`, because
        `_train_lbph_locked` refuses to train a module whose recognizer is `None` — the next
        enrolment would then be silently anonymous for ever (P4 PL7).
        """
        dataset_dir = self._dataset_dir
        model_path = self._model_path
        label_map_path = self._label_map_path
        if dataset_dir is None or model_path is None or label_map_path is None:
            return
        if self._has_training_images(dataset_dir):
            self._train_lbph_locked(dataset_dir, model_path, label_map_path)
            return

        try:
            model_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove the LBPH model: %s", exc)
        try:
            label_map_path.parent.mkdir(parents=True, exist_ok=True)
            label_map_path.write_text("{}", encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not clear the LBPH label map: %s", exc)
        self._label_map = {}
        self._recognizer = self._fresh_recognizer()
        logger.info("Last person forgotten: LBPH model removed, recognizer is untrained")

    def _has_training_images(self, dataset_dir: Path) -> bool:
        """True when at least one person directory still holds an image."""
        if not dataset_dir.exists():
            return False
        for person_dir in dataset_dir.iterdir():
            if person_dir.is_dir() and any(person_dir.glob("*.png")):
                return True
        return False

    def _fresh_recognizer(self) -> Any | None:
        """A new, untrained LBPH recognizer — or `None` when cv2 cannot build one.

        Recreated rather than cleared because `LBPHFaceRecognizer` has no reset: dropping a trained
        model means dropping the object that holds it (P4 PL7).
        """
        cv2 = self._cv2
        if cv2 is None or not hasattr(cv2, "face"):
            return None
        try:
            return cv2.face.LBPHFaceRecognizer_create()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("LBPH unavailable while retiring the model: %s", exc)
            return None

    def _handle_command(self, command: dict, context, settings: dict) -> None:
        action = command.get("action")
        name = command.get("name")
        frame = context.get("vision_frame")
        if action != "enroll" or not name or frame is None:
            return

        if self.backend == "opencv":
            self._enroll_opencv(name, frame, settings)
        elif self.backend == "face_recognition":
            self._enroll_face_recognition(name, frame, settings)
        else:
            # Nothing was written, so the roster cannot have changed.
            return
        self._publish_roster(context)

    def _enroll_opencv(self, name: str, frame, settings: dict) -> None:
        if self._cv2 is None or self._cascade is None:
            return
        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) != 1:
            logger.warning("Enroll requires exactly one face; got %d", len(faces))
            return

        x, y, w, h = faces[0]
        face_roi = gray[y : y + h, x : x + w]

        lbph_settings = settings.get("lbph", {})
        dataset_dir = self._resolve_path(
            lbph_settings.get("dataset_dir", "~/.houndmind/face/dataset")
        )
        dataset_dir.mkdir(parents=True, exist_ok=True)
        person_dir = dataset_dir / name
        person_dir.mkdir(parents=True, exist_ok=True)
        filename = person_dir / f"{int(time.time())}.png"
        cv2.imwrite(str(filename), face_roi)

        model_path = self._resolve_path(
            lbph_settings.get("model_path", "~/.houndmind/face/face_model.yml")
        )
        label_map_path = self._resolve_path(
            lbph_settings.get("label_map_path", "~/.houndmind/face/face_labels.json")
        )
        self._train_lbph(dataset_dir, model_path, label_map_path)

    def _train_lbph(
        self, dataset_dir: Path, model_path: Path, label_map_path: Path
    ) -> None:
        with self._identity_lock:
            self._train_lbph_locked(dataset_dir, model_path, label_map_path)

    def _train_lbph_locked(
        self, dataset_dir: Path, model_path: Path, label_map_path: Path
    ) -> None:
        if self._cv2 is None or self._recognizer is None:
            return
        cv2 = self._cv2
        faces: list[Any] = []
        labels: list[int] = []
        label_map: dict[int, str] = {}
        label_id = 0

        for person_dir in sorted(dataset_dir.iterdir()):
            if not person_dir.is_dir():
                continue
            label_map[label_id] = person_dir.name
            for img_path in person_dir.glob("*.png"):
                img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                faces.append(img)
                labels.append(label_id)
            label_id += 1

        if not faces:
            return

        try:
            import numpy as np  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("NumPy required for LBPH training: %s", exc)
            return
        self._recognizer.train(faces, np.array(labels))
        model_path.parent.mkdir(parents=True, exist_ok=True)
        self._recognizer.save(str(model_path))
        label_map_path.parent.mkdir(parents=True, exist_ok=True)
        label_map_path.write_text(json.dumps(label_map, indent=2), encoding="utf-8")
        self._label_map = label_map

    def _enroll_face_recognition(self, name: str, frame, settings: dict) -> None:
        try:
            import face_recognition  # type: ignore
        except ImportError as exc:
            # Returning here used to mean "enrolled" from the caller's side with no file written:
            # a missing wheel is a module that cannot do its job, not a silent no-op (P4 PL4).
            self.disable(f"missing dependency: face_recognition ({exc})")
            return

        rgb = frame[:, :, ::-1]
        locations = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, locations)
        if len(encodings) != 1:
            logger.warning("Enroll requires exactly one face; got %d", len(encodings))
            return

        # Rebound together under the lock, never appended one list at a time: the two lists are
        # parallel by contract, and a reader that sees an embedding without its name is a wrong
        # label at best and an `IndexError` at worst (P4 PL7).
        with self._identity_lock:
            self._known_embeddings = [*self._known_embeddings, encodings[0].tolist()]
            self._known_names = [*self._known_names, name]
            self._save_embeddings_locked()

    def _load_embeddings(self) -> None:
        if self._embeddings_path is None or not self._embeddings_path.exists():
            return
        try:
            payload = json.loads(self._embeddings_path.read_text(encoding="utf-8"))
            with self._identity_lock:
                self._known_embeddings = payload.get("embeddings", [])
                self._known_names = payload.get("names", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load embeddings: %s", exc)

    def _save_embeddings(self) -> None:
        with self._identity_lock:
            self._save_embeddings_locked()

    def _save_embeddings_locked(self) -> None:
        if self._embeddings_path is None:
            return
        self._embeddings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"names": self._known_names, "embeddings": self._known_embeddings}
        self._embeddings_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _load_label_map(self, label_map_path: Path) -> dict[int, str]:
        if not label_map_path.exists():
            return {}
        try:
            payload = json.loads(label_map_path.read_text(encoding="utf-8"))
            return {int(k): v for k, v in payload.items()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load label map: %s", exc)
            return {}

    def _resolve_path(self, value: str) -> Path:
        """A configured path, with `~` honoured before anything else happens to it.

        `settings.face_recognition` defaults and every other persisted file — places, routines, the
        API token — live under `~/.houndmind`, so a `~` that reached the filesystem literally would
        write a directory named `~` inside the install tree: the #104 bug wearing a different hat.
        `PlaceStore.__init__` already expands here (`kernel/place_store.py:145`).
        """
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.repo_root / path
        return path
