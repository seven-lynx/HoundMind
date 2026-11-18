# Place fixtures

**Synthetic, and generated rather than committed.** A photograph of somebody's kitchen cannot be a
fixture: it is personal data, it is megabytes, and it says nothing about the code. `frames/` and
`views/` here are therefore empty on purpose — `tests/test_place_match_cli.py` draws deterministic
textured images with OpenCV into a `tmp_path`, teaches one view from them, and runs
`python -m tools.place_match` over the folder.

What the generated set proves:

| Frame | Expected verdict |
|---|---|
| the image the view was taught from | `match`, score ~1.00 |
| a different texture, same size | `no-match`, score below the threshold |
| a flat grey rectangle | `featureless` |

If you need a real set to tune `min_score` on a device, put your own images in a directory like this
one and run the CLI against it — nothing here reads these files, so they cost nothing when absent.
