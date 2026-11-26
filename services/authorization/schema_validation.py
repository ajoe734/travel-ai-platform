"""Validate service-built dicts against the real specs/domain/*.schema.json contracts.

Mirrors the resolver setup in tests/domain_contract_test.py (relative $refs
resolve against each schema file's own $id) so AuthorizationService validates
against the exact same schema objects the ENG-01 contract tests do, not a
hand-rolled subset.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

DOMAIN = Path(__file__).resolve().parents[2] / "specs" / "domain"

_SCHEMA_FILES = [
    DOMAIN / "common" / "identifiers.schema.json",
    DOMAIN / "common" / "money.schema.json",
    DOMAIN / "common" / "error-envelope.schema.json",
    DOMAIN / "decision-request.schema.json",
    DOMAIN / "approval-record.schema.json",
]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_store() -> dict[str, Any]:
    store = {}
    for path in _SCHEMA_FILES:
        schema = _load(path)
        store[schema["$id"]] = schema
    return store


_STORE = _build_store()


def _validator_for(schema_path: Path, fragment: str | None = None) -> Draft202012Validator:
    schema = _STORE[_load(schema_path)["$id"]]
    resolver = jsonschema.RefResolver.from_schema(schema, store=_STORE)
    node = schema
    if fragment:
        _, node = resolver.resolve(fragment)
    return Draft202012Validator(node, resolver=resolver)


_DECISION_REQUEST = DOMAIN / "decision-request.schema.json"
_APPROVAL_RECORD = DOMAIN / "approval-record.schema.json"

VALIDATORS = {
    "DecisionRequest": _validator_for(_DECISION_REQUEST),
    "ApprovalRecord": _validator_for(_APPROVAL_RECORD),
    "CustomerConsent": _validator_for(_APPROVAL_RECORD, "#/$defs/CustomerConsent"),
    "ApprovalRevocation": _validator_for(_APPROVAL_RECORD, "#/$defs/ApprovalRevocation"),
    "ExecutionAuthorization": _validator_for(_APPROVAL_RECORD, "#/$defs/ExecutionAuthorization"),
    "AuthorizationUse": _validator_for(_APPROVAL_RECORD, "#/$defs/AuthorizationUse"),
}


class ContractShapeError(ValueError):
    """Raised when a service-built dict does not satisfy its own domain contract.

    This is always an ENG-03 bug, never a caller input problem — by the time a
    dict reaches here it has already passed the service's own business
    validation (AuthorizationError), so a shape failure means the service
    assembled a non-conforming instance.
    """


def validate(entity: str, instance: dict[str, Any]) -> None:
    validator = VALIDATORS[entity]
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        messages = [f"{list(e.path)}: {e.message}" for e in errors]
        raise ContractShapeError(f"{entity} failed its own schema: {messages}")
