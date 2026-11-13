# PiDog Examples

Status: **guide** — the three runnable demos in `examples/`, what each proves, and how to start
without moving the dog.

Two of the three run with no hardware at all. The third drives the dog, and says so before you run it.

## The three demos

| File | Hardware? | What it shows |
|---|---|---|
| `pidog_programming_examples.py` | no | The runtime with hardware modules disabled: behaviour, habituation, personality bias, module statuses. Interactive menu or one-shot CLI. |
| `houndmind_mapping_demo.py` | no | A mapping snapshot built from a fixed grid, printed as a map. |
| `sound_attention_demo.py` | **yes** | The dog turns its head toward a detected sound and signals attention on the LED strip. Moves servos. |

## `pidog_programming_examples.py`

Run the interactive menu:

```bash
python examples/pidog_programming_examples.py
```

List the available examples (non-interactive):

```bash
python examples/pidog_programming_examples.py --list
```

Run all of them in sequence:

```bash
python examples/pidog_programming_examples.py all
# or
python examples/pidog_programming_examples.py a
```

Run one by index, or by a case-insensitive substring of its name:

```bash
python examples/pidog_programming_examples.py 2
python examples/pidog_programming_examples.py habituation
```

## `houndmind_mapping_demo.py`

```bash
python examples/houndmind_mapping_demo.py
```

No hardware and no config: it feeds a fixed grid to the mapper and prints the result, which makes it
the fastest way to see the map format before trusting it with a real scan.

## `sound_attention_demo.py`

```bash
python examples/sound_attention_demo.py
```

This is the one that **moves the dog**. Put it on the ground, clear of anything within one body
length, battery charged, with a hand near the power. If all you want is to read the code, the
attention module is documented in `docs/FEATURES_GUIDE.md` §8.

## Notes

- The hardware-free examples disable potentially dangerous modules on purpose, so they are safe to
  run on a workstation. To run one against the robot, review and edit `config/settings.jsonc` (or
  remove the safe-disable calls in the example) — do that only on the robot itself.
- The examples exist to show how modules communicate through `RuntimeContext`. Inspect the printed
  `behavior_action` and `module_statuses` to see module outputs;
  `docs/HOUNDMIND_PROGRAMMING_GUIDE.md` §4 is the key list.

## Contributing an example

Implement a function that takes no arguments and append a tuple to the `EXAMPLES` list in
`examples/pidog_programming_examples.py`:

```py
EXAMPLES.append(("My demo name", my_demo_function))
```

Then run the tests that cover the runtime pieces you touched:

```bash
python -m pytest -q tests/test_habituation.py tests/test_personality_bias.py
```

An example that can move the dog must be opt-in, off by default, and must say so in its docstring.
