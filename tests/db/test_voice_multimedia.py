"""ENG-10 acceptance probes using the actual Postgres repositories."""
from __future__ import annotations

import pytest

from db.repository import db as repo_db
from db.repository.errors import IdempotencyConflict
from datetime import datetime, timedelta, timezone

from services.voice.errors import (PaymentHandoffOwnershipRejected,
                                   ResumeChallengeRejected,
                                   TransferDestinationRejected,
                                   UnsafePaymentHandoff, VoiceSessionNotFound,
                                   VoiceStateConflict)
from services.voice.service import VoiceService


_CONFIRMED_FIELDS = {"service_date": "2026-12-01", "timezone": "Asia/Taipei", "party_size": 2, "amount_minor_units": 1800, "currency": "TWD"}


def test_correction_supersedes_old_voice_turn_without_cancelling_the_case(conn, tenant_a, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    service = VoiceService()
    with repo_db.tenant_transaction(conn, tenant_a):
        session = service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport="WEBRTC", provider_session_ref="webrtc-test-1", recording_policy={"notice_version": "v1"}, recording_notice_given=True)
        service.start_session(conn, tenant_id=tenant_a, session_id=session["id"])
        service.record_turn(conn, tenant_id=tenant_a, session_id=session["id"], status="CONFIRMED", expected_demand_revision=1, expected_owner_revision=0, transcript_ref="private://turn/1", confirmed_fields=_CONFIRMED_FIELDS)
        # This represents a provider-accepted operation.  Correcting spoken
        # input must only stop local playback, never cancel it.
        work_id = work_factory(tenant_a, case_id)
        task_id = "00000000-0000-4000-8000-000000000901"
        conn.execute("""INSERT INTO execution_task (tenant_id,id,work_id,kind,operation,business_key,request_hash,request_snapshot,status,postcondition_version,postcondition)
                        VALUES (%s,%s,%s,'ACTION','booking.create','voice-test-booking','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','{}'::jsonb,'WAITING','v1','{}'::jsonb)""", (tenant_a, task_id, work_id))
        playback_id = service.create_playback(conn, tenant_id=tenant_a, session_id=session["id"], demand_revision=1)
        service.set_playback_status(conn, tenant_id=tenant_a, playback_id=playback_id, status="PLAYING")
        demand_revision = service.interrupt_for_correction(conn, tenant_id=tenant_a, session_id=session["id"])
        turn_status = conn.execute("SELECT status FROM voice_turn WHERE tenant_id=%s AND session_id=%s", (tenant_a, session["id"])).fetchone()[0]
        playback_status = conn.execute("SELECT status FROM voice_playback WHERE tenant_id=%s AND id=%s", (tenant_a, playback_id)).fetchone()[0]
        task_status = conn.execute("SELECT status FROM execution_task WHERE tenant_id=%s AND id=%s", (tenant_a, task_id)).fetchone()[0]
        with pytest.raises(VoiceStateConflict):
            service.record_turn(conn, tenant_id=tenant_a, session_id=session["id"], status="FINAL", expected_demand_revision=1, expected_owner_revision=0)
    assert demand_revision == 2
    assert turn_status == "SUPERSEDED"
    assert playback_status == "INTERRUPTED"
    assert task_status == "WAITING"


def test_resume_requires_verified_original_case_and_audio_message_dedupes(conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    service = VoiceService()
    with repo_db.tenant_transaction(conn, tenant_a):
        session = service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport="SIP_TEST", provider_session_ref="sip-test-1", recording_policy={"notice_version": "v1"}, recording_notice_given=False)
        service.start_session(conn, tenant_id=tenant_a, session_id=session["id"])
        service.disconnect_session(conn, tenant_id=tenant_a, session_id=session["id"])
        challenge = service.issue_resume_challenge(conn, tenant_id=tenant_a, session_id=session["id"], proof="otp", expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
        assert service.resume_session(conn, tenant_id=tenant_a, session_id=session["id"], challenge_id=challenge, proof="wrong") is None
        service.resume_session(conn, tenant_id=tenant_a, session_id=session["id"], challenge_id=challenge, proof="otp")
        first = service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="line-audio-1", media_kind="AUDIO_MESSAGE", asset_ref="quarantine://asset/1")
        duplicate = service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="line-audio-1", media_kind="AUDIO_MESSAGE", asset_ref="quarantine://asset/1")
        for kind in ("IMAGE", "VIDEO", "DOCUMENT"):
            assert service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="asset-" + kind, media_kind=kind, asset_ref="quarantine://" + kind)
        with pytest.raises(IdempotencyConflict):
            service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="line-audio-1", media_kind="AUDIO_MESSAGE", asset_ref="quarantine://changed")
    assert first is True
    assert duplicate is False


def test_resume_challenge_expiry_lock_replay_and_state_guards(conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    service = VoiceService()
    with repo_db.tenant_transaction(conn, tenant_a):
        session = service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport="WEBRTC", provider_session_ref="webrtc-resume-1", recording_policy={}, recording_notice_given=False)
        service.start_session(conn, tenant_id=tenant_a, session_id=session["id"])
        with pytest.raises(ResumeChallengeRejected):
            service.issue_resume_challenge(conn, tenant_id=tenant_a, session_id=session["id"], proof="otp", expires_at=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
        service.disconnect_session(conn, tenant_id=tenant_a, session_id=session["id"])
        expired = service.issue_resume_challenge(conn, tenant_id=tenant_a, session_id=session["id"], proof="otp", expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
        assert service.resume_session(conn, tenant_id=tenant_a, session_id=session["id"], challenge_id=expired, proof="otp") is None
        challenge = service.issue_resume_challenge(conn, tenant_id=tenant_a, session_id=session["id"], proof="otp2", expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
        for _ in range(5):
            assert service.resume_session(conn, tenant_id=tenant_a, session_id=session["id"], challenge_id=challenge, proof="wrong") is None
        failed, locked = conn.execute("SELECT failed_attempts,locked_at FROM voice_resume_challenge WHERE tenant_id=%s AND id=%s", (tenant_a, challenge)).fetchone()
        assert failed == 5 and locked is not None
        with pytest.raises(ResumeChallengeRejected):
            service.issue_resume_challenge(conn, tenant_id=tenant_a, session_id=session["id"], proof="new", expires_at=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
    assert failed == 5


def test_transfer_outcome_and_payment_link_are_recorded_without_card_data(conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    service = VoiceService(transfer_destinations={"merchant-oncall-1"})
    with repo_db.tenant_transaction(conn, tenant_a):
        session = service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport="WEBRTC", provider_session_ref="webrtc-test-2", recording_policy={"notice_version": "v1"}, recording_notice_given=True)
        service.start_session(conn, tenant_id=tenant_a, session_id=session["id"])
        with pytest.raises(TransferDestinationRejected): service.request_transfer(conn, tenant_id=tenant_a, session_id=session["id"], destination_ref="unapproved")
        transfer_id = service.request_transfer(conn, tenant_id=tenant_a, session_id=session["id"], destination_ref="merchant-oncall-1")
        outcome = service.apply_transfer_result(conn, tenant_id=tenant_a, transfer_id=transfer_id, status="FAILED", provider_result_ref="provider-failed-1")
        handoff_id = service.create_payment_link_handoff(conn, tenant_id=tenant_a, session_id=session["id"], payment_link_ref="payment-link://checkout/1")
        with pytest.raises(UnsafePaymentHandoff):
            service.create_payment_link_handoff(conn, tenant_id=tenant_a, session_id=session["id"], payment_link_ref="pan:4111111111111111")
    assert outcome == {"status": "FAILED", "provider_result_ref": "provider-failed-1"}
    assert handoff_id


def test_transfer_connected_takes_over_and_terminal_state_cannot_regress(conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    service = VoiceService(transfer_destinations={"merchant-oncall-1"})
    with repo_db.tenant_transaction(conn, tenant_a):
        session = service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport="WEBRTC", provider_session_ref="webrtc-transfer-1", recording_policy={}, recording_notice_given=False)
        service.start_session(conn, tenant_id=tenant_a, session_id=session["id"])
        transfer_id = service.request_transfer(conn, tenant_id=tenant_a, session_id=session["id"], destination_ref="merchant-oncall-1")
        assert service.apply_transfer_result(conn, tenant_id=tenant_a, transfer_id=transfer_id, status="RINGING")["status"] == "RINGING"
        assert service.apply_transfer_result(conn, tenant_id=tenant_a, transfer_id=transfer_id, status="CONNECTED")["status"] == "CONNECTED"
        assert service.apply_transfer_result(conn, tenant_id=tenant_a, transfer_id=transfer_id, status="CONNECTED")["status"] == "CONNECTED"
        assert conn.execute("SELECT owner_revision FROM case_record WHERE tenant_id=%s AND id=%s", (tenant_a, case_id)).fetchone()[0] == 1
        with pytest.raises(VoiceStateConflict):
            service.record_turn(conn, tenant_id=tenant_a, session_id=session["id"], status="FINAL", expected_demand_revision=1, expected_owner_revision=0)
        with pytest.raises(VoiceStateConflict):
            service.apply_transfer_result(conn, tenant_id=tenant_a, transfer_id=transfer_id, status="FAILED")


def test_media_recording_payment_ownership_and_transport_rejections(conn, tenant_a, tenant_b, case_factory, payment_chain_factory):
    case_id = case_factory(tenant_a)
    other_case_id = case_factory(tenant_a)
    order_id = payment_chain_factory(tenant_a, other_case_id, 100)["order_id"]
    service = VoiceService()
    with repo_db.tenant_transaction(conn, tenant_a):
        for transport in ("AUDIO_MESSAGE", "LINE_NATIVE_CALL", "SIP"):
            with pytest.raises(ValueError):
                service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport=transport, provider_session_ref="rejected-" + transport, recording_policy={}, recording_notice_given=False)
        session = service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport="WEBRTC", provider_session_ref="webrtc-media-1", recording_policy={}, recording_notice_given=False)
        service.set_recording_status(conn, tenant_id=tenant_a, session_id=session["id"], status="NOTICE_GIVEN")
        service.set_recording_status(conn, tenant_id=tenant_a, session_id=session["id"], status="RECORDING")
        service.set_recording_status(conn, tenant_id=tenant_a, session_id=session["id"], status="REDACTED")
        intake = service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="status-1", media_kind="AUDIO_MESSAGE", asset_ref="quarantine://status-1")
        intake_id = conn.execute("SELECT id FROM asynchronous_media_intake WHERE tenant_id=%s AND source_event_id='status-1'", (tenant_a,)).fetchone()[0]
        assert intake is True
        service.set_media_status(conn, tenant_id=tenant_a, intake_id=intake_id, status="SCANNING")
        service.set_media_status(conn, tenant_id=tenant_a, intake_id=intake_id, status="READY")
        with pytest.raises(VoiceStateConflict): service.set_media_status(conn, tenant_id=tenant_a, intake_id=intake_id, status="REJECTED")
        # Keep the outer tenant command usable after proving the trigger by
        # containing PostgreSQL's failed statement in a savepoint.
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute("DELETE FROM asynchronous_media_intake WHERE tenant_id=%s AND id=%s", (tenant_a, intake_id))
        with pytest.raises(PaymentHandoffOwnershipRejected): service.create_payment_link_handoff(conn, tenant_id=tenant_a, session_id=session["id"], payment_link_ref="https://pay.example.com/a", order_id=order_id)
        with pytest.raises(PaymentHandoffOwnershipRejected): service.create_payment_link_handoff(conn, tenant_id=tenant_a, session_id="00000000-0000-4000-8000-000000000777", payment_link_ref="https://pay.example.com/a")
        for link in ("https://pay.example.com/?ref=4111-1111-1111-1111", "https://pay.example.com/#pan=4111-1111-1111-1111&cvv=123", "https://pay.example.com/?security_code=123", "https://:secret@pay.example.com/a", "https:///no-host"):
            with pytest.raises(UnsafePaymentHandoff): service.create_payment_link_handoff(conn, tenant_id=tenant_a, session_id=session["id"], payment_link_ref=link)
    with repo_db.tenant_transaction(conn, tenant_b):
        with pytest.raises(VoiceSessionNotFound):
            service.start_session(conn, tenant_id=tenant_b, session_id=session["id"])
