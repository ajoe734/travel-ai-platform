"""ExperienceReservationMock: synchronous timeslot/session booking.

SD connector-result-and-reconciliation.md §9: must deliver session
resource modelling, synchronous booking, the same reference back for the
same business key, and a resource-conflict failure mode. Must NOT be read
as proof that any real experience platform has granted this tenant
access.
"""
from __future__ import annotations

from ..base import Connector
from ..idempotency import IdempotencyStore, request_hash
from ..types import (
    AuthorizationState,
    CapabilityDescriptor,
    ConnectorMode,
    Failed,
    IdempotencySupport,
    LookupSupport,
    MerchantConsentState,
    OperationalAvailability,
    OperationResult,
    SideEffect,
    SideEffectDisposition,
    Succeeded,
    SupportLevel,
)

ACCOUNT_ID = "mock-experience-account"
ENVIRONMENT = "sandbox"


def _capabilities() -> dict[str, CapabilityDescriptor]:
    common = dict(
        authorization_state=AuthorizationState.ACTIVE,
        merchant_consent=MerchantConsentState.GRANTED,
        operational_availability=OperationalAvailability.AVAILABLE,
        mode=ConnectorMode.SYNC,
        inventory_model="TIMESLOT",
    )
    return {
        "availability.read": CapabilityDescriptor(
            capability_key="availability.read",
            support=SupportLevel.SUPPORTED,
            side_effect=SideEffect.READ,
            readable_fields=("session_id", "starts_at", "capacity", "booked"),
            **common,
        ),
        "booking.create": CapabilityDescriptor(
            capability_key="booking.create",
            support=SupportLevel.SUPPORTED,
            side_effect=SideEffect.WRITE,
            writable_fields=("session_id", "party_size"),
            idempotency=IdempotencySupport(
                supported=True,
                key_scope="tenant+account+environment+business_key",
                retention="session lifetime",
                conflict_semantics="same business_key + same request_hash returns the original reference",
            ),
            lookup=LookupSupport(
                method="business_key",
                uniqueness="one external resource per business_key",
                terminal_detection="synchronous: result is terminal on return",
            ),
            **common,
        ),
        "booking.lookup": CapabilityDescriptor(
            capability_key="booking.lookup",
            support=SupportLevel.SUPPORTED,
            side_effect=SideEffect.READ,
            readable_fields=("external_reference", "status"),
            **common,
        ),
    }


class ExperienceReservationMock(Connector):
    """Fixed sessions with a resource capacity; see connectors/fixtures.py
    for the deterministic session IDs used by tests."""

    def __init__(self, sessions: dict[str, int]) -> None:
        super().__init__(_capabilities())
        self._capacity = dict(sessions)
        self._booked: dict[str, int] = {session_id: 0 for session_id in sessions}
        self._store = IdempotencyStore()

    def query_availability(self, session_id: str) -> dict[str, int]:
        """Backs the declared `availability.read` capability (SD §9: 場次
        資源). Returns the fixed capacity and current booked count for a
        known session; an unknown session reads as zero capacity rather
        than raising, mirroring how create_booking treats it."""
        self.ensure_capability("availability.read", SideEffect.READ)
        return {
            "session_id": session_id,
            "capacity": self._capacity.get(session_id, 0),
            "booked": self._booked.get(session_id, 0),
        }

    def create_booking(
        self,
        tenant_id: str,
        business_key: str,
        session_id: str,
        party_size: int,
        now: str,
    ) -> OperationResult:
        self.ensure_capability("booking.create", SideEffect.WRITE)
        if party_size <= 0:
            raise ValueError(f"party_size must be a positive integer, got {party_size}")
        payload = {"session_id": session_id, "party_size": party_size}
        req_hash = request_hash(payload)

        existing = self._store.get(tenant_id, ACCOUNT_ID, ENVIRONMENT, "booking.create", business_key)
        if existing is not None:
            record = self._store.reuse(tenant_id, ACCOUNT_ID, ENVIRONMENT, "booking.create", business_key, req_hash)
            return record.result

        remaining = self._capacity.get(session_id, 0) - self._booked.get(session_id, 0)
        if party_size > remaining:
            result: OperationResult = Failed(
                code="SESSION_CAPACITY_EXCEEDED",
                message=f"session '{session_id}' has {remaining} seats left, requested {party_size}",
                retryable=False,
                side_effect_disposition=SideEffectDisposition.NOT_APPLIED,
                evidence_refs=(f"experience-mock:capacity-check:{business_key}",),
                observed_at=now,
            )
            external_reference = f"exp-res-rejected-{tenant_id}:{business_key}"
        else:
            self._booked[session_id] = self._booked.get(session_id, 0) + party_size
            external_reference = f"exp-res-{tenant_id}:{business_key}"
            result = Succeeded(
                external_reference=external_reference,
                data={"session_id": session_id, "party_size": party_size},
                evidence_refs=(f"experience-mock:booking:{external_reference}",),
                observed_at=now,
            )

        self._store.record_dispatch(
            tenant_id, ACCOUNT_ID, ENVIRONMENT, "booking.create", business_key, req_hash, external_reference, result
        )
        return result

    def lookup_booking(self, tenant_id: str, business_key: str) -> OperationResult:
        self.ensure_capability("booking.lookup", SideEffect.READ)
        record = self._store.get(tenant_id, ACCOUNT_ID, ENVIRONMENT, "booking.create", business_key)
        if record is None:
            raise KeyError(business_key)
        return record.result
