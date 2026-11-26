"""UTC-aware ISO-8601 timestamp comparison (ENG-03 Round 1 retrofit, finding F7).

Timestamps in this service are strings validated by the Timestamp schema
($ref common/identifiers.schema.json#/$defs/Timestamp, `format: date-time`).
Two instants that denote the same moment can be spelled differently
(fractional seconds, "Z" vs "+00:00"); comparing them with a bare string
``<=`` makes "06:00:00.500Z" look earlier than "06:00:00Z" when it is
actually later. Every expiry/effective-at comparison in this service must
go through ``is_at_or_before`` instead of comparing the raw strings.
"""
from __future__ import annotations

from datetime import datetime, timezone


def parse_timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp {value!r} is missing a UTC offset")
    return dt.astimezone(timezone.utc)


def is_at_or_before(a: str, b: str) -> bool:
    """Return True if instant ``a`` is at or before instant ``b``."""
    return parse_timestamp(a) <= parse_timestamp(b)
