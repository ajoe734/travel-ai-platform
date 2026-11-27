"""ENG-10 acceptance probes using the actual Postgres repositories."""
from __future__ import annotations

import pytest

from db.repository import db as repo_db
from db.repository.errors import IdempotencyConflict
from datetime import datetime, timedelta, timezone

from services.voice.errors import ResumeChallengeRejected, TransferDestinationRejected, UnsafePaymentHandoff, VoiceStateConflict
from services.voice.service import VoiceService


def test_correction_supersedes_old_voice_turn_without_cancelling_the_case(conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    service = VoiceService()
    with repo_db.tenant_transaction(conn, tenant_a):
        session = service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport="WEBRTC", provider_session_ref="webrtc-test-1", recording_policy={"notice_version": "v1"}, recording_notice_given=True)
        service.start_session(conn, tenant_id=tenant_a, session_id=session["id"])
        service.record_turn(conn, tenant_id=tenant_a, session_id=session["id"], status="CONFIRMED", expected_demand_revision=1, expected_owner_revision=0, transcript_ref="private://turn/1")
        playback_id = service.create_playback(conn, tenant_id=tenant_a, session_id=session["id"], demand_revision=1)
        service.set_playback_status(conn, tenant_id=tenant_a, playback_id=playback_id, status="PLAYING")
        demand_revision = service.interrupt_for_correction(conn, tenant_id=tenant_a, session_id=session["id"])
        turn_status = conn.execute("SELECT status FROM voice_turn WHERE tenant_id=%s AND session_id=%s", (tenant_a, session["id"])).fetchone()[0]
        playback_status = conn.execute("SELECT status FROM voice_playback WHERE tenant_id=%s AND id=%s", (tenant_a, playback_id)).fetchone()[0]
        with pytest.raises(VoiceStateConflict):
            service.record_turn(conn, tenant_id=tenant_a, session_id=session["id"], status="FINAL", expected_demand_revision=1, expected_owner_revision=0)
    assert demand_revision == 2
    assert turn_status == "SUPERSEDED"
    assert playback_status == "INTERRUPTED"


def test_resume_requires_verified_original_case_and_audio_message_dedupes(conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    other_case_id = case_factory(tenant_a)
    service = VoiceService()
    with repo_db.tenant_transaction(conn, tenant_a):
        session = service.create_session(conn, tenant_id=tenant_a, case_id=case_id, transport="SIP_TEST", provider_session_ref="sip-test-1", recording_policy={"notice_version": "v1"}, recording_notice_given=False)
        service.start_session(conn, tenant_id=tenant_a, session_id=session["id"])
        service.disconnect_session(conn, tenant_id=tenant_a, session_id=session["id"])
        challenge = service.issue_resume_challenge(conn, tenant_id=tenant_a, session_id=session["id"], proof="otp", expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
        with pytest.raises(ResumeChallengeRejected): service.resume_session(conn, tenant_id=tenant_a, session_id=session["id"], challenge_id=challenge, proof="wrong")
        service.resume_session(conn, tenant_id=tenant_a, session_id=session["id"], challenge_id=challenge, proof="otp")
        first = service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="line-audio-1", media_kind="AUDIO_MESSAGE", asset_ref="quarantine://asset/1")
        duplicate = service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="line-audio-1", media_kind="AUDIO_MESSAGE", asset_ref="quarantine://asset/1")
        for kind in ("IMAGE", "VIDEO", "DOCUMENT"):
            assert service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="asset-" + kind, media_kind=kind, asset_ref="quarantine://" + kind)
        with pytest.raises(IdempotencyConflict):
            service.receive_asynchronous_media(conn, tenant_id=tenant_a, case_id=case_id, producer_ref="line", source_event_id="line-audio-1", media_kind="AUDIO_MESSAGE", asset_ref="quarantine://changed")
    assert first is True
    assert duplicate is False


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
