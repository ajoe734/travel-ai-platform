"""Canonical JSON encoding and payload hashing per docs/sd/authorization-and-approval.md §3.2.

canonicalization_version = travel-canonical-json-v1.

Rules implemented here (SD §3.2 steps 1-5):
  1. Reject NaN/Infinity and unpaired UTF-16 surrogates. Duplicate JSON object
     keys are rejected by ``parse_json_strict`` at the point raw request text
     is parsed (a Python dict built programmatically cannot itself carry a
     duplicate key, so the encoder does not need to re-check that case).
  2. ID/currency/timestamp fields are expected to already be in the schema's
     canonical string form by the time they reach this encoder (that
     normalization is the schema's job, not this module's).
  3. Object keys are sorted by ascending byte order; arrays keep the caller's
     order (callers sort manifest-shaped arrays by item_id before calling in,
     per SD §3.2 point 3 — this module does not reorder arrays itself).
  4. No insignificant whitespace; only '"', '\\' and U+0000-U+001F are
     escaped, using lowercase \\u00xx for control characters; '/' is never
     escaped; everything else is emitted as literal UTF-8.
  5. The hash input is the fixed UTF-8 prefix "travel-approval-v1\\n" followed
     by the canonical JSON bytes, hashed with SHA-256 and stored as lowercase
     hex.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

CANONICALIZATION_VERSION = "travel-canonical-json-v1"
_HASH_PREFIX = b"travel-approval-v1\n"


class CanonicalEncodingError(ValueError):
    """Raised when a value cannot be encoded under the canonical JSON rules."""


def parse_json_strict(text: str) -> Any:
    """Parse raw JSON text, rejecting NaN/Infinity and duplicate object keys.

    SD §3.2 step 1: "拒絕未知欄位、重複 JSON key、NaN、Infinity". Unknown-field
    rejection is the JSON Schema's job (additionalProperties: false); this
    function only owns the two checks a schema cannot express.
    """

    def _reject_constant(token: str) -> Any:
        raise CanonicalEncodingError(f"rejected non-finite JSON constant: {token}")

    def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise CanonicalEncodingError(f"duplicate JSON object key: {key!r}")
            seen[key] = value
        return seen

    return json.loads(
        text,
        parse_constant=_reject_constant,
        object_pairs_hook=_reject_duplicate_keys,
    )


def _check_no_unpaired_surrogate(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalEncodingError(f"unpaired UTF-16 surrogate in string: {exc}") from exc


def _encode_string(value: str) -> str:
    _check_no_unpaired_surrogate(value)
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif code <= 0x1F:
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise CanonicalEncodingError(
            "float is not a canonical JSON type here; business amounts and "
            "ratios must be carried as decimal strings (SD §3.1)"
        )
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0].encode("utf-8"))
        return "{" + ",".join(f"{_encode_string(k)}:{_encode(v)}" for k, v in items) + "}"
    raise CanonicalEncodingError(f"unsupported type for canonical encoding: {type(value)!r}")


def encode_canonical(value: Any) -> bytes:
    """Return the canonical JSON encoding of ``value`` as UTF-8 bytes."""
    return _encode(value).encode("utf-8")


def payload_hash(value: Any) -> str:
    """SHA-256 of the fixed prefix + canonical JSON bytes, as lowercase hex (SD §3.2 step 5)."""
    digest = hashlib.sha256(_HASH_PREFIX + encode_canonical(value))
    return digest.hexdigest()
