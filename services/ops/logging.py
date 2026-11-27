"""Credential/PII-redacting structured operation log envelope."""
from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {"authorization", "cookie", "credential", "password", "secret", "token", "api_key", "card_number", "raw_payload", "traveler_name", "email", "phone"}
ALLOWED_KEYS = {"tenant_id", "case_id", "work_id", "task_id", "attempt_id", "operation", "business_key", "environment", "correlation_id", "causation_id", "event", "outcome", "external_ref"}


def structured_operation_log(**fields: Any) -> dict[str, Any]:
    """Return a whitelisted, redacted log record suitable for an exporter."""
    record: dict[str, Any] = {}
    for key, value in fields.items():
        lowered = key.lower()
        if lowered in SENSITIVE_KEYS or any(part in lowered for part in ("password", "secret", "token", "credential")):
            record[key] = "[REDACTED]"
        elif key in ALLOWED_KEYS:
            record[key] = value
    return record
