# Baseline — pre-resurrection state

Status: **historical** — a measurement at one commit. Append to it; never rewrite a number in place.
Version: v2026.01.18 • Author: 7Lynx
Pairs with: `ROADMAP.md` (the findings it references), `docs/ARCHITECTURE.md` (what replaced it)

Captured 2026-11-10 at commit `20f79a0` (tag `legacy-2026.01.18`).
This is the reference point every later phase is measured against. Do not edit it; append.

## Environment actually used

| Item | Value |
|---|---|
| OS | Windows 10/11 workstation |
| Interpreter | **Python 3.14.5** (scoop, `C:\Users\Seito\scoop\apps\python\current`) |
| Other interpreters | none — `py -0p` reports *"No installed Pythons found"* |
| Python 3.10 / 3.11 / 3.13 | **not available on this machine** |
| Tooling | throwaway `.venv-dev` (gitignored): `pytest 9.2.0`, `ruff 0.17.4`, `mypy`, `json5` |
| CI interpreter | **3.11** (`.github/workflows/ci.yml:15`) |

**Caveat that applies to every number below:** the package declares
`requires-python = ">=3.10,<3.12"`, so Python 3.14 is outside its own supported range. The
results are therefore *tooling evidence*, not *compatibility evidence*. Nothing here was
run on Python 3.11 or on a Pi.

## Results

### `pytest -q` (from repo root, `PYTHONPATH=src`)

```
ERROR src/tools/smoke_test.py
ERROR tests/test_vision_preprocessing.py
2 errors in 0.78s
```

- `src/tools/smoke_test.py` matches pytest's default `*_test.py` pattern and is **collected
  as a test module**. Importing it pulls `cv2` → `numpy`, and on a device it would import
  `pidog`. A device CLI is being treated as a test file. (finding **H-12**)
- `tests/test_vision_preprocessing.py` needs `numpy`; CI installs it explicitly
  (`.github/workflows/ci.yml:39`), a developer install from `[lite]` does not.

With those two ignored:

```
40 passed in 0.48s
```

29 test files, 40 test cases. No test touches `hal/motors`, `hal/sensors`,
`navigation/scanning`, `behavior/fsm`, `safety/supervisor`, `safety/watchdog`, or
`main.build_modules`. (finding **H-09**)

### `ruff check src`

```
ruff 0.17.4
Found 238 errors.
```

Top rules:

| Count | Rule |
|---|---|
| 96 | `BLE001` blind-except |
| 26 | `I001` unsorted-imports |
| 22 | `S110` try-except-pass |
| 17 | `RUF100` unused-noqa |
| 14 | `UP006` non-pep585-annotation |
| 11 | `UP035` deprecated-import |
| 11 | `UP045` non-pep604-annotation-optional |
| 9 | `S112` try-except-continue |

There is **no `[tool.ruff]` section anywhere in the repo** and `ruff` is unpinned in
`[dev]` (`pyproject.toml:19`). CI installs whatever PyPI serves, so the lint gate is
non-deterministic by construction and is red at this commit. (finding **H-11**)

The source of the 238 is knowable and fixable: this codebase deliberately uses
`except Exception` at the hardware boundary, which `BLE001` flags. The resolution is an
explicit `[tool.ruff]` selecting the rules the project actually wants, not silencing them.

### `mypy src --ignore-missing-imports`

```
Success: no issues found in 63 source files
```

mypy was green at baseline on 3.14. This is the one gate that can be trusted today, and the
only one that must not regress.

## Not obtained

| Item | Why |
|---|---|
| Python 3.11 results | no 3.11 interpreter on the workstation |
| `pip install -e .[lite,dev]` | impossible on 3.14 — `requires-python` excludes it |
| `python -m build` | packaging unchanged at this commit; not re-run |
| Pi 4 / Pi 5 behaviour | no hardware attached, and the agent does not command motion |
| Servo, camera, audio, thermal | unobservable here; all statements are hypotheses |

## Reproducing this baseline

On a machine with Python 3.11:

```bash
python3.11 -m venv .venv311
. .venv311/bin/activate
pip install -e .[lite,dev] numpy opencv-contrib-python
ruff check src
PYTHONPATH=src pytest -q
mypy src --ignore-missing-imports
```

Expect `pytest` and `mypy` to pass and `ruff` to fail, matching the numbers above unless
the unpinned ruff version has changed again — which is exactly finding H-11.

---

## Addendum — 2026-11-11, after Phases 1–3

Appended, not substituted: the numbers above describe commit `20f79a0` and stay true of it. This
section records what has moved and what has not.

### Fixed since the baseline

| Baseline item | Now | Evidence |
|---|---|---|
| `requires-python = ">=3.10,<3.12"` | `">=3.11,<3.14"` | `pyproject.toml:13` |
| "no `[tool.ruff]` anywhere; ruff unpinned" (**H-11**) | `ruff==0.17.4` pinned and configured with an explicit `select` | `pyproject.toml:29,46-55` |
| `src/tools/smoke_test.py` collected as a test (**H-12**) | fixed — `testpaths = ["tests"]` | `pyproject.toml:61-65` |
| "no test touches `hal/motors`, `safety/watchdog`, `main.build_modules`" (**H-09**) | superseded: `test_hal_lock`, `test_hal_wiring`, `test_watchdog`, `test_supervisor`, `test_gateway`, `test_intents`, `test_runtime_tick`, `test_scanning_worker` | `tests/` |
| `ruff check src` → 238 errors | **clean** | see below |

### Re-measured on the same workstation (2026-11-11)

| Item | Value |
|---|---|
| Interpreter | **Python 3.14.5** |
| `pytest` | `370 passed, 2 skipped` across **53** test files |
| `pytest tests/test_api_routes.py` | `14 passed` — the route table still matches `docs/CONTROL_API.md` |
| `ruff check src` | `All checks passed` |
| `mypy src --ignore-missing-imports` | `Success: no issues found in 82 source files` |

The interpreter caveat above still applies, and it is now sharper rather than softer: 3.14 is outside
the declared `>=3.11,<3.14`, so these are **tooling evidence, not compatibility evidence**. Nothing
here was run on 3.11 or on a Pi. The one gate that is safe to trust is `mypy`, exactly as the
baseline said.

### Known gap, formerly not fixed here

`scripts/installer_core.py` accepted **Python 3.10 and 3.11 only** and refused 3.12+, while
`pyproject.toml:13` declares `>=3.11,<3.14`. The installer was stricter than the metadata in one
direction and looser in the other: it would create an environment on 3.10 that `pip install` then
refused, and it refused 3.12/3.13 even though the package declares support for them. `docs/INSTALL.md`
documented the installer's behaviour, so the documentation inherited the error and told operators to
build a 3.10 venv.

Reconciled in the Pi 5 edition change: `is_supported_python` and the top-level version gate now accept
**3.11–3.13**, which is the declared range, and `docs/INSTALL.md` documents that range. The baseline
above is kept as written — it is what the tree measured before that change, not a description of it.

---

## Addendum — 2026-11-11, after the Pi 5 edition

Appended for the same reason as the addendum above: the earlier sections stay true of the tree they
measured.

### Re-measured on the same workstation

| Item | Value |
|---|---|
| Interpreter | **Python 3.14.5** (`requires-python` is `>=3.11,<3.14`, so this is tooling evidence only) |
| `pytest` | `416 passed, 2 skipped` across **56** test files |
| `ruff check src` | `All checks passed` |
| `mypy src --ignore-missing-imports` | `Success: no issues found in 84 source files` |

### What changed about the baseline's own subject matter

| Baseline item | Now | Evidence |
|---|---|---|
| No board detection anywhere in `src/` (**H-06**) | `board/detect.py` reads the device-tree model and resolves the profile | `src/houndmind_ai/board/detect.py`, `tests/test_board_detect.py` |
| Installer mapped a Pi 5 to `pi4` (**H-06**) | `detect_pi_class` answers `pi4`/`pi5`/`unsupported`/`unknown` and agrees with the runtime | `scripts/installer_core.py`, `tests/test_board_detect.py` |
| Installer accepted 3.10/3.11 and refused 3.12+ | accepts 3.11–3.13, matching `requires-python` | `scripts/installer_core.py`, `docs/INSTALL.md` |

The interpreter caveat is unchanged and still the sharpest thing in this document: every number above
comes from 3.14, which the package excludes, and none of it was run on a Pi.