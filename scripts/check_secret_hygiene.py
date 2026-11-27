#!/usr/bin/env python3
"""Small deterministic guard against committing common credential material."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")
HIGH_RISK_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{20,}")
REAL_DSN = re.compile(r"(?:postgres(?:ql)?|mysql)://[^\s:@/]+:[^\s@/]+@", re.I)


def tracked_files(root: Path = ROOT) -> list[Path]:
    output = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
    return [root / name for name in output.decode("utf-8").split("\0") if name]


def findings(root: Path = ROOT) -> list[str]:
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    problems = [] if ".env\n" in ignored or ".env\r\n" in ignored else [".gitignore must ignore .env"]
    example = (root / ".env.example").read_text(encoding="utf-8")
    if "CHANGE_ME" not in example:
        problems.append(".env.example must use CHANGE_ME placeholders")
    for path in tracked_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in (("private key", PRIVATE_KEY), ("high-risk token", HIGH_RISK_TOKEN), ("credential DSN", REAL_DSN)):
            match = pattern.search(text)
            # This fixed, repository-documented password only exists in the
            # disposable hosted PostgreSQL fixture; it is not a credential.
            example_dsn = label == "credential DSN" and ("..." in match.group(0) or "<" in match.group(0)) if match else False
            if match and "eng02-ci-only" not in match.group(0) and not example_dsn:
                problems.append(f"{path.relative_to(root)}: possible {label}")
    return problems


def main() -> int:
    problems = findings()
    if problems:
        print("secret hygiene failed:\n" + "\n".join(problems), file=sys.stderr)
        return 2
    print("secret hygiene passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
