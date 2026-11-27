"""Repository-level errors mapped to specs/domain/error-codes.json.

Each exception carries the registered ``code`` so a thin API layer can build
the application/problem+json envelope (specs/domain/common/error-envelope.schema.json)
without re-deriving it from a raw psycopg/Postgres error.
"""
from __future__ import annotations

import psycopg


class RepositoryError(Exception):
    code: str = "SOURCE_UNAVAILABLE"
    retryable: bool = False

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class IdempotencyConflict(RepositoryError):
    """Same (tenant, actor, operation, idempotency_key) or business_key, different payload."""

    code = "IDEMPOTENCY_CONFLICT"


class InsufficientRefundBalance(RepositoryError):
    code = "INSUFFICIENT_REFUND_BALANCE"


class InsufficientCreditBalance(RepositoryError):
    code = "INSUFFICIENT_CREDIT_BALANCE"


class CreditTermsRequired(RepositoryError):
    code = "CREDIT_TERMS_REQUIRED"


class RefundRouteMismatch(RepositoryError):
    code = "REFUND_ROUTE_MISMATCH"


class CrossTenantReferenceRejected(RepositoryError):
    code = "CROSS_TENANT_REFERENCE_REJECTED"


class AuthorizationUseAlreadyBound(RepositoryError):
    code = "AUTHORIZATION_USE_ALREADY_BOUND"


class VersionConflict(RepositoryError):
    code = "VERSION_CONFLICT"


class ImmutableRecordViolation(RepositoryError):
    """Surfaces a forbid_update_delete()/guard-trigger rejection from the DB.

    Callers should never trigger this in normal operation; it means a code
    path attempted to mutate an append-only table (ADR 0003 / relationships.md).
    """

    code = "IMMUTABLE_RECORD"


def translate_integrity_error(exc: psycopg.Error, *, on_unique_violation: "RepositoryError | None" = None) -> RepositoryError:
    """Map a raw Postgres error to a RepositoryError the caller actually expects.

    ``on_unique_violation`` lets each call site say which specific conflict a
    unique_violation on its own constraint means (e.g. IdempotencyConflict for
    a business_key clash vs AuthorizationUseAlreadyBound for an authorization
    reuse), instead of this module guessing from the constraint name.
    """
    sqlstate = getattr(exc, "sqlstate", None) or getattr(getattr(exc, "diag", None), "sqlstate", None)
    if sqlstate == "23505" and on_unique_violation is not None:  # unique_violation
        return on_unique_violation
    if sqlstate == "0A000":  # feature_not_supported -- forbid_update_delete()/guard triggers
        return ImmutableRecordViolation(str(exc))
    if sqlstate == "23503":  # foreign_key_violation -- e.g. cross-tenant composite FK
        return CrossTenantReferenceRejected(str(exc))
    return RepositoryError(str(exc))
