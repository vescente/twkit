"""Refuse a commit that carries a secret: an env file, or a host or password from ~/.twkit/.env.

Reports file and variable names only, never a value.

    .venv/bin/python tools/check_secrets.py            # every tracked file
    .venv/bin/python tools/check_secrets.py --staged   # what the next commit adds (pre-commit hook)
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = "example.env"
GUARDED = ("_HOST", "_PASSWORD")


def guarded_values() -> dict:
    """`TWKIT_*_HOST` and `TWKIT_*_PASSWORD` values from ~/.twkit/.env."""
    sys.path.insert(0, os.path.join(ROOT, "mcp"))
    from twkit import config
    return {k: v for k, v in config.env_file_values().items()
            if k.endswith(GUARDED) and len(v) >= 4}


def is_env_file(path: str) -> bool:
    name = os.path.basename(path)
    return path != TEMPLATE and (name.startswith(".env") or name.endswith(".env"))


def findings(files: dict, values: dict) -> list:
    """`(path, reason)` for every env file and every guarded value found; values never shown."""
    out = [(p, "an environment file") for p in files if is_env_file(p)]
    for path, text in files.items():
        out += [(path, f"the value of {name}") for name, value in values.items() if value in text]
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout


def _files(staged: bool) -> dict:
    names = (_git("diff", "--cached", "--name-only", "--diff-filter=ACMR") if staged
             else _git("ls-files")).splitlines()
    out = {}
    for name in names:
        if staged:
            raw = subprocess.run(["git", "show", f":{name}"], cwd=ROOT, capture_output=True).stdout
        else:
            with open(os.path.join(ROOT, name), "rb") as fh:
                raw = fh.read()
        out[name] = raw.decode("utf-8", errors="ignore")
    return out


def main() -> int:
    found = findings(_files("--staged" in sys.argv), guarded_values())
    for path, reason in found:
        print(f"refused: {path} carries {reason}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
