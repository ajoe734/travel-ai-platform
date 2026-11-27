"""Tenant-scoped persistence for ENG-10 voice and multimedia continuation."""
from __future__ import annotations

import json
from typing import Any

import psycopg

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
    row = conn.execute(f"UPDATE voice_session SET status=%s WHERE tenant_id=%s AND id=%s RETURNING {', '.join(_SESSION)}", (status, tenant_id, session_id)).fetchone()
    if row is None:
        raise ValueError("voice session not found")
    return row_as_dict(_SESSION, row)


def append_turn(conn: psycopg.Connection, *, tenant_id: str, turn_id: str, session_id: str, demand_revision: int, status: str, transcript_ref: str | None) -> None:
    turn_no = conn.execute("SELECT COALESCE(MAX(turn_no),0)+1 FROM voice_turn WHERE tenant_id=%s AND session_id=%s", (tenant_id, session_id)).fetchone()[0]
    conn.execute("INSERT INTO voice_turn (tenant_id,id,session_id,turn_no,demand_revision,status,transcript_ref) VALUES (%s,%s,%s,%s,%s,%s,%s)", (tenant_id, turn_id, session_id, turn_no, demand_revision, status, transcript_ref))


def interrupt_for_new_demand(conn: psycopg.Connection, *, tenant_id: str, session_id: str, prior_demand_revision: int) -> None:
    conn.execute("UPDATE voice_playback SET status='INTERRUPTED' WHERE tenant_id=%s AND session_id=%s AND demand_revision=%s AND status IN ('QUEUED','PLAYING')", (tenant_id, session_id, prior_demand_revision))
    conn.execute("UPDATE voice_turn SET status='SUPERSEDED' WHERE tenant_id=%s AND session_id=%s AND demand_revision=%s AND status IN ('PARTIAL','FINAL')", (tenant_id, session_id, prior_demand_revision))


def create_transfer(conn: psycopg.Connection, *, tenant_id: str, transfer_id: str, session_id: str, destination_ref: str) -> None:
    conn.execute("INSERT INTO voice_transfer (tenant_id,id,session_id,destination_ref,status) VALUES (%s,%s,%s,%s,'REQUESTED')", (tenant_id, transfer_id, session_id, destination_ref))


def set_transfer_status(conn: psycopg.Connection, *, tenant_id: str, transfer_id: str, status: str, provider_result_ref: str | None) -> dict[str, Any]:
    row = conn.execute("UPDATE voice_transfer SET status=%s, provider_result_ref=COALESCE(%s,provider_result_ref) WHERE tenant_id=%s AND id=%s RETURNING status,provider_result_ref", (status, provider_result_ref, tenant_id, transfer_id)).fetchone()
    if row is None:
        raise ValueError("voice transfer not found")
    return {"status": row[0], "provider_result_ref": row[1]}


def receive_asynchronous_media(conn: psycopg.Connection, *, tenant_id: str, intake_id: str, case_id: str, source_event_id: str, media_kind: str, asset_ref: str) -> bool:
    row = conn.execute("SELECT id FROM asynchronous_media_intake WHERE tenant_id=%s AND source_event_id=%s", (tenant_id, source_event_id)).fetchone()
    if row:
        return False
    conn.execute("INSERT INTO asynchronous_media_intake (tenant_id,id,case_id,source_event_id,media_kind,asset_ref,status) VALUES (%s,%s,%s,%s,%s,%s,'RECEIVED')", (tenant_id, intake_id, case_id, source_event_id, media_kind, asset_ref))
    return True


def create_payment_handoff(conn: psycopg.Connection, *, tenant_id: str, handoff_id: str, session_id: str, order_id: str | None, payment_link_ref: str) -> None:
    conn.execute("INSERT INTO voice_payment_handoff (tenant_id,id,session_id,order_id,payment_link_ref) VALUES (%s,%s,%s,%s,%s)", (tenant_id, handoff_id, session_id, order_id, payment_link_ref))
