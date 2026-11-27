"""Commands implementing the durable boundaries of SA UC-03/UC-04.

All methods are called inside the caller's tenant transaction.  Provider I/O
is intentionally outside this module: only WEBRTC and SIP_TEST identifiers are
accepted, so no mock result can be mistaken for a real telephone connection.
"""
from __future__ import annotations

import uuid
from typing import Any

from db.repository import case_repository, voice_repository

from .errors import ResumeVerificationRequired, UnsafePaymentHandoff, VoiceSessionNotFound


def _id() -> str:
    return str(uuid.uuid4())


class VoiceService:
    def create_session(self, conn: Any, *, tenant_id: str, case_id: str, transport: str, provider_session_ref: str, recording_policy: dict[str, Any], recording_notice_given: bool) -> dict[str, Any]:
        if transport not in {"WEBRTC", "SIP_TEST"}:
            raise ValueError("only WEBRTC or explicitly test-scoped SIP_TEST are supported")
        case = case_repository.get_case(conn, tenant_id=tenant_id, case_id=case_id)
        if not case:
            raise VoiceSessionNotFound("case not found")
        return voice_repository.create_session(conn, tenant_id=tenant_id, session_id=_id(), case_id=case_id, transport=transport, provider_session_ref=provider_session_ref, recording_policy=recording_policy, recording_status="NOTICE_GIVEN" if recording_notice_given else "NOT_REQUESTED", case_owner_revision=case["owner_revision"])

    def start_session(self, conn: Any, *, tenant_id: str, session_id: str) -> dict[str, Any]:
        return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="ACTIVE")

    def record_turn(self, conn: Any, *, tenant_id: str, session_id: str, status: str, transcript_ref: str | None = None) -> None:
        session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id)
        if not session:
            raise VoiceSessionNotFound("voice session not found")
        demand_revision = case_repository.get_case(conn, tenant_id=tenant_id, case_id=session["case_id"])["demand_revision"]
        voice_repository.append_turn(conn, tenant_id=tenant_id, turn_id=_id(), session_id=session_id, demand_revision=demand_revision, status=status, transcript_ref=transcript_ref)

    def interrupt_for_correction(self, conn: Any, *, tenant_id: str, session_id: str) -> int:
        session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id)
        if not session:
            raise VoiceSessionNotFound("voice session not found")
        prior = case_repository.get_case(conn, tenant_id=tenant_id, case_id=session["case_id"])["demand_revision"]
        next_revision = case_repository.revise_demand(conn, tenant_id=tenant_id, case_id=session["case_id"])
        voice_repository.interrupt_for_new_demand(conn, tenant_id=tenant_id, session_id=session_id, prior_demand_revision=prior)
        return next_revision

    def resume_session(self, conn: Any, *, tenant_id: str, session_id: str, verified_case_id: str) -> dict[str, Any]:
        session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id)
        if not session:
            raise VoiceSessionNotFound("voice session not found")
        if verified_case_id != session["case_id"]:
            raise ResumeVerificationRequired("verified case does not match the session")
        return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="ACTIVE")

    def request_transfer(self, conn: Any, *, tenant_id: str, session_id: str, destination_ref: str) -> str:
        if not voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id):
            raise VoiceSessionNotFound("voice session not found")
        transfer_id = _id()
        voice_repository.create_transfer(conn, tenant_id=tenant_id, transfer_id=transfer_id, session_id=session_id, destination_ref=destination_ref)
        voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="TRANSFERRING")
        return transfer_id

    def apply_transfer_result(self, conn: Any, *, tenant_id: str, transfer_id: str, status: str, provider_result_ref: str | None = None) -> dict[str, Any]:
        if status not in {"RINGING", "CONNECTED", "FAILED"}:
            raise ValueError("invalid transfer result")
        return voice_repository.set_transfer_status(conn, tenant_id=tenant_id, transfer_id=transfer_id, status=status, provider_result_ref=provider_result_ref)

    def receive_audio_message(self, conn: Any, *, tenant_id: str, case_id: str, source_event_id: str, asset_ref: str) -> bool:
        return voice_repository.receive_asynchronous_media(conn, tenant_id=tenant_id, intake_id=_id(), case_id=case_id, source_event_id=source_event_id, media_kind="AUDIO_MESSAGE", asset_ref=asset_ref)

    def create_payment_link_handoff(self, conn: Any, *, tenant_id: str, session_id: str, payment_link_ref: str, order_id: str | None = None) -> str:
        if not payment_link_ref or payment_link_ref.lower().startswith(("card:", "pan:", "cvv:")):
            raise UnsafePaymentHandoff("voice flow may hand off a payment link, never card data")
        handoff_id = _id()
        voice_repository.create_payment_handoff(conn, tenant_id=tenant_id, handoff_id=handoff_id, session_id=session_id, order_id=order_id, payment_link_ref=payment_link_ref)
        return handoff_id
