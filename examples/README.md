PiDog Examples
===============

This folder contains beginner-friendly, safety-first examples for exploring
the HoundMind runtime without moving hardware. The main entrypoint is
`examples/pidog_programming_examples.py` and supports an interactive menu
and a small CLI.

Usage
-----

Run the interactive menu:

```bash
python examples/pidog_programming_examples.py
```

List available examples (non-interactive):

```bash
python examples/pidog_programming_examples.py --list
```

Run all examples sequentially:

```bash
python examples/pidog_programming_examples.py all
# or
python examples/pidog_programming_examples.py a
```

Run a single example by index or name (case-insensitive substring):

```bash
python examples/pidog_programming_examples.py 2
python examples/pidog_programming_examples.py habituation
```

Notes
-----

- Examples disable potentially dangerous hardware by default so they are
  safe to run on a desktop. To enable motors/sensors for robot hardware,
  review and edit your `config/settings.jsonc` or remove the safe-disable
  calls in the example (do this only on the robot itself).
- The examples are intended for learning how the runtime and modules
  communicate via the `RuntimeContext`. Inspect printed `behavior_action`
  and `module_statuses` to understand module outputs.

Contributing
------------

To add a new example, implement a function that takes no arguments and
append a tuple to the `EXAMPLES` list in
`examples/pidog_programming_examples.py`:

```py
EXAMPLES.append(("My demo name", my_demo_function))
```

Run tests locally (targeted) before pushing:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pytest -q tests/test_habituation.py tests/test_personality_bias.py
```
