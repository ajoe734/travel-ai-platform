"""Pure input guards for the voice boundary.

These are deliberately dependency-free so the security and confirmation rules
can be exercised even where the PostgreSQL acceptance suite is unavailable.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qsl, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_SENSITIVE_PAYMENT_KEYS = {"card", "card_number", "pan", "cvv", "cvc", "security_code"}


def payment_link_is_safe(payment_link_ref: str) -> bool:
    parsed = urlparse(payment_link_ref)
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    fragment_keys = {key.lower() for key, _ in parse_qsl(parsed.fragment, keep_blank_values=True)}
    # Remove ordinary separators before detecting a PAN.  This deliberately
    # rejects payment data in URL fragments too, which never belongs in a link
    # handoff and is easy for query-only checks to miss.
    compact = re.sub(r"[\s-]", "", payment_link_ref)
    return bool(
        payment_link_ref
        and parsed.scheme in {"https", "payment-link"}
        and parsed.netloc
        and parsed.username is None
        and parsed.password is None
        and not (query_keys | fragment_keys) & _SENSITIVE_PAYMENT_KEYS
        and re.search(r"(?<!\d)\d{13,19}(?!\d)", compact) is None
    )


def confirmed_fields_are_valid(fields: object) -> bool:
    """Validate a spoken booking confirmation without inventing quote facts."""
    if not isinstance(fields, dict):
        return False
    required = {"service_date", "timezone", "party_size", "amount_minor_units", "currency"}
    if not required <= fields.keys() or set(fields) - required:
        return False
    try:
        date.fromisoformat(fields["service_date"])
        ZoneInfo(fields["timezone"])
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return False
    return (
        isinstance(fields["party_size"], int)
        and not isinstance(fields["party_size"], bool)
        and fields["party_size"] > 0
        and isinstance(fields["amount_minor_units"], int)
        and not isinstance(fields["amount_minor_units"], bool)
        and fields["amount_minor_units"] >= 0
        and isinstance(fields["currency"], str)
        and re.fullmatch(r"[A-Z]{3}", fields["currency"]) is not None
    )
