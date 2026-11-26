"""Validate workbench instances against the real ENG-01 domain schemas and
this task's own specs/workbench/service-revision.schema.json, using the
jsonschema package (not a hand-rolled parser) -- same approach as
tests/domain_contract_test.py's validator_for().

Entities this service persists (Work, ExecutionTask, DecisionRequest) must
pass their specs/domain/*.schema.json before a mutation is accepted; that is
what keeps this in-memory repository's state shape identical to what ENG-02
will enforce in the database.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROOT / "specs" / "domain"
WORKBENCH = ROOT / "specs" / "workbench"

_SCHEMA_FILES = [
    DOMAIN / "common" / "identifiers.schema.json",
    DOMAIN / "common" / "money.schema.json",
    DOMAIN / "common" / "error-envelope.schema.json",
    DOMAIN / "work.schema.json",
    DOMAIN / "execution-task.schema.json",
    DOMAIN / "decision-request.schema.json",
    WORKBENCH / "service-revision.schema.json",
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_store() -> dict:
    store = {}
    for path in _SCHEMA_FILES:
        schema = _load(path)
        store[schema["$id"]] = schema
    return store


_STORE = _build_store()


def _validator_for(schema_path: Path) -> Draft202012Validator:
    schema = _STORE[_load(schema_path)["$id"]]
    resolver = jsonschema.RefResolver.from_schema(schema, store=_STORE)
    return Draft202012Validator(schema, resolver=resolver)


WORK_VALIDATOR = _validator_for(DOMAIN / "work.schema.json")
EXECUTION_TASK_VALIDATOR = _validator_for(DOMAIN / "execution-task.schema.json")
DECISION_REQUEST_VALIDATOR = _validator_for(DOMAIN / "decision-request.schema.json")
SERVICE_REVISION_VALIDATOR = _validator_for(WORKBENCH / "service-revision.schema.json")


def validate_work(instance: dict) -> None:
    jsonschema.validate(instance, WORK_VALIDATOR.schema, resolver=WORK_VALIDATOR.resolver, cls=Draft202012Validator)


def validate_execution_task(instance: dict) -> None:
    jsonschema.validate(
        instance, EXECUTION_TASK_VALIDATOR.schema, resolver=EXECUTION_TASK_VALIDATOR.resolver, cls=Draft202012Validator
    )


def validate_decision_request(instance: dict) -> None:
    jsonschema.validate(
        instance,
        DECISION_REQUEST_VALIDATOR.schema,
        resolver=DECISION_REQUEST_VALIDATOR.resolver,
        cls=Draft202012Validator,
    )


def validate_service_revision(instance: dict) -> None:
    jsonschema.validate(
        instance,
        SERVICE_REVISION_VALIDATOR.schema,
        resolver=SERVICE_REVISION_VALIDATOR.resolver,
        cls=Draft202012Validator,
    )
