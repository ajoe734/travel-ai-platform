"""Commands implementing the durable boundaries of SA UC-03/UC-04.

All methods are called inside the caller's tenant transaction.  Provider I/O
is intentionally outside this module: only WEBRTC and SIP_TEST identifiers are
accepted, so no mock result can be mistaken for a real telephone connection.
"""
from __future__ import annotations

import re
import uuid
from urllib.parse import parse_qsl, urlparse
from typing import Any

from db.repository import case_repository, voice_repository

from .errors import (PaymentHandoffOwnershipRejected, ResumeChallengeRejected,
                     TransferDestinationRejected, UnsafePaymentHandoff,
                     VoiceSessionNotFound, VoiceStateConflict)


def _id() -> str:
    return str(uuid.uuid4())


class VoiceService:
    def __init__(self, *, transfer_destinations: set[str] | None = None) -> None:
        self.transfer_destinations = transfer_destinations or set()
    def create_session(self, conn: Any, *, tenant_id: str, case_id: str, transport: str, provider_session_ref: str, recording_policy: dict[str, Any], recording_notice_given: bool) -> dict[str, Any]:
        if transport not in {"WEBRTC", "SIP_TEST"}:
            raise ValueError("only WEBRTC or explicitly test-scoped SIP_TEST are supported")
        case = case_repository.get_case(conn, tenant_id=tenant_id, case_id=case_id)
        if not case:
            raise VoiceSessionNotFound("case not found")
        return voice_repository.create_session(conn, tenant_id=tenant_id, session_id=_id(), case_id=case_id, transport=transport, provider_session_ref=provider_session_ref, recording_policy=recording_policy, recording_status="NOTICE_GIVEN" if recording_notice_given else "NOT_REQUESTED", case_owner_revision=case["owner_revision"])

    def start_session(self, conn: Any, *, tenant_id: str, session_id: str) -> dict[str, Any]:
        return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="ACTIVE")

    def set_recording_status(self, conn: Any, *, tenant_id: str, session_id: str, status: str) -> None:
        try: voice_repository.set_recording_status(conn, tenant_id=tenant_id, session_id=session_id, status=status)
        except RuntimeError as exc: raise VoiceStateConflict(str(exc)) from exc

    def record_turn(self, conn: Any, *, tenant_id: str, session_id: str, status: str, expected_demand_revision: int, expected_owner_revision: int, transcript_ref: str | None = None) -> None:
        session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id)
        if not session:
            raise VoiceSessionNotFound("voice session not found")
        case = case_repository.get_case(conn, tenant_id=tenant_id, case_id=session["case_id"])
        if session["status"] != "ACTIVE" or case is None or case["demand_revision"] != expected_demand_revision or case["owner_revision"] != expected_owner_revision or session["case_owner_revision"] != expected_owner_revision:
            raise VoiceStateConflict("stale demand/owner revision or inactive voice session")
        voice_repository.append_turn(conn, tenant_id=tenant_id, turn_id=_id(), session_id=session_id, demand_revision=expected_demand_revision, status=status, transcript_ref=transcript_ref)

    def interrupt_for_correction(self, conn: Any, *, tenant_id: str, session_id: str) -> int:
        session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id)
        if not session:
            raise VoiceSessionNotFound("voice session not found")
        prior, next_revision = case_repository.revise_demand_with_prior(conn, tenant_id=tenant_id, case_id=session["case_id"])
        voice_repository.interrupt_for_new_demand(conn, tenant_id=tenant_id, session_id=session_id, prior_demand_revision=prior)
        return next_revision

    def issue_resume_challenge(self, conn: Any, *, tenant_id: str, session_id: str, proof: str, expires_at: str) -> str:
        session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id)
        if not session:
            raise VoiceSessionNotFound("voice session not found")
        challenge_id = _id()
        voice_repository.create_resume_challenge(conn, tenant_id=tenant_id, challenge_id=challenge_id, session_id=session_id, proof=proof, expires_at=expires_at)
        return challenge_id

    def resume_session(self, conn: Any, *, tenant_id: str, session_id: str, challenge_id: str, proof: str) -> dict[str, Any]:
        session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id)
        if not session:
            raise VoiceSessionNotFound("voice session not found")
        if session["status"] != "DISCONNECTED" or not voice_repository.consume_resume_challenge(conn, tenant_id=tenant_id, challenge_id=challenge_id, session_id=session_id, proof=proof):
            raise ResumeChallengeRejected("valid, unexpired CASE_RESUME challenge required")
        try:
            return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="ACTIVE")
        except RuntimeError as exc:
            raise VoiceStateConflict(str(exc)) from exc

    def disconnect_session(self, conn: Any, *, tenant_id: str, session_id: str) -> dict[str, Any]:
        try: return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="DISCONNECTED")
        except (LookupError, RuntimeError) as exc: raise VoiceStateConflict(str(exc)) from exc

    def close_session(self, conn: Any, *, tenant_id: str, session_id: str) -> dict[str, Any]:
        try: return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="CLOSED")
        except (LookupError, RuntimeError) as exc: raise VoiceStateConflict(str(exc)) from exc

    def request_transfer(self, conn: Any, *, tenant_id: str, session_id: str, destination_ref: str) -> str:
        session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id)
        if not session:
            raise VoiceSessionNotFound("voice session not found")
        if session["status"] != "ACTIVE" or destination_ref not in self.transfer_destinations:
            raise TransferDestinationRejected("transfer requires ACTIVE session and configured destination")
        transfer_id = _id()
        voice_repository.create_transfer(conn, tenant_id=tenant_id, transfer_id=transfer_id, session_id=session_id, destination_ref=destination_ref)
        voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="TRANSFERRING")
        return transfer_id

    def apply_transfer_result(self, conn: Any, *, tenant_id: str, transfer_id: str, status: str, provider_result_ref: str | None = None) -> dict[str, Any]:
        if status not in {"RINGING", "CONNECTED", "FAILED"}:
            raise VoiceStateConflict("invalid transfer result")
        try:
            outcome = voice_repository.set_transfer_status(conn, tenant_id=tenant_id, transfer_id=transfer_id, status=status, provider_result_ref=provider_result_ref)
        except RuntimeError as exc:
            raise VoiceStateConflict(str(exc)) from exc
        transfer = conn.execute("SELECT session_id FROM voice_transfer WHERE tenant_id=%s AND id=%s", (tenant_id, transfer_id)).fetchone()
        if status == "FAILED":
            voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=transfer[0], status="ACTIVE")
        elif status == "CONNECTED":
            session = voice_repository.get_session(conn, tenant_id=tenant_id, session_id=transfer[0])
            case_repository.take_over_ownership(conn, tenant_id=tenant_id, case_id=session["case_id"], new_owner={"actor_kind": "HUMAN_MERCHANT", "actor_id": "transfer:" + transfer_id})
            voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=transfer[0], status="CLOSED")
        return outcome

    def receive_asynchronous_media(self, conn: Any, *, tenant_id: str, case_id: str, producer_ref: str, source_event_id: str, media_kind: str, asset_ref: str) -> bool:
        if media_kind not in {"AUDIO_MESSAGE", "IMAGE", "VIDEO", "DOCUMENT"}:
            raise VoiceStateConflict("unsupported asynchronous media kind")
        return voice_repository.receive_asynchronous_media(conn, tenant_id=tenant_id, intake_id=_id(), case_id=case_id, producer_ref=producer_ref, source_event_id=source_event_id, media_kind=media_kind, asset_ref=asset_ref)

    def create_playback(self, conn: Any, *, tenant_id: str, session_id: str, demand_revision: int) -> str:
        playback_id = _id(); voice_repository.create_playback(conn, tenant_id=tenant_id, playback_id=playback_id, session_id=session_id, demand_revision=demand_revision); return playback_id

    def set_playback_status(self, conn: Any, *, tenant_id: str, playback_id: str, status: str) -> None:
        try: voice_repository.set_playback_status(conn, tenant_id=tenant_id, playback_id=playback_id, status=status)
        except RuntimeError as exc: raise VoiceStateConflict(str(exc)) from exc

    def create_payment_link_handoff(self, conn: Any, *, tenant_id: str, session_id: str, payment_link_ref: str, order_id: str | None = None) -> str:
        parsed = urlparse(payment_link_ref)
        sensitive = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)} & {"card", "pan", "cvv", "cvc", "card_number"}
        if not payment_link_ref or parsed.scheme not in {"https", "payment-link"} or parsed.username or sensitive or re.search(r"(?<!\d)\d{13,19}(?!\d)", payment_link_ref):
            raise UnsafePaymentHandoff("voice flow may hand off a payment link, never card data")
        if not voice_repository.payment_handoff_context_valid(conn, tenant_id=tenant_id, session_id=session_id, order_id=order_id):
            raise PaymentHandoffOwnershipRejected("session must exist and order must belong to its case")
        handoff_id = _id()
        voice_repository.create_payment_handoff(conn, tenant_id=tenant_id, handoff_id=handoff_id, session_id=session_id, order_id=order_id, payment_link_ref=payment_link_ref)
        return handoff_id
