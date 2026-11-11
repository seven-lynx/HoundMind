# Baseline — pre-resurrection state

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