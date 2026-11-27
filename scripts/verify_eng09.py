#!/usr/bin/env python3
"""Reproducible local ENG-09 static and unit verification entrypoint."""
from __future__ import annotations

import subprocess
import sys


def run(*command: str) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    run(sys.executable, "scripts/eng09_preflight.py", "--env-file", ".env.example", "--example")
    run(sys.executable, "scripts/check_secret_hygiene.py")
    run(sys.executable, "-m", "py_compile", "db/migrate.py", "db/seeds/load_fixtures.py")
    run(sys.executable, "-m", "compileall", "-q", "db/repository", "services", "connectors", "scripts")
    run(sys.executable, "-m", "pytest", "tests", "-v")
    run("node", "tests/workbench_frontend_test.cjs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
