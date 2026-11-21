# Testing — the suite, what it proves, and what it cannot

Status: **guide** — how to run the tests, what a test may touch, and which claims need a dog instead.
Pairs with: [`HARDWARE_TEST.md`](HARDWARE_TEST.md) (the on-device ladder), [`TOOLS.md`](TOOLS.md) (the
validators), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (what CI runs)

## Run it

```bash
pip install -e .[lite,dev]          # once per machine
PYTHONPATH=src python -m pytest -q                       # the suite
PYTHONPATH=src python -m pytest -q tests/test_gateway.py # one file
PYTHONPATH=src python -m pytest -q -k watchdog           # one subject
```

On Windows PowerShell: `$env:PYTHONPATH='src'; python -m pytest -q`.

`pytest` alone also works: `pyproject.toml` sets `testpaths`, `python_files` and `pythonpath`, so the
package is importable without the environment variable in most shells. The gate commands are `python
-m ruff check src`, `pytest -q` and `mypy src --ignore-missing-imports` — the same three CI runs, in
that order.

## What a test may touch

- **No dog, no camera, no speaker, no network.** `tests/` is hardware-free by rule; a test that needs
  the Pi belongs in `src/tools/`, where a human runs it.
- **`hal/fake.py::FakeDogHAL` is the sanctioned stand-in.** It records `calls`, models distance, IMU
  and battery validity, and takes the bus lock the vendor would. `test_hal_contract.py`,
  `test_hal_wiring.py` and `test_interlock.py` are built on it.
- **A dummy context is enough** for a module: `tests/test_sensor_health.py` shows the two-method
  object (`get`/`set`) a `Module` actually uses.
- **`monkeypatch` for a vendor module**: install a stand-in in `sys.modules` (`tests/test_optional_vision.py`
  does it for `vilib`), or patch the module's own seam (`tests/test_camera_check.py`).
- **Never assert on wall-clock timing without a tolerance.** A 50 ms budget asserted to the
  millisecond fails on a loaded CI box and teaches nobody anything.
- **A default the user relies on is a test.** `tests/test_shipped_defaults.py` reads
  `config/settings.jsonc` raw and asserts the value, so a shipped default cannot drift back silently.

## What CI cannot prove

CI runs Python **3.11** on `ubuntu-latest`, with no hardware. That leaves four kinds of claim it
cannot make, and each has a home:

| Claim | Where it is proved instead |
|---|---|
| Anything that touches the servo bus, an I2C sensor, the camera or the speaker | `docs/HARDWARE_TEST.md`, or a `src/tools/` command run by a person |
| That a start is **motionless** | `python -m houndmind_ai --dry-run` on the device (it builds the registry and ticks nothing) |
| Wall-clock behaviour: loop rate, tick budget, latency, a 30-minute soak | `tools/bench_tick.py`, `docs/LOGGING.md` and the bench logs — a CI number is a floor, not the device's |
| That `systemd`, the installer or a reboot behaves | `packaging/systemd/`, `tools/installer_verify.py`, and the device session that owns the row |

The workstation interpreter is **not** evidence either: `pyproject.toml` supports `>=3.11,<3.14`, so
a pass on a 3.14 venv is tooling evidence. Say which interpreter produced a number.

**Coverage** is measured, not gated: CI prints `--cov=houndmind_ai --cov-report=term` and the last
measured total was **82 %** (13,885 statements, 2,516 missed, Python 3.14.5). There is deliberately no
`--cov-fail-under` — a threshold is a decision, not a default (#397).

## Writing a test that lasts

- Name the defect or the rule, not the function: `test_a_failed_distance_read_is_zero_and_flagged_invalid`
  says what breaks if it fails.
- One behaviour per test. A test that asserts three things fails without saying which one broke.
- Assert the *published contract* (a context key, a JSON field, an exit code), not an internal call
  order, or the next refactor rewrites the suite.
- When a fixture set exists, use it: `tests/fixtures/routines/` is one file per rule, and
  `tests/test_routine_fixtures.py` asserts *which* problem each one produces.
