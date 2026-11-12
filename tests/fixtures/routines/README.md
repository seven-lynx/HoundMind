# Routine fixtures

One file per rule in `docs/ROUTINES.md`, so a rule that changes has a file that fails.

| Prefix | Meaning |
|---|---|
| `valid_` | `check_routine` accepts it against `config/actions.jsonc`, and the store loads its id |
| `invalid_` | refused, and `tests/test_routine_fixtures.py` asserts *which* problem, at which path |
| `malformed_` | not JSON at all: the store refuses it before the validator runs |
| `collision_` | each legal alone; together only the first file in sorted order keeps the id |

This directory is a legal `settings.routines.dir`, which is why the store test loads it in place
instead of copying it to a temporary one. Nothing here reaches a dog unless someone copies it into
`~/.houndmind/routines/`.

Deliberately absent: the 64-step boundary and the 256 KB cap (both generated in `tmp_path`, because a
quarter-megabyte of junk must not be tracked), and the missing-`id` / duplicate-key documents already
pinned by `tests/test_routine.py`.
