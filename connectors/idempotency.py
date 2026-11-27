"""In-memory dispatch ledger shared by the mock connectors.

Source: docs/sd/connector-result-and-reconciliation.md §5/§6. A write is
looked up by (tenant_id, connector_account_id, environment, capability_key,
business_key) before any external create; a retry carrying the SAME
request_hash returns the already-created external resource instead of
creating a new one (backlog ENG-04 acceptance: 同 key 不重複建立外部資源).
A different request_hash under the same business_key is a new business
request and is rejected, never silently merged (SD §6.1).

This ledger is this SDK's in-process stand-in for the persisted
task/business_key row ENG-02 owns; it is not a database and is not durable
across process restarts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .errors import BusinessKeyConflictError
from .types import OperationResult


def request_hash(payload: dict) -> str:
    """64 lowercase-hex chars, matching specs/domain's request_hash pattern
    (execution-task.schema.json, execution-attempt.schema.json)."""
    # DB drivers return UUID values for uuid columns.  Callers use this hash
    # for durable snapshots and inbox payloads, so accepting those values here
    # is part of the repository/connector boundary rather than leaving each
    # worker to remember an ad-hoc conversion.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class DispatchRecord:
    request_hash: str
    external_reference: str
    result: OperationResult
    created_count: int = 1
    call_count: int = 1


class IdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str, str, str], DispatchRecord] = {}

    @staticmethod
    def _key(
        tenant_id: str, account_id: str, environment: str, capability_key: str, business_key: str
    ) -> tuple[str, str, str, str, str]:
        return (tenant_id, account_id, environment, capability_key, business_key)

    def get(
        self, tenant_id: str, account_id: str, environment: str, capability_key: str, business_key: str
    ) -> DispatchRecord | None:
        return self._records.get(self._key(tenant_id, account_id, environment, capability_key, business_key))

    def record_dispatch(
        self,
        tenant_id: str,
        account_id: str,
        environment: str,
        capability_key: str,
        business_key: str,
        req_hash: str,
        external_reference: str,
        result: OperationResult,
    ) -> DispatchRecord:
        """Called exactly once per business_key, the first time it is seen,
        before the external side effect (SD §6: 'dispatch intent 在發送前記錄
        穩定 reference'). A later retry must go through reuse(), never this
        method again, so created_count never exceeds 1 for one business_key.
        """
        key = self._key(tenant_id, account_id, environment, capability_key, business_key)
        if key in self._records:
            raise BusinessKeyConflictError(business_key)
        record = DispatchRecord(request_hash=req_hash, external_reference=external_reference, result=result)
        self._records[key] = record
        return record

    def reuse(
        self,
        tenant_id: str,
        account_id: str,
        environment: str,
        capability_key: str,
        business_key: str,
        req_hash: str,
    ) -> DispatchRecord:
        """Looks up an existing dispatch for a retry. Raises
        BusinessKeyConflictError if the retry's payload hash differs from
        the original (SD §6.1)."""
        record = self.get(tenant_id, account_id, environment, capability_key, business_key)
        if record is None:
            raise KeyError(business_key)
        if record.request_hash != req_hash:
            raise BusinessKeyConflictError(business_key)
        record.call_count += 1
        return record

    def update_result(
        self,
        tenant_id: str,
        account_id: str,
        environment: str,
        capability_key: str,
        business_key: str,
        result: OperationResult,
    ) -> DispatchRecord:
        """Overwrites only the stored OperationResult (e.g. PENDING/UNKNOWN
        resolving to a terminal SUCCEEDED/FAILED after reconciliation);
        external_reference and created_count are untouched, since no new
        external resource is ever created by a reconcile."""
        record = self.get(tenant_id, account_id, environment, capability_key, business_key)
        if record is None:
            raise KeyError(business_key)
        record.result = result
        return record
