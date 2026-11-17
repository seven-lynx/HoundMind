"""Write the settings schema as a JSON Schema document.

`config/settings.jsonc` is validated at load time by `kernel/config_schema.py`, which is the only
description of what a key accepts. This tool turns that same tree into JSON Schema draft 2020-12 so
an editor can complete and check the file while it is being written, instead of the first answer
arriving from the dog at start-up.

    python -m tools.schema_export                        # print the document
    python -m tools.schema_export --out settings.schema.json

Point an editor at the file with a `$schema` line in the JSONC document, or by file association.
Nothing here reads hardware, touches a servo, or needs a PiDog.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from houndmind_ai.kernel.config_schema import json_schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the HoundMind settings schema as JSON Schema"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the document here instead of printing it",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation (default 2, use 0 for one line)",
    )
    args = parser.parse_args(argv)

    indent = args.indent if args.indent > 0 else None
    text = json.dumps(json_schema(), indent=indent, sort_keys=False) + "\n"
    if args.out is None:
        sys.stdout.write(text)
        return 0

    try:
        args.out.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"[schema] cannot write {args.out}: {exc}", file=sys.stderr)
        return 1
    print(f"[schema] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
