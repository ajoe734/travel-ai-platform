"""AuthorizationError and the registry of error codes it is allowed to raise.

Every code this module raises must already be registered in
specs/domain/error-codes.json (the open registry tests/domain_contract_test.py
also checks) — codes are never invented ad hoc at the raise site.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "specs" / "domain" / "error-codes.json"


def _load_registry() -> dict[str, dict[str, Any]]:
    data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    return {entry["code"]: entry for entry in data["codes"]}


REGISTRY = _load_registry()


class AuthorizationError(Exception):
    """A rejection with a registered machine-readable error code.

    ``detail`` must never disclose whether a resource belonging to a
    different tenant exists (SA 08.3; specs/domain/common/error-envelope.schema.json).
    """

    def __init__(self, code: str, detail: str, *, retryable: bool | None = None) -> None:
        if code not in REGISTRY:
            raise ValueError(f"{code!r} is not a registered error code in {_REGISTRY_PATH}")
        entry = REGISTRY[code]
        self.code = code
        self.http_status = entry["http_status"]
        self.retryable = entry["retryable_default"] if retryable is None else retryable
        self.detail = detail
        super().__init__(f"{code}: {detail}")

    def to_envelope(self, trace_id: str) -> dict[str, Any]:
        """Build an application/problem+json body matching common/error-envelope.schema.json."""
        envelope = {
            "type": self.code,
            "title": self.code.replace("_", " ").title(),
            "status": self.http_status,
            "detail": self.detail,
            "code": self.code,
            "trace_id": trace_id,
            "retryable": self.retryable,
        }
        return envelope


def version_conflict(detail: str) -> AuthorizationError:
    return AuthorizationError("VERSION_CONFLICT", detail)


def idempotency_conflict(detail: str) -> AuthorizationError:
    return AuthorizationError("IDEMPOTENCY_CONFLICT", detail)


def authorization_stale(detail: str) -> AuthorizationError:
    return AuthorizationError("AUTHORIZATION_STALE", detail)


def authorization_scope_mismatch(detail: str) -> AuthorizationError:
    return AuthorizationError("AUTHORIZATION_SCOPE_MISMATCH", detail)


def policy_approval_required(detail: str) -> AuthorizationError:
    return AuthorizationError("POLICY_APPROVAL_REQUIRED", detail)


def cross_tenant_rejected(detail: str) -> AuthorizationError:
    return AuthorizationError("CROSS_TENANT_REFERENCE_REJECTED", detail)


def authorization_use_already_bound(detail: str) -> AuthorizationError:
    return AuthorizationError("AUTHORIZATION_USE_ALREADY_BOUND", detail)


def unverified_approval_rejected(detail: str) -> AuthorizationError:
    return AuthorizationError("UNVERIFIED_APPROVAL_REJECTED", detail)


def actor_role_mismatch(detail: str) -> AuthorizationError:
    return AuthorizationError("ACTOR_ROLE_MISMATCH", detail)


def authorization_revoked(detail: str) -> AuthorizationError:
    return AuthorizationError("AUTHORIZATION_REVOKED", detail)


def revocation_not_permitted(detail: str) -> AuthorizationError:
    return AuthorizationError("REVOCATION_NOT_PERMITTED", detail)
