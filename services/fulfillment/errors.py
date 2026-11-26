"""Fulfillment service errors, one per registered code in
specs/domain/error-codes.json (same pattern as services/workbench/errors.py).
"""
from __future__ import annotations


class FulfillmentError(Exception):
    code: str = "FULFILLMENT_ERROR"
    http_status: int = 500

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")


class WorkNotFoundError(FulfillmentError):
    code = "WORK_NOT_FOUND"
    http_status = 404


class WorkPhaseMismatchError(FulfillmentError):
    code = "WORK_PHASE_MISMATCH"
    http_status = 409


class TaskNotFoundError(FulfillmentError):
    code = "WORK_NOT_FOUND"  # SA 08.3: 存取與錯誤 — same not-found shape, no cross-tenant existence leak.
    http_status = 404


class TaskLeaseContendedError(FulfillmentError):
    code = "TASK_LEASE_CONTENDED"
    http_status = 409


class TaskAlreadyDispatchedError(FulfillmentError):
    code = "TASK_ALREADY_DISPATCHED"
    http_status = 409


class DecisionOptionUnknownError(FulfillmentError):
    code = "DECISION_OPTION_UNKNOWN"
    http_status = 422
