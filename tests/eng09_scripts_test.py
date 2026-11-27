from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


def _module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _module("eng09_preflight", "scripts/eng09_preflight.py")
hygiene = _module("check_secret_hygiene", "scripts/check_secret_hygiene.py")


def _dsn(user: str, password: str, database: str) -> str:
    """Build intentionally fake DSNs without putting credential-shaped text in git."""
    return "postgresql://" + user + ":" + password + "@db/" + database


class Eng09PreflightTest(unittest.TestCase):
    def test_accepts_complete_non_production_contract(self):
        self.assertEqual(preflight.validate({
            "DATABASE_URL": _dsn("admin", "secret", "admin"), "TRAVEL_APP_DATABASE_URL": _dsn("app", "secret", "app"), "ENG02_ADMIN_DATABASE_URL": _dsn("verify", "secret", "verify"),
            "TRAVEL_ENVIRONMENT": "MOCK", "TRAVEL_DEPLOYMENT_ID": "build-1",
        }), [])

    def test_rejects_missing_admin_role_and_production(self):
        errors = preflight.validate({"DATABASE_URL": "x", "TRAVEL_ENVIRONMENT": "PRODUCTION", "TRAVEL_DEPLOYMENT_ID": "x"})
        self.assertTrue(any("ENG02_ADMIN_DATABASE_URL" in value for value in errors))
        self.assertTrue(any("MOCK or SANDBOX" in value for value in errors))

    def test_example_checks_every_database_url_and_deploy_rejects_placeholders_or_shared_role(self):
        base = {
            "DATABASE_URL": _dsn("admin", "secret", "admin"),
            "TRAVEL_APP_DATABASE_URL": _dsn("app", "secret", "app"),
            "ENG02_ADMIN_DATABASE_URL": _dsn("verify", "secret", "verify"),
            "TRAVEL_ENVIRONMENT": "MOCK", "TRAVEL_DEPLOYMENT_ID": "build-1",
        }
        self.assertEqual(preflight.validate(base), [])
        shared = dict(base, TRAVEL_APP_DATABASE_URL=base["DATABASE_URL"])
        self.assertTrue(any("separate admin and app" in error for error in preflight.validate(shared)))
        placeholder = dict(base, ENG02_ADMIN_DATABASE_URL="postgresql://CHANGE_ME")
        self.assertTrue(any("must not use CHANGE_ME" in error for error in preflight.validate(placeholder)))
        invalid_example = dict(base, TRAVEL_APP_DATABASE_URL=_dsn("app", "real", "app"))
        self.assertTrue(any("TRAVEL_APP_DATABASE_URL" in error for error in preflight.validate(invalid_example, example=True)))


class SecretHygieneTest(unittest.TestCase):
    def test_detects_key_token_and_credential_dsn(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text(".env\n", encoding="utf-8")
            (root / ".env.example").write_text("DATABASE_URL=postgresql://CHANGE_ME\n", encoding="utf-8")
            leaked = root / "leaked.txt"
            leaked.write_text("-----BEGIN " + "PRIVATE KEY-----\n" + "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789\n" + "postgresql://alice:" + "secret@db/x\n", encoding="utf-8")
            original = hygiene.tracked_files
            hygiene.tracked_files = lambda _root: [leaked]
            try:
                problems = hygiene.findings(root)
            finally:
                hygiene.tracked_files = original
        self.assertEqual(len(problems), 3)

    def test_detects_a_real_dsn_after_a_documented_fixture_dsn(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text(".env\n", encoding="utf-8")
            (root / ".env.example").write_text("DATABASE_URL=postgresql://CHANGE_ME\n", encoding="utf-8")
            leaked = root / "leaked.txt"
            leaked.write_text(
                "postgresql://postgres:eng02-ci-only@localhost:5432/postgres\n"
                "postgresql://" + "admin:RealSecret123@prod.example/db\n", encoding="utf-8"
            )
            original = hygiene.tracked_files
            hygiene.tracked_files = lambda _root: [leaked]
            try:
                problems = hygiene.findings(root)
            finally:
                hygiene.tracked_files = original
        self.assertEqual(problems, ["leaked.txt: possible credential DSN"])
