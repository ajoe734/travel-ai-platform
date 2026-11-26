"""Connector-layer errors raised before any external I/O is attempted."""
from __future__ import annotations

from .types import CapabilityDescriptor


class CapabilityUnavailableError(Exception):
    """SD §2/§9, backlog ENG-04 acceptance: a capability that is not
    SUPPORTED + ACTIVE for the requested side effect must be rejected
    before dispatch, not surfaced as a failed provider call."""

    def __init__(self, capability_key: str, descriptor: CapabilityDescriptor) -> None:
        self.capability_key = capability_key
        self.descriptor = descriptor
        super().__init__(
            f"capability '{capability_key}' unavailable: "
            f"support={descriptor.support.value}, authorization_state={descriptor.authorization_state.value}"
        )


class BusinessKeyConflictError(Exception):
    """SD §6.1: the same business_key was requested again with a different
    request_hash. This is a new business request, not a retry, and must
    never silently overwrite or re-dispatch the original."""

    def __init__(self, business_key: str) -> None:
        self.business_key = business_key
        super().__init__(f"business_key '{business_key}' already dispatched with a different request payload")
