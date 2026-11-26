"""Provider-neutral connector base.

A concrete adapter -- mock today, a real vendor integration later -- holds
a fixed CapabilityDescriptor map and must call ensure_capability() before
any external I/O for the capability it is about to use. This is what makes
backlog ENG-04's acceptance 'PMS 未提供發布能力時在呼叫前拒絕' true at the
SDK layer rather than by convention in each adapter.
"""
from __future__ import annotations

from typing import Mapping

from .errors import CapabilityUnavailableError
from .types import AuthorizationState, CapabilityDescriptor, ConnectorMode, SideEffect, SupportLevel


class Connector:
    def __init__(self, capabilities: Mapping[str, CapabilityDescriptor]) -> None:
        self._capabilities = dict(capabilities)

    def describe_capability(self, capability_key: str) -> CapabilityDescriptor:
        """Read-only capability lookup; never raises, so a caller can
        inspect support/authorization_state/restrictions before deciding
        whether to attempt the operation at all."""
        return self._capabilities.get(capability_key) or CapabilityDescriptor(
            capability_key=capability_key,
            support=SupportLevel.UNSUPPORTED,
            authorization_state=AuthorizationState.MISSING,
            mode=ConnectorMode.SYNC,
            inventory_model="UNKNOWN",
            side_effect=SideEffect.WRITE,
        )

    def ensure_capability(self, capability_key: str, side_effect: SideEffect) -> CapabilityDescriptor:
        """Raises CapabilityUnavailableError and performs no external call
        when the capability is not declared, not SUPPORTED, the account is
        not ACTIVE, or the declared side_effect does not match what the
        caller is about to do (a declared READ lookup must never be reused
        to smuggle in a WRITE, SD-C-10)."""
        descriptor = self.describe_capability(capability_key)
        if not descriptor.is_callable() or descriptor.side_effect is not side_effect:
            raise CapabilityUnavailableError(capability_key, descriptor)
        return descriptor
