"""Typed core contracts for the connector SDK.

Source: docs/sd/connector-result-and-reconciliation.md §1-3. Three layers
must never collapse into one: CapabilityDescriptor (can this account do
this, at all), OperationResult (what happened on this one call) and the
domain's own state machine (not modelled here; see specs/domain/*). An
OperationResult of SUCCEEDED is this connector's belief; a domain verifier
checking the Work/task postcondition is a separate, later step
(connector-result-and-reconciliation.md §1) and is out of this module's
scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Union


class SupportLevel(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNVERIFIED = "UNVERIFIED"


class AuthorizationState(str, Enum):
    ACTIVE = "ACTIVE"
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ConnectorMode(str, Enum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"
    MANUAL = "MANUAL"
    CONTROLLED_BROWSER = "CONTROLLED_BROWSER"


class SideEffect(str, Enum):
    READ = "READ"
    WRITE = "WRITE"


class SideEffectDisposition(str, Enum):
    NOT_APPLIED = "NOT_APPLIED"
    REVERSED = "REVERSED"


@dataclass(frozen=True)
class IdempotencySupport:
    """SD §2 idempotency column."""

    supported: bool
    key_scope: str | None = None
    retention: str | None = None
    conflict_semantics: str | None = None


@dataclass(frozen=True)
class LookupSupport:
    """SD §2 lookup column."""

    method: str
    uniqueness: str
    visibility_delay: str | None = None
    terminal_detection: str | None = None


@dataclass(frozen=True)
class VersionControlSupport:
    """SD §2 version_control column."""

    supported: bool
    conflict_risk_note: str | None = None


@dataclass(frozen=True)
class CapabilityVerification:
    """SD §2 verification column. account_id/environment are this
    platform's connector_account_id, never a real vendor credential."""

    account_id: str
    environment: str
    api_product_version: str
    checked_at: str
    sandbox_evidence: str | None = None
    production_enabled: bool = False


@dataclass(frozen=True)
class CapabilityDescriptor:
    """SD connector-result-and-reconciliation.md §2.

    Identified by (tenant_id, connector_account_id, environment,
    capability_key, contract_version) at the persistence layer (ENG-02
    scope); this in-process value object carries the fields for one such
    row.
    """

    capability_key: str
    support: SupportLevel
    authorization_state: AuthorizationState
    mode: ConnectorMode
    inventory_model: str
    side_effect: SideEffect
    writable_fields: tuple[str, ...] = ()
    readable_fields: tuple[str, ...] = ()
    idempotency: IdempotencySupport | None = None
    lookup: LookupSupport | None = None
    version_control: VersionControlSupport | None = None
    restrictions: tuple[str, ...] = ()
    verification: CapabilityVerification | None = None

    def is_callable(self) -> bool:
        """SUPPORTED is necessary but not sufficient; the account must also
        be ACTIVE before any write is attempted (SD §2, §9)."""
        return self.support is SupportLevel.SUPPORTED and self.authorization_state is AuthorizationState.ACTIVE


@dataclass(frozen=True)
class Succeeded:
    external_reference: str
    data: Any
    evidence_refs: tuple[str, ...]
    observed_at: str
    source_revision: str | None = None
    status: Literal["SUCCEEDED"] = "SUCCEEDED"

    def __post_init__(self) -> None:
        if not self.evidence_refs:
            raise ValueError("SUCCEEDED must carry at least one evidence_ref (SD §3)")


@dataclass(frozen=True)
class Pending:
    external_reference: str
    reconciliation_token: str
    pending_reason: str
    evidence_refs: tuple[str, ...]
    observed_at: str
    next_check_at: str | None = None
    status: Literal["PENDING"] = "PENDING"


@dataclass(frozen=True)
class Unknown:
    reconciliation_token: str
    reason_code: str
    dispatch_evidence_ref: str
    observed_at: str
    external_reference: str | None = None
    status: Literal["UNKNOWN"] = "UNKNOWN"


@dataclass(frozen=True)
class Failed:
    code: str
    message: str
    retryable: bool
    side_effect_disposition: SideEffectDisposition
    evidence_refs: tuple[str, ...]
    observed_at: str
    compensation_ref: str | None = None
    status: Literal["FAILED"] = "FAILED"

    def __post_init__(self) -> None:
        if self.side_effect_disposition is SideEffectDisposition.REVERSED and not self.compensation_ref:
            raise ValueError(
                "REVERSED must carry compensation_ref: a verified compensation, not just the "
                "original effect (SD §3)"
            )


OperationResult = Union[Succeeded, Pending, Unknown, Failed]
