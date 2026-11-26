"""OtaDelayedPublicationMock: asynchronous, delayed-review channel publish.

SD connector-result-and-reconciliation.md §9: must deliver a PENDING
accepted-for-review state, an UNKNOWN response-lost state, delayed readback
once the channel finishes review, and both an accept and a partial/reject
outcome. Must NOT be read as proof of any OTA's real review SLA or write
access (§9).

The mock's internal `_backend` dict stands in for "what actually happened
at the provider" -- it is updated at dispatch time, before the method
returns, exactly like a real provider's own database would already hold
the submission even if the HTTP response to this caller is lost in
transit. This is what lets reconcile() find the SAME external_reference
after a simulated response-lost UNKNOWN (backlog ENG-04 acceptance: 外部成
功後本地逾時仍可查回同一結果).

`_backend` is keyed by `(tenant_id, business_key)`, not business_key
alone: two tenants are free to pick the same business_key independently,
and one tenant's submission must never be visible to, or overwritten by,
another tenant's call against this same mock instance.
"""
from __future__ import annotations

from dataclasses import dataclass

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
    Pending,
    SideEffect,
    SideEffectDisposition,
    Succeeded,
    SupportLevel,
    Unknown,
)

ACCOUNT_ID = "mock-ota-account"
ENVIRONMENT = "sandbox"


def _capabilities() -> dict[str, CapabilityDescriptor]:
    return {
        "publication.update": CapabilityDescriptor(
            capability_key="publication.update",
            support=SupportLevel.SUPPORTED,
            authorization_state=AuthorizationState.ACTIVE,
            merchant_consent=MerchantConsentState.GRANTED,
            operational_availability=OperationalAvailability.AVAILABLE,
            mode=ConnectorMode.ASYNC,
            inventory_model="CHANNEL_OFFER",
            side_effect=SideEffect.WRITE,
            writable_fields=("offer_id", "channel", "service_version"),
            idempotency=IdempotencySupport(
                supported=True,
                key_scope="tenant+account+environment+business_key",
                conflict_semantics="same business_key + same request_hash returns the original submission",
            ),
            lookup=LookupSupport(
                method="business_key",
                uniqueness="one external submission per business_key",
                visibility_delay="review is asynchronous; terminal state only known after advance_review",
                terminal_detection="reconcile() against stored business_key, never a caller-supplied URL/ID",
            ),
        ),
        "publication.read": CapabilityDescriptor(
            capability_key="publication.read",
            support=SupportLevel.SUPPORTED,
            authorization_state=AuthorizationState.ACTIVE,
            merchant_consent=MerchantConsentState.GRANTED,
            operational_availability=OperationalAvailability.AVAILABLE,
            mode=ConnectorMode.SYNC,
            inventory_model="CHANNEL_OFFER",
            side_effect=SideEffect.READ,
            readable_fields=("observed_version", "observed_sales_state"),
        ),
    }


@dataclass
class _BackendRecord:
    external_reference: str
    status: str  # SUBMITTED | LIVE_VERIFIED | REJECTED
    channel: str
    service_version: str


def _reconciliation_token(tenant_id: str, business_key: str) -> str:
    """The opaque reconciliation context this mock hands back to the
    caller: tenant-scoped so two tenants submitting the same business_key
    never collide on the token that reconcile() later validates against
    (backlog ENG-04 F1 remediation)."""
    return f"recon-{tenant_id}:{business_key}"


class OtaDelayedPublicationMock(Connector):
    def __init__(self) -> None:
        super().__init__(_capabilities())
        self._backend: dict[tuple[str, str], _BackendRecord] = {}
        self._store = IdempotencyStore()

    def submit_publication(
        self,
        tenant_id: str,
        business_key: str,
        channel: str,
        service_version: str,
        now: str,
        simulate_response_lost: bool = False,
    ) -> OperationResult:
        self.ensure_capability("publication.update", SideEffect.WRITE)
        payload = {"channel": channel, "service_version": service_version}
        req_hash = request_hash(payload)

        existing = self._store.get(tenant_id, ACCOUNT_ID, ENVIRONMENT, "publication.update", business_key)
        if existing is not None:
            record = self._store.reuse(
                tenant_id, ACCOUNT_ID, ENVIRONMENT, "publication.update", business_key, req_hash
            )
            return record.result

        # Tenant-scoped: two tenants may independently pick the same
        # business_key, and this record -- and the external_reference
        # handed back for it -- must never be shared or overwritten across
        # tenants (backlog ENG-04 F1 remediation).
        external_reference = f"ota-pub-{tenant_id}:{business_key}"
        self._backend[(tenant_id, business_key)] = _BackendRecord(
            external_reference=external_reference, status="SUBMITTED", channel=channel, service_version=service_version
        )

        if simulate_response_lost:
            # The provider already accepted the submission (above); only
            # this caller's transport to it was lost. SD §4: an ambiguous
            # transport failure must be UNKNOWN, never FAILED/NOT_APPLIED.
            result: OperationResult = Unknown(
                reconciliation_token=_reconciliation_token(tenant_id, business_key),
                reason_code="RESPONSE_LOST",
                dispatch_evidence_ref=f"ota-mock:dispatch-intent:{business_key}",
                observed_at=now,
            )
        else:
            result = Pending(
                external_reference=external_reference,
                reconciliation_token=_reconciliation_token(tenant_id, business_key),
                pending_reason="WAITING_CHANNEL_REVIEW",
                evidence_refs=(f"ota-mock:submission:{external_reference}",),
                observed_at=now,
            )

        self._store.record_dispatch(
            tenant_id, ACCOUNT_ID, ENVIRONMENT, "publication.update", business_key, req_hash, external_reference, result
        )
        return result

    def advance_review(self, tenant_id: str, business_key: str, outcome: str) -> None:
        """Test/ops helper standing in for the channel's own review
        finishing -- the asynchronous equivalent of a webhook or scheduled
        check landing (SD §5/§7). outcome is 'LIVE_VERIFIED' or
        'REJECTED'. tenant_id is required so this never advances another
        tenant's submission under the same business_key."""
        if outcome not in ("LIVE_VERIFIED", "REJECTED"):
            raise ValueError(f"unknown review outcome: {outcome}")
        record = self._backend.get((tenant_id, business_key))
        if record is None:
            raise KeyError(business_key)
        record.status = outcome

    def reconcile(self, tenant_id: str, business_key: str, reconciliation_token: str, now: str) -> OperationResult:
        """Looks up by the persisted tenant_id/business_key only -- never
        an arbitrary caller-supplied external URL/ID (SD §5.1). The
        caller-supplied reconciliation_token must match the one this mock
        issued for this exact tenant/business_key context; a mismatch
        means the caller is reconciling against the wrong dispatch and is
        a local validation error, not a provider outcome.

        SUCCEEDED and FAILED both close out the stored result; PENDING
        leaves it open for a later reconcile (backlog ENG-04 acceptance:
        查核回 SUCCEEDED 或 FAILED 均有收尾). A lookup miss -- the
        dispatch is not yet visible to this reconcile call -- returns
        UNKNOWN rather than raising: SD-C-03 requires a not-found read to
        be preserved as UNKNOWN for backoff-and-recheck, never surfaced as
        a crash, a release, or a redo.
        """
        self.ensure_capability("publication.read", SideEffect.READ)
        expected_token = _reconciliation_token(tenant_id, business_key)
        if reconciliation_token != expected_token:
            raise ValueError(
                f"reconciliation_token does not match the persisted tenant/business_key context for '{business_key}'"
            )

        backend_record = self._backend.get((tenant_id, business_key))
        if backend_record is None:
            # SD-C-03: a lookup miss alone is never grounds to fail,
            # release the lease, or redo the dispatch.
            return Unknown(
                reconciliation_token=reconciliation_token,
                reason_code="NOT_FOUND_RETRY",
                dispatch_evidence_ref=f"ota-mock:lookup-miss:{business_key}",
                observed_at=now,
            )

        if backend_record.status == "SUBMITTED":
            result: OperationResult = Pending(
                external_reference=backend_record.external_reference,
                reconciliation_token=reconciliation_token,
                pending_reason="WAITING_CHANNEL_REVIEW",
                evidence_refs=(f"ota-mock:submission:{backend_record.external_reference}",),
                observed_at=now,
            )
        elif backend_record.status == "LIVE_VERIFIED":
            result = Succeeded(
                external_reference=backend_record.external_reference,
                data={"channel": backend_record.channel, "observed_sales_state": "LIVE_VERIFIED"},
                evidence_refs=(f"ota-mock:review-evidence:{backend_record.external_reference}",),
                observed_at=now,
                source_revision=backend_record.service_version,
            )
        else:  # REJECTED
            result = Failed(
                code="CHANNEL_REJECTED",
                message=f"channel '{backend_record.channel}' rejected submission for '{business_key}'",
                retryable=False,
                side_effect_disposition=SideEffectDisposition.NOT_APPLIED,
                evidence_refs=(f"ota-mock:review-evidence:{backend_record.external_reference}",),
                observed_at=now,
            )

        self._store.update_result(tenant_id, ACCOUNT_ID, ENVIRONMENT, "publication.update", business_key, result)
        return result
