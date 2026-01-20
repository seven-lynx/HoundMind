"""Collect a support bundle including recent logs and config files.

Usage:
    python -m tools.collect_support_bundle /path/to/output.zip

If no output path is provided the script will create `logs/support_bundle_{timestamp}.zip`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def gather_git_commit(root: Path) -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL)
        return out.decode().strip()
    except Exception:
        return None


def collect(bundle_path: Path) -> None:
    root = repo_root()
    logs = root / "logs"
    config = root / "config" / "settings.jsonc"
    # try to gather a trace id for correlation: prefer env var, then scan recent logs
    def _find_trace_in_logs(logs_dir: Path) -> str | None:
        if not logs_dir.exists():
            return None
        # check latest files first
        files = sorted([p for p in logs_dir.iterdir() if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
        trace_re = re.compile(r'"trace_id"\s*:\s*"([^"]+)"')
        for f in files:
            try:
                data = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            # search for last occurrence
            m = trace_re.search(data[::-1])
            if m:
                # reverse-match workaround: fallback to forward search
                m2 = trace_re.search(data)
                if m2:
                    return m2.group(1)
        return None

    trace_id = os.environ.get("HOUNDMIND_TRACE_ID")
    if not trace_id:
        trace_id = _find_trace_in_logs(logs)

    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": gather_git_commit(root),
        "trace_id": trace_id,
    }

    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as z:
        # Add metadata
        z.writestr("metadata.json", json.dumps(metadata, indent=2))

        # Add config if present
        if config.exists():
            z.write(config, arcname=str(Path("config") / config.name))

        # Add top-level docs for context
        for name in ("README.md", "pyproject.toml", "ROADMAP.md"):
            p = root / name
            if p.exists():
                z.write(p, arcname=name)

        # Add logs: include recent full files and a trimmed tail
        if logs.exists() and logs.is_dir():
            for f in sorted(logs.iterdir()):
                if not f.is_file():
                    continue
                if f.suffix in (".gz", ".zip"):
                    # include compressed rotated files as-is
                    z.write(f, arcname=str(Path("logs") / f.name))
                    continue
                # include full file if small, otherwise include last 2000 lines as a trimmed file
                try:
                    size_mb = f.stat().st_size / (1024 * 1024)
                    if size_mb < 2:
                        z.write(f, arcname=str(Path("logs") / f.name))
                    else:
                        tail = f.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
                        z.writestr(str(Path("logs") / (f.name + ".tail.txt")), "\n".join(tail))
                except Exception:
                    # best-effort
                    try:
                        z.write(f, arcname=str(Path("logs") / f.name))
                    except Exception:
                        pass

    print(f"Support bundle created: {bundle_path}")


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    root = repo_root()
    default_dir = root / "logs" / "support_bundles"
    default_dir.mkdir(parents=True, exist_ok=True)
    if argv:
        out = Path(argv[0])
        if out.is_dir():
            out = out / f"support_bundle_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
    else:
        out = default_dir / f"support_bundle_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"

    try:
        collect(out)
        return 0
    except Exception as exc:
        print("Failed to create support bundle:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
