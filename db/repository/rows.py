"""Driver-boundary normalization for repository return values.

PostgreSQL UUID columns are returned as :class:`uuid.UUID` by psycopg.  The
repository boundary is also the API/worker boundary, so return canonical wire
values here rather than leaking driver objects into service JSON/hash logic.
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable


def normalize(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize(item) for item in value)
    return value


def row_as_dict(columns: Iterable[str], row: Iterable[Any]) -> dict[str, Any]:
    return {column: normalize(value) for column, value in zip(columns, row)}
