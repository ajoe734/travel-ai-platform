"""Workbench service errors, one per registered code in specs/domain/error-codes.json.

Raising the typed subclass (never a bare Exception/ValueError) is what lets a
future HTTP boundary map 1:1 onto the error envelope in
specs/domain/common/error-envelope.schema.json without re-deriving the code
from a message string.
"""
from __future__ import annotations


class WorkbenchError(Exception):
    code: str = "WORKBENCH_ERROR"
    http_status: int = 500

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")


class InvalidServiceRevisionFieldError(WorkbenchError):
    code = "INVALID_SERVICE_REVISION_FIELD"
    http_status = 422


class MissingRequiredInputError(WorkbenchError):
    code = "MISSING_REQUIRED_INPUT"
    http_status = 422


class DecisionNotPendingError(WorkbenchError):
    code = "DECISION_NOT_PENDING"
    http_status = 409


class DecisionOptionUnknownError(WorkbenchError):
    code = "DECISION_OPTION_UNKNOWN"
    http_status = 422


class WorkNotFoundError(WorkbenchError):
    code = "WORK_NOT_FOUND"
    http_status = 404


class WorkPhaseMismatchError(WorkbenchError):
    code = "WORK_PHASE_MISMATCH"
    http_status = 409


class CrossTenantReferenceRejectedError(WorkbenchError):
    code = "CROSS_TENANT_REFERENCE_REJECTED"
    http_status = 404


class VersionConflictError(WorkbenchError):
    code = "VERSION_CONFLICT"
    http_status = 409


class AuthorizationStaleError(WorkbenchError):
    code = "AUTHORIZATION_STALE"
    http_status = 409
