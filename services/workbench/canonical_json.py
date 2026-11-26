"""Canonical JSON encoding for DecisionRequest display payloads.

Source: docs/sd/authorization-and-approval.md §3.2 ("Canonical payload v1").
This module follows that algorithm's shape -- sorted object keys by UTF-8
byte order, no insignificant whitespace, lowercase true/false/null, control
characters escaped as \\u00xx, floats prohibited -- closely enough to make
payload_hash a meaningful staleness check for a workbench decision card
(specs/domain/decision-request.schema.json requires
canonicalization_version == "travel-canonical-json-v1").

It is NOT the cross-language, test-vector-verified canonical encoder SD-A-09
calls for, and it does NOT use the ApprovalRecord hash prefix
("travel-approval-v1\\n") -- that pipeline belongs to ApprovalRecord /
ExecutionAuthorization and is ENG-03 scope. This module's prefix is scoped to
this workbench's own DecisionRequest display payload only, so the two hashes
can never be mistaken for each other even though both schemas currently
declare the same canonicalization_version label.
"""
from __future__ import annotations

import hashlib

CANONICALIZATION_VERSION = "travel-canonical-json-v1"
_DECISION_HASH_PREFIX = b"travel-workbench-decision-v1\n"


def _encode_string(value: str) -> str:
    out = ['"']
    for ch in value:
        code_point = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif code_point < 0x20:
            out.append(f"\\u{code_point:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _encode_value(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, float):
        raise ValueError("canonical payloads must not contain float values (SD §3.2)")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ",".join(_encode_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0].encode("utf-8"))
        return "{" + ",".join(_encode_string(k) + ":" + _encode_value(v) for k, v in items) + "}"
    raise TypeError(f"unsupported canonical value type: {type(value)!r}")


def canonical_bytes(payload: dict) -> bytes:
    return _encode_value(payload).encode("utf-8")


def decision_payload_hash(payload: dict) -> str:
    """SHA-256 hex digest of this workbench's decision display payload, used
    to detect AUTHORIZATION_STALE when content changes between showing a
    decision card and the merchant submitting a decision on it."""
    return hashlib.sha256(_DECISION_HASH_PREFIX + canonical_bytes(payload)).hexdigest()


def sha256_hex(payload: dict) -> str:
    """Plain canonical-bytes hash with no prefix, used for ExecutionTask
    request_hash (SD work-execution-contract.md §2): same business_key with
    a different request_hash must be rejected as a new business request."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
