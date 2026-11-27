#!/usr/bin/env python3
"""Fail closed on the small, non-secret configuration contract for ENG-09.

This intentionally uses only the standard library so an operator can run it
before installing database dependencies.  It validates *names and safe
environment declarations*; it never prints a DSN or other value.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REQUIRED = ("DATABASE_URL", "TRAVEL_APP_DATABASE_URL", "ENG02_ADMIN_DATABASE_URL", "TRAVEL_ENVIRONMENT", "TRAVEL_DEPLOYMENT_ID")
ALLOWED_ENVIRONMENTS = {"MOCK", "SANDBOX"}


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{number}: expected NAME=value")
        name, value = line.split("=", 1)
        if not name or not name.replace("_", "").isalnum() or not name[0].isalpha():
            raise ValueError(f"{path}:{number}: invalid environment variable name")
        values[name] = value
    return values


def validate(values: dict[str, str], *, example: bool = False) -> list[str]:
    errors = [f"missing {name}" for name in REQUIRED if not values.get(name)]
    environment = values.get("TRAVEL_ENVIRONMENT")
    if environment and environment not in ALLOWED_ENVIRONMENTS:
        errors.append("TRAVEL_ENVIRONMENT must be MOCK or SANDBOX for this repository baseline")
    deployment_id = values.get("TRAVEL_DEPLOYMENT_ID", "")
    if deployment_id and (len(deployment_id) > 128 or any(ch.isspace() for ch in deployment_id)):
        errors.append("TRAVEL_DEPLOYMENT_ID must be a non-secret, whitespace-free identifier of at most 128 characters")
    database_urls = ("DATABASE_URL", "TRAVEL_APP_DATABASE_URL", "ENG02_ADMIN_DATABASE_URL")
    if example:
        for name in database_urls:
            if name in values and "CHANGE_ME" not in values[name]:
                errors.append(f"{name} in an example must use CHANGE_ME placeholder")
    else:
        for name in database_urls:
            if values.get(name) and "CHANGE_ME" in values[name]:
                errors.append(f"{name} must not use CHANGE_ME outside an example")
        if values.get("DATABASE_URL") and values.get("DATABASE_URL") == values.get("TRAVEL_APP_DATABASE_URL"):
            errors.append("DATABASE_URL and TRAVEL_APP_DATABASE_URL must use separate admin and app credentials")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="read this local .env file instead of process environment")
    parser.add_argument("--example", action="store_true", help="validate .env.example placeholders, not a deployable environment")
    args = parser.parse_args(argv)
    values = read_dotenv(args.env_file) if args.env_file else dict(os.environ)
    errors = validate(values, example=args.example)
    if errors:
        print("ENG-09 preflight failed: " + "; ".join(errors), file=sys.stderr)
        return 2
    print("ENG-09 preflight passed (configuration values intentionally redacted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
