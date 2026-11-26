"""PmsNightlyMock: room-night PMS with no publication capability.

SD connector-result-and-reconciliation.md §9: must model the room-night
inventory model, support cross-night availability queries, and explicitly
declare publication.update as UNSUPPORTED -- not merely absent from the
capability map, but declared and rejected. Must NOT be read as proof that
any real PMS lets this platform rewrite OTA prices (§9).
"""
from __future__ import annotations

from datetime import date, timedelta

from ..base import Connector
from ..idempotency import IdempotencyStore, request_hash
from ..types import (
    AuthorizationState,
    CapabilityDescriptor,
    ConnectorMode,
    Failed,
    IdempotencySupport,
    LookupSupport,
    OperationResult,
    SideEffect,
    SideEffectDisposition,
    Succeeded,
    SupportLevel,
)

ACCOUNT_ID = "mock-pms-account"
ENVIRONMENT = "sandbox"


def _capabilities() -> dict[str, CapabilityDescriptor]:
    return {
        "availability.read": CapabilityDescriptor(
            capability_key="availability.read",
            support=SupportLevel.SUPPORTED,
            authorization_state=AuthorizationState.ACTIVE,
            mode=ConnectorMode.SYNC,
            inventory_model="ROOM_NIGHT",
            side_effect=SideEffect.READ,
            readable_fields=("room_id", "night", "capacity", "booked"),
        ),
        "booking.create": CapabilityDescriptor(
            capability_key="booking.create",
            support=SupportLevel.SUPPORTED,
            authorization_state=AuthorizationState.ACTIVE,
            mode=ConnectorMode.SYNC,
            inventory_model="ROOM_NIGHT",
            side_effect=SideEffect.WRITE,
            writable_fields=("room_id", "check_in", "check_out"),
            idempotency=IdempotencySupport(
                supported=True,
                key_scope="tenant+account+environment+business_key",
                conflict_semantics="same business_key + same request_hash returns the original reference",
            ),
            lookup=LookupSupport(method="business_key", uniqueness="one external resource per business_key"),
        ),
        "booking.lookup": CapabilityDescriptor(
            capability_key="booking.lookup",
            support=SupportLevel.SUPPORTED,
            authorization_state=AuthorizationState.ACTIVE,
            mode=ConnectorMode.SYNC,
            inventory_model="ROOM_NIGHT",
            side_effect=SideEffect.READ,
            readable_fields=("external_reference", "status"),
        ),
        "publication.update": CapabilityDescriptor(
            capability_key="publication.update",
            support=SupportLevel.UNSUPPORTED,
            authorization_state=AuthorizationState.MISSING,
            mode=ConnectorMode.MANUAL,
            inventory_model="ROOM_NIGHT",
            side_effect=SideEffect.WRITE,
            restrictions=("this PMS has no channel/OTA publication API; SD §9",),
        ),
    }


def _nights(check_in: date, check_out: date) -> list[date]:
    nights = []
    current = check_in
    while current < check_out:
        nights.append(current)
        current += timedelta(days=1)
    return nights


class PmsNightlyMock(Connector):
    """Fixed per-room, per-night capacity; see connectors/fixtures.py."""

    def __init__(self, room_night_capacity: dict[tuple[str, date], int]) -> None:
        super().__init__(_capabilities())
        self._capacity = dict(room_night_capacity)
        self._booked: dict[tuple[str, date], int] = {}
        self._store = IdempotencyStore()
        self.publication_call_count = 0

    def query_availability(self, room_id: str, check_in: date, check_out: date) -> dict[date, int]:
        self.ensure_capability("availability.read", SideEffect.READ)
        result = {}
        for night in _nights(check_in, check_out):
            capacity = self._capacity.get((room_id, night), 0)
            booked = self._booked.get((room_id, night), 0)
            result[night] = capacity - booked
        return result

    def create_booking(
        self,
        tenant_id: str,
        business_key: str,
        room_id: str,
        check_in: date,
        check_out: date,
        now: str,
    ) -> OperationResult:
        self.ensure_capability("booking.create", SideEffect.WRITE)
        payload = {"room_id": room_id, "check_in": check_in.isoformat(), "check_out": check_out.isoformat()}
        req_hash = request_hash(payload)

        existing = self._store.get(tenant_id, ACCOUNT_ID, ENVIRONMENT, "booking.create", business_key)
        if existing is not None:
            record = self._store.reuse(tenant_id, ACCOUNT_ID, ENVIRONMENT, "booking.create", business_key, req_hash)
            return record.result

        nights = _nights(check_in, check_out)
        remaining = {
            night: self._capacity.get((room_id, night), 0) - self._booked.get((room_id, night), 0)
            for night in nights
        }
        sold_out_nights = [night for night, left in remaining.items() if left < 1]

        if sold_out_nights:
            result: OperationResult = Failed(
                code="ROOM_NIGHT_SOLD_OUT",
                message=f"room '{room_id}' has no inventory on {[n.isoformat() for n in sold_out_nights]}",
                retryable=False,
                side_effect_disposition=SideEffectDisposition.NOT_APPLIED,
                evidence_refs=(f"pms-mock:availability-check:{business_key}",),
                observed_at=now,
            )
            external_reference = f"pms-res-rejected-{business_key}"
        else:
            for night in nights:
                self._booked[(room_id, night)] = self._booked.get((room_id, night), 0) + 1
            external_reference = f"pms-res-{business_key}"
            result = Succeeded(
                external_reference=external_reference,
                data={"room_id": room_id, "check_in": check_in.isoformat(), "check_out": check_out.isoformat()},
                evidence_refs=(f"pms-mock:booking:{external_reference}",),
                observed_at=now,
            )

        self._store.record_dispatch(
            tenant_id, ACCOUNT_ID, ENVIRONMENT, "booking.create", business_key, req_hash, external_reference, result
        )
        return result

    def submit_publication(self, *args, **kwargs) -> OperationResult:
        """Always rejected before any state is touched (backlog ENG-04
        acceptance: PMS 未提供發布能力時在呼叫前拒絕)."""
        self.publication_call_count += 1
        self.ensure_capability("publication.update", SideEffect.WRITE)
        raise AssertionError("unreachable: ensure_capability must have raised")
