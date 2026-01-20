"""CLI helper to inject voice commands/text into a running HoundMind session.

Usage:
    python -m tools.voice_cli say --text "sit"
    python -m tools.voice_cli command --action "forward"
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
    parser = argparse.ArgumentParser(description="Voice assistant CLI")
    parser.add_argument(
        "command", choices=["say", "command", "status"], help="Command to run"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--text", default=None, help="Text to interpret")
    parser.add_argument("--action", default=None, help="Direct action override")
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"

    if args.command == "status":
        print(request_json(f"{base}/status"))
        return
    if args.command == "say":
        if not args.text:
            raise SystemExit("--text is required for say")
        print(request_json(f"{base}/say", {"text": args.text}))
        return
    if args.command == "command":
        if not args.action:
            raise SystemExit("--action is required for command")
        print(request_json(f"{base}/command", {"action": args.action}))
        return


if __name__ == "__main__":
    main()
