"""Commands implementing the durable boundaries of SA UC-03/UC-04.

All methods are called inside the caller's tenant transaction.  Provider I/O
is intentionally outside this module: only WEBRTC and SIP_TEST identifiers are
accepted, so no mock result can be mistaken for a real telephone connection.
"""
from __future__ import annotations

import uuid
from typing import Any

from db.repository import case_repository, voice_repository

from .errors import (PaymentHandoffOwnershipRejected, ResumeChallengeRejected,
                     TransferDestinationRejected, UnsafePaymentHandoff,
                     VoiceSessionNotFound, VoiceStateConflict)
from .validation import confirmed_fields_are_valid, payment_link_is_safe


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
        try:
            return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="ACTIVE")
        except LookupError as exc:
            raise VoiceSessionNotFound(str(exc)) from exc
        except RuntimeError as exc:
            raise VoiceStateConflict(str(exc)) from exc

    def set_recording_status(self, conn: Any, *, tenant_id: str, session_id: str, status: str) -> None:
        try: voice_repository.set_recording_status(conn, tenant_id=tenant_id, session_id=session_id, status=status)
        except RuntimeError as exc: raise VoiceStateConflict(str(exc)) from exc

    def record_turn(self, conn: Any, *, tenant_id: str, session_id: str, status: str, expected_demand_revision: int, expected_owner_revision: int, transcript_ref: str | None = None, confirmed_fields: dict[str, Any] | None = None) -> None:
        if status == "CONFIRMED" and not confirmed_fields_are_valid(confirmed_fields):
            raise VoiceStateConflict("CONFIRMED voice turn requires date, IANA timezone, party size, and amount replay")
        if status != "CONFIRMED" and confirmed_fields is not None:
            raise VoiceStateConflict("only CONFIRMED voice turns may carry confirmed_fields")
        locked = voice_repository.lock_session_and_case(conn, tenant_id=tenant_id, session_id=session_id)
        if not locked:
            raise VoiceSessionNotFound("voice session not found")
        session, case = locked
        if session["status"] != "ACTIVE" or case is None or case["demand_revision"] != expected_demand_revision or case["owner_revision"] != expected_owner_revision or session["case_owner_revision"] != expected_owner_revision:
            raise VoiceStateConflict("stale demand/owner revision or inactive voice session")
        voice_repository.append_turn(conn, tenant_id=tenant_id, turn_id=_id(), session_id=session_id, demand_revision=expected_demand_revision, status=status, transcript_ref=transcript_ref, confirmed_fields=confirmed_fields)

    def interrupt_for_correction(self, conn: Any, *, tenant_id: str, session_id: str) -> int:
        locked = voice_repository.lock_session_and_case(conn, tenant_id=tenant_id, session_id=session_id)
        if not locked:
            raise VoiceSessionNotFound("voice session not found")
        session, case = locked
        if session["status"] != "ACTIVE":
            raise VoiceStateConflict("only an ACTIVE session may interrupt for a correction")
        prior, next_revision = case_repository.revise_demand_with_prior(conn, tenant_id=tenant_id, case_id=session["case_id"])
        voice_repository.interrupt_for_new_demand(conn, tenant_id=tenant_id, session_id=session_id, prior_demand_revision=prior)
        return next_revision

    def issue_resume_challenge(self, conn: Any, *, tenant_id: str, session_id: str, proof: str, expires_at: str) -> str:
        locked = voice_repository.lock_session_and_case(conn, tenant_id=tenant_id, session_id=session_id)
        if not locked:
            raise VoiceSessionNotFound("voice session not found")
        session, _case = locked
        if session["status"] != "DISCONNECTED" or not voice_repository.resume_challenge_can_issue(conn, tenant_id=tenant_id, session_id=session_id):
            raise ResumeChallengeRejected("resume challenge requires disconnected, unlocked session")
        challenge_id = _id()
        voice_repository.create_resume_challenge(conn, tenant_id=tenant_id, challenge_id=challenge_id, session_id=session_id, proof=proof, expires_at=expires_at)
        return challenge_id

    def resume_session(self, conn: Any, *, tenant_id: str, session_id: str, challenge_id: str, proof: str) -> dict[str, Any] | None:
        locked = voice_repository.lock_session_and_case(conn, tenant_id=tenant_id, session_id=session_id)
        if not locked:
            raise VoiceSessionNotFound("voice session not found")
        session, _case = locked
        if session["status"] != "DISCONNECTED":
            return None
        # Rejection returns a durable result instead of raising from the
        # command transaction, so failed_attempts/locked_at are committed.
        if not voice_repository.consume_resume_challenge(conn, tenant_id=tenant_id, challenge_id=challenge_id, session_id=session_id, proof=proof):
            return None
        try:
            return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="ACTIVE")
        except RuntimeError as exc:
            raise VoiceStateConflict(str(exc)) from exc

    def disconnect_session(self, conn: Any, *, tenant_id: str, session_id: str) -> dict[str, Any]:
        try: return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="DISCONNECTED")
        except LookupError as exc: raise VoiceSessionNotFound(str(exc)) from exc
        except RuntimeError as exc: raise VoiceStateConflict(str(exc)) from exc

    def close_session(self, conn: Any, *, tenant_id: str, session_id: str) -> dict[str, Any]:
        try: return voice_repository.set_session_status(conn, tenant_id=tenant_id, session_id=session_id, status="CLOSED")
        except LookupError as exc: raise VoiceSessionNotFound(str(exc)) from exc
        except RuntimeError as exc: raise VoiceStateConflict(str(exc)) from exc

    def request_transfer(self, conn: Any, *, tenant_id: str, session_id: str, destination_ref: str) -> str:
        if destination_ref not in self.transfer_destinations:
            raise TransferDestinationRejected("transfer requires ACTIVE session and configured destination")
        transfer_id = _id()
        try:
            voice_repository.create_transfer_from_active(conn, tenant_id=tenant_id, transfer_id=transfer_id, session_id=session_id, destination_ref=destination_ref)
        except RuntimeError as exc:
            if voice_repository.get_session(conn, tenant_id=tenant_id, session_id=session_id) is None:
                raise VoiceSessionNotFound("voice session not found") from exc
            raise TransferDestinationRejected(str(exc)) from exc
        return transfer_id

    def apply_transfer_result(self, conn: Any, *, tenant_id: str, transfer_id: str, status: str, provider_result_ref: str | None = None) -> dict[str, Any]:
        if status not in {"RINGING", "CONNECTED", "FAILED"}:
            raise VoiceStateConflict("invalid transfer result")
        try:
            outcome = voice_repository.set_transfer_status(conn, tenant_id=tenant_id, transfer_id=transfer_id, status=status, provider_result_ref=provider_result_ref)
        except RuntimeError as exc:
            raise VoiceStateConflict(str(exc)) from exc
        if status == "CONNECTED" and outcome["newly_connected"]:
            case_repository.take_over_ownership(conn, tenant_id=tenant_id, case_id=outcome["case_id"], new_owner={"actor_kind": "HUMAN_MERCHANT", "actor_id": "transfer:" + transfer_id})
        return {"status": outcome["status"], "provider_result_ref": outcome["provider_result_ref"]}

    def receive_asynchronous_media(self, conn: Any, *, tenant_id: str, case_id: str, producer_ref: str, source_event_id: str, media_kind: str, asset_ref: str) -> bool:
        if media_kind not in {"AUDIO_MESSAGE", "IMAGE", "VIDEO", "DOCUMENT"}:
            raise VoiceStateConflict("unsupported asynchronous media kind")
        return voice_repository.receive_asynchronous_media(conn, tenant_id=tenant_id, intake_id=_id(), case_id=case_id, producer_ref=producer_ref, source_event_id=source_event_id, media_kind=media_kind, asset_ref=asset_ref)

    def set_media_status(self, conn: Any, *, tenant_id: str, intake_id: str, status: str) -> None:
        try:
            voice_repository.set_media_status(conn, tenant_id=tenant_id, intake_id=intake_id, status=status)
        except RuntimeError as exc:
            raise VoiceStateConflict(str(exc)) from exc

    def create_playback(self, conn: Any, *, tenant_id: str, session_id: str, demand_revision: int) -> str:
        playback_id = _id(); voice_repository.create_playback(conn, tenant_id=tenant_id, playback_id=playback_id, session_id=session_id, demand_revision=demand_revision); return playback_id

    def set_playback_status(self, conn: Any, *, tenant_id: str, playback_id: str, status: str) -> None:
        try: voice_repository.set_playback_status(conn, tenant_id=tenant_id, playback_id=playback_id, status=status)
        except RuntimeError as exc: raise VoiceStateConflict(str(exc)) from exc

    def create_payment_link_handoff(self, conn: Any, *, tenant_id: str, session_id: str, payment_link_ref: str, order_id: str | None = None) -> str:
        if not payment_link_is_safe(payment_link_ref):
            raise UnsafePaymentHandoff("voice flow may hand off a payment link, never card data")
        if not voice_repository.payment_handoff_context_valid(conn, tenant_id=tenant_id, session_id=session_id, order_id=order_id):
            raise PaymentHandoffOwnershipRejected("session must exist and order must belong to its case")
        handoff_id = _id()
        voice_repository.create_payment_handoff(conn, tenant_id=tenant_id, handoff_id=handoff_id, session_id=session_id, order_id=order_id, payment_link_ref=payment_link_ref)
        return handoff_id
