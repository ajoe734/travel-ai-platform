"""Tenant-scoped persistence for ENG-10 voice and multimedia continuation."""
from __future__ import annotations

import json
import hashlib
from typing import Any

import psycopg

from .errors import IdempotencyConflict
from .rows import row_as_dict

_SESSION = ["tenant_id", "id", "case_id", "transport", "provider_session_ref", "status", "recording_policy", "recording_status", "case_owner_revision", "created_at", "updated_at"]


def create_session(conn: psycopg.Connection, *, tenant_id: str, session_id: str, case_id: str, transport: str, provider_session_ref: str, recording_policy: dict[str, Any], recording_status: str, case_owner_revision: int) -> dict[str, Any]:
    row = conn.execute(
        f"""INSERT INTO voice_session (tenant_id,id,case_id,transport,provider_session_ref,status,recording_policy,recording_status,case_owner_revision)
            VALUES (%s,%s,%s,%s,%s,'CONNECTING',%s,%s,%s) RETURNING {', '.join(_SESSION)}""",
        (tenant_id, session_id, case_id, transport, provider_session_ref, json.dumps(recording_policy), recording_status, case_owner_revision),
    ).fetchone()
    return row_as_dict(_SESSION, row)


def get_session(conn: psycopg.Connection, *, tenant_id: str, session_id: str) -> dict[str, Any] | None:
    row = conn.execute(f"SELECT {', '.join(_SESSION)} FROM voice_session WHERE tenant_id=%s AND id=%s", (tenant_id, session_id)).fetchone()
    return row_as_dict(_SESSION, row) if row else None


def set_session_status(conn: psycopg.Connection, *, tenant_id: str, session_id: str, status: str) -> dict[str, Any]:
    current = conn.execute(f"SELECT {', '.join(_SESSION)} FROM voice_session WHERE tenant_id=%s AND id=%s FOR UPDATE", (tenant_id, session_id)).fetchone()
    if current is None:
        raise LookupError("voice session not found")
    current_status = current[5]
    allowed = {"CONNECTING": {"ACTIVE", "CLOSED"}, "ACTIVE": {"TRANSFERRING", "DISCONNECTED", "CLOSED"}, "TRANSFERRING": {"ACTIVE", "DISCONNECTED", "CLOSED"}, "DISCONNECTED": {"ACTIVE", "CLOSED"}, "CLOSED": set()}
    if status not in allowed[current_status]:
        raise RuntimeError(f"invalid voice session transition {current_status}->{status}")
    row = conn.execute(f"UPDATE voice_session SET status=%s WHERE tenant_id=%s AND id=%s RETURNING {', '.join(_SESSION)}", (status, tenant_id, session_id)).fetchone()
    if row is None:
        raise ValueError("voice session not found")
    return row_as_dict(_SESSION, row)


def set_recording_status(conn: psycopg.Connection, *, tenant_id: str, session_id: str, status: str) -> None:
    row = conn.execute("SELECT recording_status FROM voice_session WHERE tenant_id=%s AND id=%s FOR UPDATE", (tenant_id, session_id)).fetchone()
    allowed = {"NOT_REQUESTED": {"NOTICE_GIVEN"}, "NOTICE_GIVEN": {"DECLINED", "RECORDING"}, "RECORDING": {"REDACTED"}, "DECLINED": set(), "REDACTED": set()}
    if row is None or status not in allowed[row[0]]:
        raise RuntimeError("invalid recording transition")
    conn.execute("UPDATE voice_session SET recording_status=%s WHERE tenant_id=%s AND id=%s", (status, tenant_id, session_id))


def append_turn(conn: psycopg.Connection, *, tenant_id: str, turn_id: str, session_id: str, demand_revision: int, status: str, transcript_ref: str | None) -> None:
    conn.execute("SELECT id FROM voice_session WHERE tenant_id=%s AND id=%s FOR UPDATE", (tenant_id, session_id)).fetchone()
    turn_no = conn.execute("SELECT COALESCE(MAX(turn_no),0)+1 FROM voice_turn WHERE tenant_id=%s AND session_id=%s", (tenant_id, session_id)).fetchone()[0]
    conn.execute("INSERT INTO voice_turn (tenant_id,id,session_id,turn_no,demand_revision,status,transcript_ref) VALUES (%s,%s,%s,%s,%s,%s,%s)", (tenant_id, turn_id, session_id, turn_no, demand_revision, status, transcript_ref))


def interrupt_for_new_demand(conn: psycopg.Connection, *, tenant_id: str, session_id: str, prior_demand_revision: int) -> None:
    conn.execute("UPDATE voice_playback SET status='INTERRUPTED' WHERE tenant_id=%s AND session_id=%s AND demand_revision=%s AND status IN ('QUEUED','PLAYING')", (tenant_id, session_id, prior_demand_revision))
    conn.execute("UPDATE voice_turn SET status='SUPERSEDED' WHERE tenant_id=%s AND session_id=%s AND demand_revision=%s AND status IN ('PARTIAL','FINAL','CONFIRMED')", (tenant_id, session_id, prior_demand_revision))


def create_playback(conn: psycopg.Connection, *, tenant_id: str, playback_id: str, session_id: str, demand_revision: int) -> None:
    conn.execute("INSERT INTO voice_playback (tenant_id,id,session_id,demand_revision,status) VALUES (%s,%s,%s,%s,'QUEUED')", (tenant_id, playback_id, session_id, demand_revision))


def set_playback_status(conn: psycopg.Connection, *, tenant_id: str, playback_id: str, status: str) -> None:
    row = conn.execute("SELECT status FROM voice_playback WHERE tenant_id=%s AND id=%s FOR UPDATE", (tenant_id, playback_id)).fetchone()
    allowed = {"QUEUED": {"PLAYING", "INTERRUPTED"}, "PLAYING": {"PLAYED", "INTERRUPTED"}, "PLAYED": set(), "INTERRUPTED": set()}
    if row is None or status not in allowed[row[0]]:
        raise RuntimeError("invalid playback transition")
    conn.execute("UPDATE voice_playback SET status=%s WHERE tenant_id=%s AND id=%s", (status, tenant_id, playback_id))


def create_transfer(conn: psycopg.Connection, *, tenant_id: str, transfer_id: str, session_id: str, destination_ref: str) -> None:
    conn.execute("INSERT INTO voice_transfer (tenant_id,id,session_id,destination_ref,status) VALUES (%s,%s,%s,%s,'REQUESTED')", (tenant_id, transfer_id, session_id, destination_ref))


def set_transfer_status(conn: psycopg.Connection, *, tenant_id: str, transfer_id: str, status: str, provider_result_ref: str | None) -> dict[str, Any]:
    current = conn.execute("SELECT status FROM voice_transfer WHERE tenant_id=%s AND id=%s FOR UPDATE", (tenant_id, transfer_id)).fetchone()
    allowed = {"REQUESTED": {"RINGING", "FAILED"}, "RINGING": {"CONNECTED", "FAILED"}, "CONNECTED": set(), "FAILED": set()}
    if current is None or status not in allowed[current[0]]:
        raise RuntimeError("invalid transfer transition")
    row = conn.execute("UPDATE voice_transfer SET status=%s, provider_result_ref=COALESCE(%s,provider_result_ref) WHERE tenant_id=%s AND id=%s RETURNING status,provider_result_ref", (status, provider_result_ref, tenant_id, transfer_id)).fetchone()
    if row is None:
        raise ValueError("voice transfer not found")
    return {"status": row[0], "provider_result_ref": row[1]}


def receive_asynchronous_media(conn: psycopg.Connection, *, tenant_id: str, intake_id: str, case_id: str, producer_ref: str, source_event_id: str, media_kind: str, asset_ref: str) -> bool:
    payload_hash = hashlib.sha256(f"{case_id}|{media_kind}|{asset_ref}".encode()).hexdigest()
    row = conn.execute("""INSERT INTO asynchronous_media_intake (tenant_id,id,case_id,producer_ref,source_event_id,media_kind,asset_ref,payload_hash,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'RECEIVED') ON CONFLICT (tenant_id,producer_ref,source_event_id) DO NOTHING RETURNING id""", (tenant_id, intake_id, case_id, producer_ref, source_event_id, media_kind, asset_ref, payload_hash)).fetchone()
    if row:
        return True
    existing = conn.execute("SELECT payload_hash FROM asynchronous_media_intake WHERE tenant_id=%s AND producer_ref=%s AND source_event_id=%s FOR UPDATE", (tenant_id, producer_ref, source_event_id)).fetchone()
    if existing and existing[0] == payload_hash:
        return False
    raise IdempotencyConflict("producer/source event is already bound to a different media payload")


def set_media_status(conn: psycopg.Connection, *, tenant_id: str, intake_id: str, status: str) -> None:
    row = conn.execute("SELECT status FROM asynchronous_media_intake WHERE tenant_id=%s AND id=%s FOR UPDATE", (tenant_id, intake_id)).fetchone()
    allowed = {"RECEIVED": {"SCANNING", "REJECTED"}, "SCANNING": {"READY", "REJECTED"}, "READY": set(), "REJECTED": set()}
    if row is None or status not in allowed[row[0]]:
        raise RuntimeError("invalid media transition")
    conn.execute("UPDATE asynchronous_media_intake SET status=%s WHERE tenant_id=%s AND id=%s", (status, tenant_id, intake_id))


def create_resume_challenge(conn: psycopg.Connection, *, tenant_id: str, challenge_id: str, session_id: str, proof: str, expires_at: str) -> None:
    conn.execute("INSERT INTO voice_resume_challenge (tenant_id,id,session_id,proof_hash,expires_at) VALUES (%s,%s,%s,%s,%s)", (tenant_id, challenge_id, session_id, hashlib.sha256(proof.encode()).hexdigest(), expires_at))


def consume_resume_challenge(conn: psycopg.Connection, *, tenant_id: str, challenge_id: str, session_id: str, proof: str) -> bool:
    row = conn.execute("SELECT proof_hash,expires_at,failed_attempts,consumed_at,locked_at FROM voice_resume_challenge WHERE tenant_id=%s AND id=%s AND session_id=%s FOR UPDATE", (tenant_id, challenge_id, session_id)).fetchone()
    if row is None or row[3] is not None or row[4] is not None or row[1] <= conn.execute("SELECT now()").fetchone()[0]: return False
    if row[0] == hashlib.sha256(proof.encode()).hexdigest():
        conn.execute("UPDATE voice_resume_challenge SET consumed_at=now() WHERE tenant_id=%s AND id=%s", (tenant_id, challenge_id)); return True
    conn.execute("UPDATE voice_resume_challenge SET failed_attempts=failed_attempts+1, locked_at=CASE WHEN failed_attempts+1 >= 5 THEN now() END WHERE tenant_id=%s AND id=%s", (tenant_id, challenge_id)); return False


def payment_handoff_context_valid(conn: psycopg.Connection, *, tenant_id: str, session_id: str, order_id: str | None) -> bool:
    row = conn.execute("SELECT s.case_id, o.case_id FROM voice_session s LEFT JOIN order_record o ON o.tenant_id=s.tenant_id AND o.id=%s WHERE s.tenant_id=%s AND s.id=%s", (order_id, tenant_id, session_id)).fetchone()
    return row is not None and (order_id is None or row[0] == row[1])


def create_payment_handoff(conn: psycopg.Connection, *, tenant_id: str, handoff_id: str, session_id: str, order_id: str | None, payment_link_ref: str) -> None:
    conn.execute("INSERT INTO voice_payment_handoff (tenant_id,id,session_id,order_id,payment_link_ref) VALUES (%s,%s,%s,%s,%s)", (tenant_id, handoff_id, session_id, order_id, payment_link_ref))
