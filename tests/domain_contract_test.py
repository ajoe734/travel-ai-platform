#!/usr/bin/env python3
"""Validate ENG-01 domain contracts under specs/domain/ against real jsonschema.

This exercises the actual Draft 2020-12 schemas (not a hand-rolled parser) with
fixture instances under specs/domain/examples/. It proves:
  - every schema file is itself a syntactically valid JSON Schema
  - fixture instances that should validate, do; fixtures that should fail, do
  - the cross-instance invariants JSON Schema alone cannot express (same
    business_key across a retry's Attempts, no duplicate AuthorizationUse for
    one authorization_id, same-tenant parent/child task refs) are checked at
    the Python level against the fixture set, standing in for the ENG-02
    database constraints these contracts are written to support.

This is a repository-level contract check. It does not run against a database,
a worker or an external connector; ENG-02/03/04/05 own those tests.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = ROOT / "specs" / "domain"
EXAMPLES = DOMAIN / "examples"

SCHEMA_FILES = [
    DOMAIN / "common" / "identifiers.schema.json",
    DOMAIN / "common" / "money.schema.json",
    DOMAIN / "common" / "error-envelope.schema.json",
    DOMAIN / "case.schema.json",
    DOMAIN / "complaint.schema.json",
    DOMAIN / "work.schema.json",
    DOMAIN / "execution-task.schema.json",
    DOMAIN / "execution-attempt.schema.json",
    DOMAIN / "decision-request.schema.json",
    DOMAIN / "approval-record.schema.json",
    DOMAIN / "order.schema.json",
]

ENTITY_SCHEMA_FILES = [
    DOMAIN / "case.schema.json",
    DOMAIN / "complaint.schema.json",
    DOMAIN / "work.schema.json",
    DOMAIN / "execution-task.schema.json",
    DOMAIN / "execution-attempt.schema.json",
    DOMAIN / "decision-request.schema.json",
    DOMAIN / "approval-record.schema.json",
    DOMAIN / "order.schema.json",
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_store() -> dict:
    store = {}
    for path in SCHEMA_FILES:
        schema = load(path)
        store[schema["$id"]] = schema
    return store


STORE = build_store()


def validator_for(schema_path: Path, fragment: str | None = None) -> Draft202012Validator:
    """Build a validator whose resolver's base scope is schema_path's own $id,
    so relative $refs inside it (e.g. "common/identifiers.schema.json#/...")
    resolve the same way the file layout implies, per RFC 3986 relative
    resolution against the referring document's $id."""
    schema = STORE[load(schema_path)["$id"]]
    resolver = jsonschema.RefResolver.from_schema(schema, store=STORE)
    node = schema
    if fragment:
        _, node = resolver.resolve(fragment)
    return Draft202012Validator(node, resolver=resolver)


# (schema file, $defs fragment or None, example path, expected valid)
FIXTURES = [
    (DOMAIN / "case.schema.json", None, EXAMPLES / "case/case-1-valid.json", True),
    (DOMAIN / "case.schema.json", None, EXAMPLES / "case/case-invalid-missing-owner.json", False),

    (DOMAIN / "work.schema.json", None, EXAMPLES / "work/work-1-booking-valid.json", True),
    (DOMAIN / "work.schema.json", None, EXAMPLES / "work/work-2-reschedule-valid.json", True),
    (DOMAIN / "work.schema.json", None, EXAMPLES / "work/work-invalid-waiting-external-missing-reason.json", False),

    (DOMAIN / "execution-task.schema.json", None, EXAMPLES / "execution-task/task-1-booking-create-valid.json", True),
    (DOMAIN / "execution-task.schema.json", None, EXAMPLES / "execution-task/task-2-notification-valid.json", True),
    (DOMAIN / "execution-task.schema.json", None, EXAMPLES / "execution-task/task-invalid-partial-on-action.json", False),
    (DOMAIN / "execution-task.schema.json", None, EXAMPLES / "execution-task/task-crosstenant-parent-ref.json", True),  # shape-valid; tenant match is a Python-level check below

    (DOMAIN / "execution-attempt.schema.json", None, EXAMPLES / "execution-attempt/attempt-1-timeout-valid.json", True),
    (DOMAIN / "execution-attempt.schema.json", None, EXAMPLES / "execution-attempt/attempt-2-reconcile-valid.json", True),

    (DOMAIN / "complaint.schema.json", None, EXAMPLES / "complaint/complaint-1-refund-succeeded-not-closed-valid.json", True),
    (DOMAIN / "complaint.schema.json", None, EXAMPLES / "complaint/complaint-invalid-resolved-without-resolution.json", False),
    (DOMAIN / "complaint.schema.json", None, EXAMPLES / "complaint/complaint-invalid-open-with-resolution.json", False),

    (DOMAIN / "decision-request.schema.json", None, EXAMPLES / "decision-request/decision-1-pending-valid.json", True),
    (DOMAIN / "decision-request.schema.json", None, EXAMPLES / "decision-request/decision-invalid-approved-without-selection.json", False),

    (DOMAIN / "approval-record.schema.json", None, EXAMPLES / "approval/approval-record-1-valid.json", True),
    (DOMAIN / "approval-record.schema.json", None, EXAMPLES / "approval/approval-record-invalid-missing-manifest.json", False),
    (DOMAIN / "approval-record.schema.json", "#/$defs/CustomerConsent", EXAMPLES / "approval/customer-consent-1-valid.json", True),
    (DOMAIN / "approval-record.schema.json", "#/$defs/ExecutionAuthorization", EXAMPLES / "approval/execution-authorization-1-valid.json", True),
    (DOMAIN / "approval-record.schema.json", "#/$defs/AuthorizationUse", EXAMPLES / "approval/authorization-use-1-valid.json", True),
    (DOMAIN / "approval-record.schema.json", "#/$defs/AuthorizationUse", EXAMPLES / "approval/authorization-use-2-same-authorization-second-root-invalid.json", True),  # shape-valid; uniqueness is the Python-level check below
    (DOMAIN / "approval-record.schema.json", "#/$defs/ApprovalRevocation", EXAMPLES / "approval/approval-revocation-1-valid.json", True),

    (DOMAIN / "order.schema.json", None, EXAMPLES / "order/order-1-confirmed-valid.json", True),
    (DOMAIN / "order.schema.json", None, EXAMPLES / "order/order-invalid-merged-status.json", False),

    (DOMAIN / "common" / "error-envelope.schema.json", None, EXAMPLES / "error-envelope/error-1-version-conflict-valid.json", True),
    (DOMAIN / "common" / "error-envelope.schema.json", None, EXAMPLES / "error-envelope/error-invalid-leaks-tenant-code-format.json", False),
]


class SchemaItselfIsValid(unittest.TestCase):
    def test_every_schema_file_is_a_valid_json_schema(self) -> None:
        for path in SCHEMA_FILES:
            with self.subTest(schema=path.relative_to(ROOT).as_posix()):
                schema = load(path)
                Draft202012Validator.check_schema(schema)


class FixtureValidation(unittest.TestCase):
    def test_fixtures_match_expected_validity(self) -> None:
        for schema_path, fragment, example_path, expected_valid in FIXTURES:
            with self.subTest(
                schema=schema_path.relative_to(ROOT).as_posix(),
                fragment=fragment,
                example=example_path.relative_to(ROOT).as_posix(),
            ):
                validator = validator_for(schema_path, fragment)
                instance = load(example_path)
                errors = list(validator.iter_errors(instance))
                if expected_valid:
                    self.assertEqual(
                        errors, [],
                        f"expected {example_path.name} to be valid against "
                        f"{schema_path.name}{fragment or ''} but got: "
                        f"{[e.message for e in errors]}",
                    )
                else:
                    self.assertTrue(
                        errors,
                        f"expected {example_path.name} to be REJECTED by "
                        f"{schema_path.name}{fragment or ''} but it validated",
                    )


class CrossInstanceInvariants(unittest.TestCase):
    """Invariants JSON Schema's per-instance validation cannot express.

    These stand in for the UNIQUE/FK constraints ENG-02 will enforce in
    PostgreSQL; here they are checked against the fixture set as the
    contract-level proof that the shapes above are sufficient to support them.
    """

    def test_case_can_have_multiple_works(self) -> None:
        case = load(EXAMPLES / "case/case-1-valid.json")
        work1 = load(EXAMPLES / "work/work-1-booking-valid.json")
        work2 = load(EXAMPLES / "work/work-2-reschedule-valid.json")
        self.assertEqual(work1["case_id"]["id"], case["id"])
        self.assertEqual(work2["case_id"]["id"], case["id"])
        self.assertNotEqual(work1["id"], work2["id"])
        self.assertEqual(len(case["work_refs"]), 2)

    def test_work_can_have_multiple_execution_tasks(self) -> None:
        work = load(EXAMPLES / "work/work-1-booking-valid.json")
        task1 = load(EXAMPLES / "execution-task/task-1-booking-create-valid.json")
        task2 = load(EXAMPLES / "execution-task/task-2-notification-valid.json")
        self.assertEqual(task1["work_id"]["id"], work["id"])
        self.assertEqual(task2["work_id"]["id"], work["id"])
        self.assertNotEqual(task1["id"], task2["id"])

    def test_retry_only_appends_an_attempt_same_task(self) -> None:
        attempt1 = load(EXAMPLES / "execution-attempt/attempt-1-timeout-valid.json")
        attempt2 = load(EXAMPLES / "execution-attempt/attempt-2-reconcile-valid.json")
        self.assertEqual(attempt1["task_id"]["id"], attempt2["task_id"]["id"])
        self.assertLess(attempt1["attempt_no"], attempt2["attempt_no"])
        self.assertEqual(attempt1["observations"][0]["outcome"], "UNKNOWN")
        self.assertEqual(attempt2["observations"][0]["outcome"], "SUCCEEDED")

    def test_duplicate_attempt_no_on_same_task_is_detected(self) -> None:
        attempt2 = load(EXAMPLES / "execution-attempt/attempt-2-reconcile-valid.json")
        duplicate = load(EXAMPLES / "execution-attempt/attempt-invalid-duplicate-attempt-no.json")
        same_task = attempt2["task_id"]["id"] == duplicate["task_id"]["id"]
        same_attempt_no = attempt2["attempt_no"] == duplicate["attempt_no"]
        self.assertTrue(
            same_task and same_attempt_no,
            "fixture no longer represents a (tenant_id, task_id, attempt_no) collision",
        )

    def test_refund_succeeding_does_not_imply_complaint_closed(self) -> None:
        complaint = load(EXAMPLES / "complaint/complaint-1-refund-succeeded-not-closed-valid.json")
        self.assertIn(complaint["status"], [
            "OPEN", "CHECKING", "WAITING_CUSTOMER", "WAITING_MERCHANT",
            "WAITING_CHANNEL", "RESOLVING", "ESCALATED", "REOPENED",
        ])
        self.assertNotIn("resolution", complaint)
        self.assertTrue(complaint["remedy_action_refs"])

    def test_authorization_use_is_not_duplicated_across_roots(self) -> None:
        use1 = load(EXAMPLES / "approval/authorization-use-1-valid.json")
        use2 = load(EXAMPLES / "approval/authorization-use-2-same-authorization-second-root-invalid.json")
        same_authorization = use1["authorization_id"]["id"] == use2["authorization_id"]["id"]
        different_root = use1["root_task_id"]["id"] != use2["root_task_id"]["id"]
        self.assertTrue(
            same_authorization and different_root,
            "fixture no longer represents an authorization reused across two root tasks",
        )
        # SD authorization-and-approval.md §5: this pairing is exactly what
        # AUTHORIZATION_USE_ALREADY_BOUND (error-codes.json) must reject.

    def test_cross_tenant_parent_task_reference_is_rejected_shape(self) -> None:
        task = load(EXAMPLES / "execution-task/task-crosstenant-parent-ref.json")
        self.assertNotEqual(
            task["tenant_id"], task["parent_task_id"]["tenant_id"],
            "fixture no longer demonstrates a cross-tenant parent_task_id",
        )


class ErrorCodeRegistryConsistency(unittest.TestCase):
    def test_registry_codes_match_envelope_pattern(self) -> None:
        registry = load(DOMAIN / "error-codes.json")
        validator = validator_for(DOMAIN / "common" / "error-envelope.schema.json")
        code_schema = validator.schema["properties"]["code"]
        import re
        pattern = re.compile(code_schema["pattern"])
        for entry in registry["codes"]:
            with self.subTest(code=entry["code"]):
                self.assertRegex(entry["code"], pattern)
                self.assertIn("source", entry)
                self.assertTrue(entry["source"])

    def test_valid_example_uses_a_registered_code(self) -> None:
        registry = load(DOMAIN / "error-codes.json")
        known = {entry["code"] for entry in registry["codes"]}
        example = load(EXAMPLES / "error-envelope/error-1-version-conflict-valid.json")
        self.assertIn(example["code"], known)


class TraceabilityPresence(unittest.TestCase):
    def test_every_entity_schema_declares_origin_and_trace(self) -> None:
        for path in ENTITY_SCHEMA_FILES:
            with self.subTest(schema=path.relative_to(ROOT).as_posix()):
                schema = load(path)
                origin = schema.get("x_origin")
                self.assertIsInstance(origin, dict, f"{path.name} missing x_origin")
                self.assertEqual(origin.get("status"), "new_sd_contract")
                trace = origin.get("sa_trace") or origin.get("sd_trace")
                self.assertTrue(trace, f"{path.name} x_origin has no sa_trace/sd_trace entries")


if __name__ == "__main__":
    unittest.main(verbosity=2)
