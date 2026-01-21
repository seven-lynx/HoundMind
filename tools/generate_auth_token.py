#!/usr/bin/env python3
"""Generate a secure auth token for telemetry dashboard.

Usage examples:
  python tools/generate_auth_token.py
  python tools/generate_auth_token.py --length 48
  python tools/generate_auth_token.py --output /etc/houndmind/auth_token.txt
  python tools/generate_auth_token.py --print-config

The script prints the token to stdout by default. Use `--print-config`
to print a JSON config snippet suitable for insertion into
`config/settings.jsonc`.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path
import stat


def write_file_strict(path: Path, content: str) -> None:
    path = path.expanduser()
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    # write file with restricted permissions
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    tmp.replace(path)


def main() -> int:
    p = argparse.ArgumentParser(description="Generate a secure auth token for telemetry dashboard")
    p.add_argument("--length", type=int, default=32, help="token byte length for URL-safe token (default: 32)")
    p.add_argument("--output", type=str, help="write token to file (restricted permissions)")
    p.add_argument("--print-config", action="store_true", help="print JSON config snippet containing the token")
    args = p.parse_args()

    # token_urlsafe takes number of bytes; choose default 32 -> ~43 chars
    token = secrets.token_urlsafe(args.length)

    if args.output:
        try:
            write_file_strict(Path(args.output), token + "\n")
            print(f"Wrote token to {args.output}")
        except Exception as exc:
            print("Failed to write token:", exc)
            return 2

    if args.print_config:
        snippet = {"telemetry": {"auth_token": token}}
        print(json.dumps(snippet, indent=2))
    else:
        print(token)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
