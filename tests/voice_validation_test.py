"""Dependency-free ENG-10 guards; DB state transitions stay in tests/db."""
from __future__ import annotations

import json
import pathlib
import unittest

from services.voice.validation import confirmed_fields_are_valid, payment_link_is_safe


class VoiceValidationTest(unittest.TestCase):
    def test_confirmed_turn_requires_date_iana_timezone_party_and_amount(self) -> None:
        valid = {"service_date": "2026-12-01", "timezone": "Asia/Taipei", "party_size": 2, "amount_minor_units": 1800, "currency": "TWD"}
        self.assertTrue(confirmed_fields_are_valid(valid))
        for field, value in (("timezone", "Taipei"), ("party_size", 0), ("amount_minor_units", -1), ("currency", "twd")):
            invalid = dict(valid); invalid[field] = value
            self.assertFalse(confirmed_fields_are_valid(invalid))

    def test_payment_link_rejects_url_bypass_forms(self) -> None:
        self.assertTrue(payment_link_is_safe("https://pay.example.com/checkout/token"))
        for value in (
            "https://pay.example.com/checkout?ref=4111-1111-1111-1111",
            "https://pay.example.com/checkout#pan=4111-1111-1111-1111&cvv=123",
            "https://pay.example.com/checkout?security_code=123",
            "https://:secret@pay.example.com/checkout",
            "https:///no-host",
        ):
            self.assertFalse(payment_link_is_safe(value), value)

    def test_voice_error_codes_are_unique_and_registered(self) -> None:
        registry = json.loads((pathlib.Path(__file__).parents[1] / "specs/domain/error-codes.json").read_text())
        codes = [entry["code"] for entry in registry["codes"]]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue({"VOICE_SESSION_NOT_FOUND", "CASE_RESUME_VERIFICATION_REQUIRED", "TRANSFER_DESTINATION_REJECTED", "PAYMENT_HANDOFF_OWNERSHIP_REJECTED"} <= set(codes))
