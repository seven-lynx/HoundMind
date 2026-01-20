"""CLI helper for face recognition enrollment and status.

Usage:
    python -m tools.face_recognition_cli status
    python -m tools.face_recognition_cli faces
    python -m tools.face_recognition_cli enroll --name Alice
"""

from __future__ import annotations

import argparse
import json
import urllib.request


def request_json(url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Face recognition CLI")
    parser.add_argument(
        "command", choices=["status", "faces", "enroll"], help="Command to run"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--name", default=None, help="Name for enroll")
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"

    if args.command == "status":
        print(request_json(f"{base}/status"))
        return
    if args.command == "faces":
        print(request_json(f"{base}/faces"))
        return
    if args.command == "enroll":
        if not args.name:
            raise SystemExit("--name is required for enroll")
        print(request_json(f"{base}/enroll", {"name": args.name}))


if __name__ == "__main__":
    main()
