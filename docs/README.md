# HoundMind Documentation

Status: **index** — the map of `docs/`. If a file is not listed here, it should not exist.
Version: v2026.01.18 • Author: 7Lynx
Pairs with: `README.md` (the front door), `ROADMAP.md` (what is planned)

Ten documents plus one reference set, each with one job. Start at the row that matches what you
are doing; do not read the whole directory.

---

## Where to start

| I want to… | Read | Status |
|---|---|---|
| Install HoundMind on a Pi and get it running | [`INSTALL.md`](INSTALL.md) | guide |
| Know what a feature does and how to turn it off | [`FEATURES_GUIDE.md`](FEATURES_GUIDE.md) | reference |
| Write code against the runtime (modules, context keys, config sections) | [`HOUNDMIND_PROGRAMMING_GUIDE.md`](HOUNDMIND_PROGRAMMING_GUIDE.md) | guide |
| Drive the `pidog` library directly, with no HoundMind in the loop | [`PIDOG_PROGRAMMING_GUIDE.md`](PIDOG_PROGRAMMING_GUIDE.md) | guide |
| Look up an exact `pidog` / `robot_hat` signature, pin, limit or trap | [`pidog/INDEX.md`](pidog/INDEX.md) | **reference** set |
| Build a client against the REST/WebSocket API | [`CONTROL_API.md`](CONTROL_API.md) | **contract** |
| Write the routine files the dog plays | [`ROUTINES.md`](ROUTINES.md) | **contract** |
| Understand why the code is shaped this way | [`ARCHITECTURE.md`](ARCHITECTURE.md) | design |
| Read the JSON logs or build a support bundle | [`LOGGING.md`](LOGGING.md) | runbook |
| Check the dog on the bench before calling a build done | [`INSTALL.md`](INSTALL.md) § Bench checklist | guide |
| Know what the project looked like before the 2026.11 refactor | [`BASELINE.md`](BASELINE.md) | **historical** |

## The status field

Every document opens with `Status:` and `Version:` on the two lines under its title. The status
says who the file binds, which is what makes it safe to quote:

| Status | Means | If it is wrong |
|---|---|---|
| `contract` | Two clients code against it. Additive changes only within `v1`. | A test fails; fix the contract and the code together |
| `design` | Explains the layer boundaries. Prose, not code. | Fix the file — the tree is the authority |
| `reference` | Describes behaviour and configuration keys. | Fix the file against `config/settings.jsonc` |
| `guide` | Step-by-step for a human at a keyboard. | Fix the file; a command that does not resolve is a bug |
| `runbook` | What to do when something has already gone wrong. | Fix the file |
| `index` | This page. Navigation only, no facts of its own. | Add the missing row |
| `historical` | A measurement at a fixed commit. **Append, never rewrite.** | Add an addendum section |

`Version:` tracks `pyproject.toml` and `README.md`. All three change in the same commit, or none
of them do.

## Rules for this directory

1. **One job per file.** A document that describes both the wire contract and the install steps
   will be wrong about one of them.
2. **A new file needs a row in the table above**, in the same commit. An unlisted document is
   unreachable and rots.
3. **No document may point outside the repository.** Plans, notes and scratch work live in
   `.houndmind-local/`, which is gitignored; a tracked file that cites a path under it is broken
   for every reader but the author.
4. **Facts come from the tree.** Every command, key and default in these files must be checkable:
   `config/settings.jsonc` for defaults, `src/houndmind_ai/services/api.py` for routes,
   `pyproject.toml` for the interpreter range.
5. **Delete, do not deprecate.** A guide for a feature that no longer exists is a second source of
   truth. The removals are recorded in `CHANGELOG.md`, which is where history belongs.
6. **`docs/pidog/` is one set with its own index.** It documents the two SunFounder libraries at
   API level, split so a reader opens one file and one section. A new file in that directory gets
   a row in its `INDEX.md` file map, not a row here — only the set's entry point is listed above.

## Outside `docs/`

| File | Holds |
|---|---|
| `README.md` | What the project is, the install one-liner, and the feature table |
| `CHANGELOG.md` | Every release, newest first. The only place history is kept |
| `ROADMAP.md` | Planned and completed work, with findings referenced by id |
| `config/settings.jsonc` | The defaults, with a comment on each key |
| `config/actions.jsonc` | The action catalog that `behavior` and `POST /api/v1/command` draw from |
| `examples/` | Runnable demos: `houndmind_mapping_demo.py`, `pidog_programming_examples.py`, `sound_attention_demo.py` |