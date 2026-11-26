#!/usr/bin/env python3
"""ENG-03 tests for services/authorization/*.

Exercises the real AuthorizationService + InMemoryAuthorizationRepository
against the real specs/domain/*.schema.json contracts (via
services/authorization/schema_validation.py) and the SD
authorization-and-approval.md negative acceptance table (§8, SD-A-01..SD-A-08,
SD-A-10). SD-A-09's cross-language canonicalization vectors and SD-A-11/12
(break-glass access, refund/credit reservations) are ENG-07/ENG-10/voice-entry
scope and are not covered here.

This is a pure in-process unittest suite — no database, HTTP server or
external connector. Persistence is services/authorization/repository.py's
InMemoryAuthorizationRepository, an explicit stand-in for ENG-02.
"""
from __future__ import annotations

import itertools
import unittest
import unicodedata

from services.authorization import canonical_json
from services.authorization.errors import AuthorizationError
from services.authorization.repository import InMemoryAuthorizationRepository
from services.authorization.service import AuthorizationService

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_TENANT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _actor(kind: str, actor_id: str) -> dict:
    return {"actor_kind": kind, "actor_id": actor_id}


def _ref(tenant_id: str, id_: str) -> dict:
    return {"tenant_id": tenant_id, "id": id_}


def _ids() -> itertools.count:
    return itertools.count(1)


_SEQ = _ids()


def _id_factory() -> str:
    n = next(_SEQ)
    return f"00000000-0000-4000-8000-{n:012d}"


def new_service() -> AuthorizationService:
    return AuthorizationService(InMemoryAuthorizationRepository(), id_factory=_id_factory)


def base_display_payload(**overrides) -> dict:
    payload = {
        "schema_version": "1.0",
        "canonicalization_version": "travel-canonical-json-v1",
        "tenant_id": TENANT,
        "purpose": "RESCHEDULE_BOOKING",
        "target_type": "QUOTE",
        "target_id": _ref(TENANT, "00000000-0000-4000-8000-000000000901"),
        "target_revision": 2,
        "work_id": _ref(TENANT, "00000000-0000-4000-8000-000000000102"),
        "operation": "booking.reschedule",
        "service_or_policy_version": "reschedule-policy-v1",
        "expires_at": "2026-11-27T05:10:00Z",
        "data_purpose": "fulfil the customer's reschedule request",
        "manifest_items": ["manifest-item-1"],
        "customer_impact": "date changes from 2026-12-01 to 2026-12-05",
        "required_consent_refs": [],
    }
    payload.update(overrides)
    return payload


def create_pending_decision(svc: AuthorizationService, **overrides):
    kwargs = dict(
        tenant_id=TENANT,
        work_id=_ref(TENANT, "00000000-0000-4000-8000-000000000102"),
        decision_type="RESCHEDULE_QUOTE_CONFIRMATION",
        options=[
            {"option_id": "accept_new_quote", "description": "接受新日期與新報價"},
            {"option_id": "keep_original", "description": "維持原日期，不改期"},
        ],
        display_payload=base_display_payload(),
        target_revision=3,
        expires_at="2026-11-27T10:00:00Z",
        requested_role="CUSTOMER",
        created_at="2026-11-26T05:00:00Z",
    )
    kwargs.update(overrides)
    return svc.create_decision(**kwargs)


def approve_happy_path(svc: AuthorizationService, decision: dict, nonce_id: str, **overrides) -> dict:
    kwargs = dict(
        tenant_id=TENANT,
        decision_id=decision["id"],
        expected_revision=decision["revision"],
        selected_option_id="accept_new_quote",
        nonce_id=nonce_id,
        approved_by=_actor("CUSTOMER", "00000000-0000-4000-8000-0000000000c1"),
        verified_actor_ref="voice-confirmation:session-998",
        scope_manifest=[{"item_id": "manifest-item-1", "operation": "booking.reschedule"}],
        approved_at="2026-11-26T05:10:00Z",
        idempotency_key="idem-approve-1",
    )
    kwargs.update(overrides)
    return svc.approve_decision(**kwargs)


class CanonicalJsonTestVectors(unittest.TestCase):
    """SD §3.2 "最低測試向量" — the 8 required vectors, minus the cross-language
    (SD-A-09) half, which needs a second-language implementation ENG-03 does
    not add."""

    def test_object_key_reordering_is_the_same_hash(self):
        a = {"b": 1, "a": {"y": 2, "x": 1}}
        b = {"a": {"x": 1, "y": 2}, "b": 1}
        self.assertEqual(canonical_json.payload_hash(a), canonical_json.payload_hash(b))

    def test_array_reordering_is_a_different_hash(self):
        a = {"items": ["x", "y", "z"]}
        b = {"items": ["z", "y", "x"]}
        self.assertNotEqual(canonical_json.payload_hash(a), canonical_json.payload_hash(b))

    def test_amount_change_is_a_different_hash(self):
        a = {"amount_minor_units": "1000", "currency": "TWD"}
        b = {"amount_minor_units": "1001", "currency": "TWD"}
        self.assertNotEqual(canonical_json.payload_hash(a), canonical_json.payload_hash(b))

    def test_null_versus_missing_field_is_a_different_hash(self):
        a = {"note": None}
        b = {}
        self.assertNotEqual(canonical_json.payload_hash(a), canonical_json.payload_hash(b))

    def test_unicode_normalization_is_not_silently_collapsed(self):
        nfc = unicodedata.normalize("NFC", "café")
        nfd = unicodedata.normalize("NFD", "café")
        self.assertNotEqual(nfc, nfd, "fixture must actually exercise two distinct code point sequences")
        self.assertNotEqual(
            canonical_json.payload_hash({"s": nfc}),
            canonical_json.payload_hash({"s": nfd}),
            "canonicalization must not normalize Unicode and silently collide two distinct inputs",
        )

    def test_same_amount_different_currency_is_a_different_hash(self):
        a = {"amount_minor_units": "1000", "currency": "TWD"}
        b = {"amount_minor_units": "1000", "currency": "USD"}
        self.assertNotEqual(canonical_json.payload_hash(a), canonical_json.payload_hash(b))

    def test_different_tenant_or_target_is_a_different_hash(self):
        a = {"tenant_id": TENANT, "target_id": "x"}
        b = {"tenant_id": OTHER_TENANT, "target_id": "x"}
        c = {"tenant_id": TENANT, "target_id": "y"}
        self.assertNotEqual(canonical_json.payload_hash(a), canonical_json.payload_hash(b))
        self.assertNotEqual(canonical_json.payload_hash(a), canonical_json.payload_hash(c))

    def test_amount_beyond_javascript_safe_integer_is_exact(self):
        huge = "90071992547409910000000001"
        self.assertNotIn("e", canonical_json.encode_canonical({"amount_minor_units": huge}).decode().lower())
        encoded = canonical_json.encode_canonical({"amount_minor_units": huge}).decode()
        self.assertIn(huge, encoded)

    def test_rejects_nan_and_infinity_via_strict_parse(self):
        with self.assertRaises(canonical_json.CanonicalEncodingError):
            canonical_json.parse_json_strict("{\"x\": NaN}")
        with self.assertRaises(canonical_json.CanonicalEncodingError):
            canonical_json.parse_json_strict("{\"x\": Infinity}")

    def test_rejects_duplicate_object_keys_via_strict_parse(self):
        with self.assertRaises(canonical_json.CanonicalEncodingError):
            canonical_json.parse_json_strict('{"x": 1, "x": 2}')

    def test_float_is_rejected_not_silently_encoded(self):
        with self.assertRaises(canonical_json.CanonicalEncodingError):
            canonical_json.encode_canonical({"ratio": 0.5})

    def test_control_characters_use_lowercase_u00xx_not_short_escapes(self):
        encoded = canonical_json.encode_canonical({"s": "a\nb\tc"}).decode()
        self.assertIn("\\u000a", encoded)
        self.assertIn("\\u0009", encoded)
        self.assertNotIn("\\n", encoded)

    def test_forward_slash_is_not_escaped(self):
        encoded = canonical_json.encode_canonical({"s": "a/b"}).decode()
        self.assertIn("a/b", encoded)
        self.assertNotIn("a\\/b", encoded)


class DecisionLifecycleTests(unittest.TestCase):
    def test_create_decision_hashes_the_exact_display_payload(self):
        svc = new_service()
        payload = base_display_payload()
        decision, nonce_id = create_pending_decision(svc, display_payload=payload)
        self.assertEqual(decision["status"], "PENDING")
        self.assertEqual(decision["revision"], 1)
        self.assertEqual(decision["payload_hash"], canonical_json.payload_hash(payload))
        self.assertTrue(nonce_id)

    def test_cross_tenant_display_payload_is_rejected(self):
        svc = new_service()
        with self.assertRaises(AuthorizationError) as ctx:
            create_pending_decision(svc, display_payload=base_display_payload(tenant_id=OTHER_TENANT))
        self.assertEqual(ctx.exception.code, "CROSS_TENANT_REFERENCE_REJECTED")

    def test_propose_revision_supersedes_the_old_pending_revision(self):
        svc = new_service()
        decision, _nonce = create_pending_decision(svc)
        new_decision, _new_nonce = svc.propose_revision(
            tenant_id=TENANT,
            decision_id=decision["id"],
            expected_revision=1,
            decision_type=decision["decision_type"],
            options=decision["options"],
            display_payload=base_display_payload(customer_impact="changed to 2026-12-10"),
            target_revision=decision["target_revision"],
            expires_at=decision["expires_at"],
            requested_role=decision["requested_role"],
            created_at="2026-11-26T05:05:00Z",
        )
        self.assertEqual(new_decision["revision"], 2)
        self.assertEqual(new_decision["status"], "PENDING")
        old = svc.repository.get_decision_revision(TENANT, decision["id"], 1)
        self.assertEqual(old["status"], "SUPERSEDED")

    def test_old_revision_can_never_be_approved_once_superseded(self):
        # SD-A-02: card displayed version A, then content changes to B before approval.
        svc = new_service()
        decision, old_nonce = create_pending_decision(svc)
        svc.propose_revision(
            tenant_id=TENANT,
            decision_id=decision["id"],
            expected_revision=1,
            decision_type=decision["decision_type"],
            options=decision["options"],
            display_payload=base_display_payload(customer_impact="price changed"),
            target_revision=decision["target_revision"],
            expires_at=decision["expires_at"],
            requested_role=decision["requested_role"],
            created_at="2026-11-26T05:05:00Z",
        )
        with self.assertRaises(AuthorizationError) as ctx:
            approve_happy_path(svc, decision, old_nonce)
        self.assertEqual(ctx.exception.code, "AUTHORIZATION_STALE")

    def test_approve_without_a_real_confirmation_nonce_is_rejected(self):
        # SD-A-01: model passes accepted=true / a self-made approval_id string.
        svc = new_service()
        decision, _real_nonce = create_pending_decision(svc)
        with self.assertRaises(AuthorizationError) as ctx:
            approve_happy_path(svc, decision, nonce_id="model-made-up-nonce")
        self.assertEqual(ctx.exception.code, "UNVERIFIED_APPROVAL_REJECTED")

    def test_approve_consumes_the_nonce_so_it_cannot_be_replayed_for_a_second_approval(self):
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        approve_happy_path(svc, decision, nonce_id)
        decision2, nonce_id2 = create_pending_decision(svc)
        with self.assertRaises(AuthorizationError) as ctx:
            approve_happy_path(svc, decision2, nonce_id, idempotency_key="idem-approve-2")
        self.assertEqual(ctx.exception.code, "UNVERIFIED_APPROVAL_REJECTED")

    def test_approve_wrong_role_is_rejected(self):
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        with self.assertRaises(AuthorizationError) as ctx:
            approve_happy_path(svc, decision, nonce_id, approved_by=_actor("EMPLOYEE", "00000000-0000-4000-8000-0000000000e1"))
        self.assertEqual(ctx.exception.code, "ACTOR_ROLE_MISMATCH")

    def test_reject_decision_records_reason_and_leaves_work_next_step_open(self):
        svc = new_service()
        decision, _nonce = create_pending_decision(svc)
        rejected = svc.reject_decision(
            tenant_id=TENANT,
            decision_id=decision["id"],
            expected_revision=1,
            selected_option_id="keep_original",
            rejected_by=_actor("CUSTOMER", "00000000-0000-4000-8000-0000000000c1"),
            reason="customer prefers original date",
            idempotency_key="idem-reject-1",
        )
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["selected_option_id"], "keep_original")

    def test_reject_already_resolved_decision_is_conflict(self):
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        approve_happy_path(svc, decision, nonce_id)
        with self.assertRaises(AuthorizationError) as ctx:
            svc.reject_decision(
                tenant_id=TENANT,
                decision_id=decision["id"],
                expected_revision=1,
                selected_option_id="keep_original",
                rejected_by=_actor("CUSTOMER", "00000000-0000-4000-8000-0000000000c1"),
                reason="too late",
                idempotency_key="idem-reject-2",
            )
        self.assertEqual(ctx.exception.code, "VERSION_CONFLICT")

    def test_expire_decisions_transitions_past_deadline_pending_rows(self):
        svc = new_service()
        decision, _nonce = create_pending_decision(svc, expires_at="2026-11-26T06:00:00Z")
        expired = svc.expire_decisions(tenant_id=TENANT, now="2026-11-26T07:00:00Z")
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["id"], decision["id"])
        self.assertEqual(expired[0]["status"], "EXPIRED")


class ApprovalIdempotencyTests(unittest.TestCase):
    def test_same_key_same_payload_replay_returns_the_same_approval(self):
        # SD-A-03
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        first = approve_happy_path(svc, decision, nonce_id)
        second = svc.approve_decision(
            tenant_id=TENANT,
            decision_id=decision["id"],
            expected_revision=1,
            selected_option_id="accept_new_quote",
            nonce_id="an-already-consumed-or-irrelevant-nonce-for-replay",
            approved_by=_actor("CUSTOMER", "00000000-0000-4000-8000-0000000000c1"),
            verified_actor_ref="voice-confirmation:session-998",
            scope_manifest=[{"item_id": "manifest-item-1", "operation": "booking.reschedule"}],
            approved_at="2026-11-26T05:10:00Z",
            idempotency_key="idem-approve-1",
        )
        self.assertEqual(first["id"], second["id"])

    def test_same_key_different_amount_is_idempotency_conflict(self):
        # SD-A-04
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        approve_happy_path(svc, decision, nonce_id)
        with self.assertRaises(AuthorizationError) as ctx:
            svc.approve_decision(
                tenant_id=TENANT,
                decision_id=decision["id"],
                expected_revision=1,
                selected_option_id="accept_new_quote",
                nonce_id="irrelevant",
                approved_by=_actor("CUSTOMER", "00000000-0000-4000-8000-0000000000c1"),
                verified_actor_ref="voice-confirmation:session-998",
                scope_manifest=[
                    {"item_id": "manifest-item-1", "operation": "booking.reschedule"},
                    {"item_id": "manifest-item-2", "operation": "booking.create"},
                ],
                approved_at="2026-11-26T05:10:00Z",
                idempotency_key="idem-approve-1",
            )
        self.assertEqual(ctx.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_duplicate_approval_under_a_different_idempotency_key_is_conflict(self):
        # backlog ENG-03 acceptance "重複批准都有明確結果": UNIQUE(tenant_id, decision_id,
        # reviewed_revision) must hold even when the second attempt does not reuse the
        # first Idempotency-Key at all (so the SD-A-03 replay path never engages).
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        first = approve_happy_path(svc, decision, nonce_id)
        with self.assertRaises(AuthorizationError) as ctx:
            svc.approve_decision(
                tenant_id=TENANT,
                decision_id=decision["id"],
                expected_revision=1,
                selected_option_id="accept_new_quote",
                nonce_id="irrelevant",
                approved_by=_actor("CUSTOMER", "00000000-0000-4000-8000-0000000000c1"),
                verified_actor_ref="voice-confirmation:session-998",
                scope_manifest=[{"item_id": "manifest-item-1", "operation": "booking.reschedule"}],
                approved_at="2026-11-26T05:11:00Z",
                idempotency_key="a-completely-different-idempotency-key",
            )
        self.assertEqual(ctx.exception.code, "VERSION_CONFLICT")
        # the first approval is untouched and still the only one on record.
        self.assertEqual(svc.repository.get_approval(TENANT, first["id"])["id"], first["id"])


class ExecutionAuthorizationTests(unittest.TestCase):
    def _manifest(self):
        return [{"item_id": "manifest-item-1", "operation": "booking.reschedule"}]

    def test_policy_covered_work_issues_authorization_without_any_decision(self):
        # SD-A-10 / backlog ENG-03: existing policy coverage must not add manual work.
        svc = new_service()
        svc.repository.put_grant(
            {
                "tenant_id": TENANT,
                "id": "00000000-0000-4000-8000-00000000c001",
                "capabilities": ["booking.reschedule"],
                "expiry": "2027-01-01T00:00:00Z",
                "revoked": False,
                "budget_remaining": 2,
            }
        )
        authorization = svc.try_issue_policy_covered_authorization(
            tenant_id=TENANT,
            work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a001"),
            root_business_key="booking:reschedule:quote-1",
            capabilities=["booking.reschedule"],
            manifest=self._manifest(),
            issued_at="2026-11-26T06:00:00Z",
            now="2026-11-26T06:00:00Z",
        )
        self.assertIsNotNone(authorization)
        self.assertEqual(authorization["grant_refs"], [_ref(TENANT, "00000000-0000-4000-8000-00000000c001")])
        self.assertNotIn("approval_refs", authorization)

    def test_no_covering_grant_falls_back_to_none_not_an_exception(self):
        svc = new_service()
        authorization = svc.try_issue_policy_covered_authorization(
            tenant_id=TENANT,
            work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a001"),
            root_business_key="booking:reschedule:quote-1",
            capabilities=["booking.reschedule"],
            manifest=self._manifest(),
            issued_at="2026-11-26T06:00:00Z",
            now="2026-11-26T06:00:00Z",
        )
        self.assertIsNone(authorization)

    def test_each_work_rechecks_its_own_grant_budget_independently(self):
        svc = new_service()
        svc.repository.put_grant(
            {
                "tenant_id": TENANT,
                "id": "00000000-0000-4000-8000-00000000c001",
                "capabilities": ["booking.reschedule"],
                "expiry": "2027-01-01T00:00:00Z",
                "revoked": False,
                "budget_remaining": 1,
            }
        )
        first = svc.try_issue_policy_covered_authorization(
            tenant_id=TENANT, work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a001"), root_business_key="booking:reschedule:quote-1",
            capabilities=["booking.reschedule"], manifest=self._manifest(),
            issued_at="2026-11-26T06:00:00Z", now="2026-11-26T06:00:00Z",
        )
        self.assertIsNotNone(first)
        second = svc.try_issue_policy_covered_authorization(
            tenant_id=TENANT, work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a002"), root_business_key="booking:reschedule:quote-2",
            capabilities=["booking.reschedule"], manifest=self._manifest(),
            issued_at="2026-11-26T06:05:00Z", now="2026-11-26T06:05:00Z",
        )
        self.assertIsNone(second, "budget was exhausted by the first Work's use of the same grant")

    def test_authorization_from_approval_rejects_manifest_outside_approved_scope(self):
        # SD-A-05: approval covers A/B, child task tries to add channel C.
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        approval = approve_happy_path(svc, decision, nonce_id)
        with self.assertRaises(AuthorizationError) as ctx:
            svc.issue_execution_authorization(
                tenant_id=TENANT,
                work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a001"),
                root_business_key="booking:reschedule:quote-1",
                capabilities=["booking.reschedule"],
                manifest=[{"item_id": "manifest-item-1", "operation": "booking.publish_channel_c"}],
                approval_refs=[_ref(TENANT, approval["id"])],
                issued_at="2026-11-26T06:00:00Z",
                now="2026-11-26T06:00:00Z",
            )
        self.assertEqual(ctx.exception.code, "AUTHORIZATION_SCOPE_MISMATCH")

    def test_authorization_use_resend_finds_the_same_use(self):
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        approval = approve_happy_path(svc, decision, nonce_id)
        authorization = svc.issue_execution_authorization(
            tenant_id=TENANT, work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a001"), root_business_key="booking:reschedule:quote-1",
            capabilities=["booking.reschedule"], manifest=self._manifest(),
            approval_refs=[_ref(TENANT, approval["id"])],
            issued_at="2026-11-26T06:00:00Z", now="2026-11-26T06:00:00Z", expiry="2026-11-27T06:00:00Z",
        )
        root_task_id = _ref(TENANT, "00000000-0000-4000-8000-00000000b001")
        first = svc.consume_authorization_use(
            tenant_id=TENANT, authorization_id=authorization["id"], root_task_id=root_task_id,
            root_business_key="booking:reschedule:quote-1", request_hash="f" * 64,
            used_at="2026-11-26T06:01:00Z", now="2026-11-26T06:01:00Z",
        )
        second = svc.consume_authorization_use(
            tenant_id=TENANT, authorization_id=authorization["id"], root_task_id=root_task_id,
            root_business_key="booking:reschedule:quote-1", request_hash="f" * 64,
            used_at="2026-11-26T06:01:05Z", now="2026-11-26T06:01:05Z",
        )
        self.assertEqual(first["id"], second["id"])

    def test_authorization_use_cannot_bind_a_second_root_task(self):
        # SD-A-06
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        approval = approve_happy_path(svc, decision, nonce_id)
        authorization = svc.issue_execution_authorization(
            tenant_id=TENANT, work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a001"), root_business_key="booking:reschedule:quote-1",
            capabilities=["booking.reschedule"], manifest=self._manifest(),
            approval_refs=[_ref(TENANT, approval["id"])],
            issued_at="2026-11-26T06:00:00Z", now="2026-11-26T06:00:00Z", expiry="2026-11-27T06:00:00Z",
        )
        svc.consume_authorization_use(
            tenant_id=TENANT, authorization_id=authorization["id"], root_task_id=_ref(TENANT, "00000000-0000-4000-8000-00000000b001"),
            root_business_key="booking:reschedule:quote-1", request_hash="f" * 64,
            used_at="2026-11-26T06:01:00Z", now="2026-11-26T06:01:00Z",
        )
        with self.assertRaises(AuthorizationError) as ctx:
            svc.consume_authorization_use(
                tenant_id=TENANT, authorization_id=authorization["id"], root_task_id=_ref(TENANT, "00000000-0000-4000-8000-00000000b002"),
                root_business_key="booking:reschedule:quote-1", request_hash="e" * 64,
                used_at="2026-11-26T06:02:00Z", now="2026-11-26T06:02:00Z",
            )
        self.assertEqual(ctx.exception.code, "AUTHORIZATION_USE_ALREADY_BOUND")
        # SD-A-06: the original root can still find its use.
        found = svc.repository.get_authorization_use(TENANT, authorization["id"])
        self.assertEqual(found["root_task_id"]["id"], "00000000-0000-4000-8000-00000000b001")


class RevocationRaceTests(unittest.TestCase):
    def _issue_authorization(self, svc):
        decision, nonce_id = create_pending_decision(svc)
        approval = approve_happy_path(svc, decision, nonce_id)
        authorization = svc.issue_execution_authorization(
            tenant_id=TENANT, work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a001"), root_business_key="booking:reschedule:quote-1",
            capabilities=["booking.reschedule"],
            manifest=[{"item_id": "manifest-item-1", "operation": "booking.reschedule"}],
            approval_refs=[_ref(TENANT, approval["id"])],
            issued_at="2026-11-26T06:00:00Z", now="2026-11-26T06:00:00Z", expiry="2026-11-27T06:00:00Z",
        )
        return approval, authorization

    def test_revoke_before_dispatch_blocks_the_not_yet_sent_action(self):
        # SD-A-07/08: revoke wins the race -> precheck must stop the new dispatch.
        svc = new_service()
        approval, authorization = self._issue_authorization(svc)
        result = svc.revoke_approval(
            tenant_id=TENANT, approval_id=approval["id"], revoked_by=_actor("EMPLOYEE", "00000000-0000-4000-8000-0000000000e1"),
            reason="merchant withdrew the reschedule offer", effective_at="2026-11-26T06:05:00Z",
            created_at="2026-11-26T06:05:01Z",
        )
        self.assertEqual(
            result["affected_authorizations"],
            [{"authorization_id": authorization["id"], "outcome": "NOT_YET_DISPATCHED_BLOCKED"}],
        )
        with self.assertRaises(AuthorizationError) as ctx:
            svc.precheck_before_dispatch(tenant_id=TENANT, authorization_id=authorization["id"], now="2026-11-26T06:06:00Z")
        self.assertEqual(ctx.exception.code, "AUTHORIZATION_REVOKED")

    def test_dispatch_before_revoke_lets_the_inflight_action_proceed_but_blocks_new_ones(self):
        svc = new_service()
        approval, authorization = self._issue_authorization(svc)
        svc.consume_authorization_use(
            tenant_id=TENANT, authorization_id=authorization["id"], root_task_id=_ref(TENANT, "00000000-0000-4000-8000-00000000b001"),
            root_business_key="booking:reschedule:quote-1", request_hash="f" * 64,
            used_at="2026-11-26T06:01:00Z", now="2026-11-26T06:01:00Z",
        )
        # worker rechecks right before actually calling the external connector, then sends it
        svc.precheck_before_dispatch(tenant_id=TENANT, authorization_id=authorization["id"], now="2026-11-26T06:01:30Z")
        svc.mark_dispatched(tenant_id=TENANT, authorization_id=authorization["id"], now="2026-11-26T06:01:31Z")

        result = svc.revoke_approval(
            tenant_id=TENANT, approval_id=approval["id"], revoked_by=_actor("EMPLOYEE", "00000000-0000-4000-8000-0000000000e1"),
            reason="merchant withdrew the reschedule offer, but this one already went out",
            effective_at="2026-11-26T06:05:00Z", created_at="2026-11-26T06:05:01Z",
        )
        self.assertEqual(
            result["affected_authorizations"],
            [{"authorization_id": authorization["id"], "outcome": "DISPATCHED_PROCEEDS_TO_RECONCILIATION"}],
        )
        # the in-flight call is not retroactively cancelled, but any *new* attempt
        # (e.g. a retry) after the revocation must be stopped.
        with self.assertRaises(AuthorizationError) as ctx:
            svc.precheck_before_dispatch(tenant_id=TENANT, authorization_id=authorization["id"], now="2026-11-26T06:10:00Z")
        self.assertEqual(ctx.exception.code, "AUTHORIZATION_REVOKED")

    def test_revoking_an_already_revoked_approval_is_idempotent(self):
        svc = new_service()
        approval, _authorization = self._issue_authorization(svc)
        first = svc.revoke_approval(
            tenant_id=TENANT, approval_id=approval["id"], revoked_by=_actor("EMPLOYEE", "00000000-0000-4000-8000-0000000000e1"),
            reason="first reason", effective_at="2026-11-26T06:05:00Z", created_at="2026-11-26T06:05:01Z",
        )
        second = svc.revoke_approval(
            tenant_id=TENANT, approval_id=approval["id"], revoked_by=_actor("EMPLOYEE", "00000000-0000-4000-8000-0000000000e2"),
            reason="resent revoke command", effective_at="2026-11-26T06:06:00Z", created_at="2026-11-26T06:06:01Z",
        )
        self.assertEqual(first["revocation"]["id"], second["revocation"]["id"])
        self.assertTrue(second["resent"])

    def test_revocation_requires_a_permitted_actor_kind(self):
        svc = new_service()
        approval, _authorization = self._issue_authorization(svc)
        with self.assertRaises(AuthorizationError) as ctx:
            svc.revoke_approval(
                tenant_id=TENANT, approval_id=approval["id"], revoked_by=_actor("CUSTOMER", "00000000-0000-4000-8000-0000000000c1"),
                reason="customer tries to revoke their own approval", effective_at="2026-11-26T06:05:00Z",
                created_at="2026-11-26T06:05:01Z",
            )
        self.assertEqual(ctx.exception.code, "REVOCATION_NOT_PERMITTED")

    def test_is_approval_effective_reflects_revocation_as_a_read_model(self):
        # ADR 0003: revoked_at is a projection, never written back onto the ApprovalRecord.
        svc = new_service()
        approval, _authorization = self._issue_authorization(svc)
        self.assertTrue(svc.is_approval_effective(tenant_id=TENANT, approval_id=approval["id"], at="2026-11-26T06:04:00Z"))
        svc.revoke_approval(
            tenant_id=TENANT, approval_id=approval["id"], revoked_by=_actor("EMPLOYEE", "00000000-0000-4000-8000-0000000000e1"),
            reason="policy change", effective_at="2026-11-26T06:05:00Z", created_at="2026-11-26T06:05:01Z",
        )
        self.assertTrue(svc.is_approval_effective(tenant_id=TENANT, approval_id=approval["id"], at="2026-11-26T06:04:59Z"))
        self.assertFalse(svc.is_approval_effective(tenant_id=TENANT, approval_id=approval["id"], at="2026-11-26T06:05:00Z"))
        stored_approval = svc.repository.get_approval(TENANT, approval["id"])
        self.assertNotIn("revoked_at", stored_approval)


class CrossTenantTests(unittest.TestCase):
    def test_approving_another_tenants_decision_id_is_rejected_without_disclosure(self):
        svc = new_service()
        decision, nonce_id = create_pending_decision(svc)
        with self.assertRaises(AuthorizationError) as ctx:
            svc.approve_decision(
                tenant_id=OTHER_TENANT,
                decision_id=decision["id"],
                expected_revision=1,
                selected_option_id="accept_new_quote",
                nonce_id=nonce_id,
                approved_by=_actor("CUSTOMER", "00000000-0000-4000-8000-0000000000c1"),
                verified_actor_ref="voice-confirmation:session-999",
                scope_manifest=[{"item_id": "manifest-item-1", "operation": "booking.reschedule"}],
                approved_at="2026-11-26T05:10:00Z",
                idempotency_key="idem-cross-tenant",
            )
        self.assertEqual(ctx.exception.code, "CROSS_TENANT_REFERENCE_REJECTED")

    def test_issuing_authorization_against_another_tenants_grant_is_rejected(self):
        svc = new_service()
        svc.repository.put_grant(
            {"tenant_id": OTHER_TENANT, "id": "00000000-0000-4000-8000-00000000c0f1", "capabilities": ["booking.reschedule"],
             "expiry": "2027-01-01T00:00:00Z", "revoked": False}
        )
        with self.assertRaises(AuthorizationError) as ctx:
            svc.issue_execution_authorization(
                tenant_id=TENANT, work_id=_ref(TENANT, "00000000-0000-4000-8000-00000000a001"), root_business_key="booking:reschedule:quote-1",
                capabilities=["booking.reschedule"], manifest=[{"item_id": "m1", "operation": "booking.reschedule"}],
                grant_refs=[_ref(TENANT, "00000000-0000-4000-8000-00000000c0f1")], issued_at="2026-11-26T06:00:00Z", now="2026-11-26T06:00:00Z",
            )
        self.assertEqual(ctx.exception.code, "CROSS_TENANT_REFERENCE_REJECTED")


if __name__ == "__main__":
    unittest.main()
