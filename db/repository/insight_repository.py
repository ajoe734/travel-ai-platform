"""Tenant-scoped persistence for ENG-11 observations, proposals and assets.

The repository stores facts without turning them into causality claims.  It
also never treats receipt or a virus scan as a publication entitlement.
"""
from __future__ import annotations

import json
from typing import Any

from .rows import row_as_dict


def _one(conn: Any, sql: str, columns: list[str], values: tuple[Any, ...]) -> dict[str, Any] | None:
    row = conn.execute(sql, values).fetchone()
    return row_as_dict(columns, row) if row else None


_INSIGHT = ["tenant_id", "id", "case_id", "query_version", "metric_key", "period_start", "period_end", "numerator", "denominator", "coverage", "case_dedupe_version", "observed_facts", "hypotheses", "evidence_refs", "result_hash"]
_PROPOSAL = ["tenant_id", "id", "case_id", "work_id", "insight_id", "revision", "status", "evidence_refs", "hypothesis_refs", "content_diff", "cost_impact", "shared_resource_impact", "required_material"]
_ASSET = ["tenant_id", "id", "material_request_id", "proposal_id", "parent_asset_id", "source_scope", "media_kind", "source_ref", "content_hash", "scan_status", "lifecycle_status", "metadata"]
_RIGHTS = ["tenant_id", "id", "asset_id", "revision", "rights_holder_ref", "permitted_purposes", "permitted_channels", "permitted_languages", "effective_at", "expires_at", "status", "approval_ref"]


def create_insight(conn: Any, *, tenant_id: str, insight_id: str, case_id: str, query_version: str, metric_key: str,
                   period_start: str, period_end: str, numerator: dict[str, Any], denominator: dict[str, Any],
                   coverage: dict[str, Any], case_dedupe_version: str, observed_facts: list[dict[str, Any]],
                   hypotheses: list[dict[str, Any]], evidence_refs: list[dict[str, Any]], result_hash: str) -> dict[str, Any]:
    return _one(conn, """INSERT INTO operating_insight (tenant_id,id,case_id,query_version,metric_key,period_start,period_end,numerator,denominator,coverage,case_dedupe_version,observed_facts,hypotheses,evidence_refs,result_hash)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING tenant_id,id,case_id,query_version,metric_key,period_start,period_end,numerator,denominator,coverage,case_dedupe_version,observed_facts,hypotheses,evidence_refs,result_hash""", _INSIGHT,
        (tenant_id, insight_id, case_id, query_version, metric_key, period_start, period_end, json.dumps(numerator), json.dumps(denominator), json.dumps(coverage), case_dedupe_version, json.dumps(observed_facts), json.dumps(hypotheses), json.dumps(evidence_refs), result_hash))


def create_proposal(conn: Any, *, tenant_id: str, proposal_id: str, case_id: str, work_id: str, insight_id: str | None,
                    evidence_refs: list[dict[str, Any]], hypothesis_refs: list[dict[str, Any]], content_diff: dict[str, Any],
                    cost_impact: dict[str, Any], shared_resource_impact: dict[str, Any], required_material: list[dict[str, Any]]) -> dict[str, Any]:
    return _one(conn, """INSERT INTO change_proposal (tenant_id,id,case_id,work_id,insight_id,status,evidence_refs,hypothesis_refs,content_diff,cost_impact,shared_resource_impact,required_material)
        VALUES (%s,%s,%s,%s,%s,'DISCUSSING',%s,%s,%s,%s,%s,%s) RETURNING tenant_id,id,case_id,work_id,insight_id,revision,status,evidence_refs,hypothesis_refs,content_diff,cost_impact,shared_resource_impact,required_material""", _PROPOSAL,
        (tenant_id, proposal_id, case_id, work_id, insight_id, json.dumps(evidence_refs), json.dumps(hypothesis_refs), json.dumps(content_diff), json.dumps(cost_impact), json.dumps(shared_resource_impact), json.dumps(required_material)))


def get_proposal(conn: Any, *, tenant_id: str, proposal_id: str) -> dict[str, Any] | None:
    return _one(conn, "SELECT tenant_id,id,case_id,work_id,insight_id,revision,status,evidence_refs,hypothesis_refs,content_diff,cost_impact,shared_resource_impact,required_material FROM change_proposal WHERE tenant_id=%s AND id=%s", _PROPOSAL, (tenant_id, proposal_id))


def append_discussion(conn: Any, *, tenant_id: str, message_id: str, proposal_id: str, speaker: str, message_kind: str,
                      body: dict[str, Any], source_refs: list[dict[str, Any]]) -> int:
    # Serialize sequence allocation per proposal.  A MAX()+1 aggregate alone
    # races because an empty child set has no row for FOR UPDATE to lock.
    conn.execute("SELECT id FROM change_proposal WHERE tenant_id=%s AND id=%s FOR UPDATE", (tenant_id, proposal_id))
    row = conn.execute("""INSERT INTO merchant_discussion_message (tenant_id,id,proposal_id,sequence,speaker,message_kind,body,source_refs)
       SELECT %s,%s,%s,COALESCE(MAX(sequence),0)+1,%s,%s,%s,%s FROM merchant_discussion_message WHERE tenant_id=%s AND proposal_id=%s RETURNING sequence""",
       (tenant_id, message_id, proposal_id, speaker, message_kind, json.dumps(body), json.dumps(source_refs), tenant_id, proposal_id)).fetchone()
    return row[0]


def create_material_request(conn: Any, *, tenant_id: str, request_id: str, proposal_id: str, required_items: list[dict[str, Any]],
                            requested_channels: list[str], deadline: str | None) -> None:
    conn.execute("INSERT INTO material_request (tenant_id,id,proposal_id,required_items,requested_channels,status,deadline) VALUES (%s,%s,%s,%s,%s,'REQUESTED',%s)",
                 (tenant_id, request_id, proposal_id, json.dumps(required_items), json.dumps(requested_channels), deadline))


def create_asset(conn: Any, *, tenant_id: str, asset_id: str, material_request_id: str | None, proposal_id: str | None,
                 parent_asset_id: str | None, source_scope: str, media_kind: str, source_ref: str, content_hash: str,
                 metadata: dict[str, Any]) -> dict[str, Any]:
    return _one(conn, """INSERT INTO asset (tenant_id,id,material_request_id,proposal_id,parent_asset_id,source_scope,media_kind,source_ref,content_hash,scan_status,lifecycle_status,metadata)
       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'RECEIVED','RECEIVED',%s) RETURNING tenant_id,id,material_request_id,proposal_id,parent_asset_id,source_scope,media_kind,source_ref,content_hash,scan_status,lifecycle_status,metadata""", _ASSET,
       (tenant_id, asset_id, material_request_id, proposal_id, parent_asset_id, source_scope, media_kind, source_ref, content_hash, json.dumps(metadata)))


def set_asset_scan(conn: Any, *, tenant_id: str, asset_id: str, scan_status: str, lifecycle_status: str) -> dict[str, Any] | None:
    return _one(conn, """UPDATE asset SET scan_status=%s,lifecycle_status=%s WHERE tenant_id=%s AND id=%s
       RETURNING tenant_id,id,material_request_id,proposal_id,parent_asset_id,source_scope,media_kind,source_ref,content_hash,scan_status,lifecycle_status,metadata""", _ASSET, (scan_status, lifecycle_status, tenant_id, asset_id))


def get_asset(conn: Any, *, tenant_id: str, asset_id: str) -> dict[str, Any] | None:
    return _one(conn, "SELECT tenant_id,id,material_request_id,proposal_id,parent_asset_id,source_scope,media_kind,source_ref,content_hash,scan_status,lifecycle_status,metadata FROM asset WHERE tenant_id=%s AND id=%s", _ASSET, (tenant_id, asset_id))


def create_rights_grant(conn: Any, *, tenant_id: str, grant_id: str, asset_id: str, revision: int, rights_holder_ref: str,
                        purposes: list[str], channels: list[str], languages: list[str], effective_at: str, expires_at: str | None,
                        approval_ref: str) -> dict[str, Any]:
    return _one(conn, """INSERT INTO asset_rights_grant (tenant_id,id,asset_id,revision,rights_holder_ref,permitted_purposes,permitted_channels,permitted_languages,effective_at,expires_at,status,approval_ref)
       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'APPROVED',%s) RETURNING tenant_id,id,asset_id,revision,rights_holder_ref,permitted_purposes,permitted_channels,permitted_languages,effective_at,expires_at,status,approval_ref""", _RIGHTS,
       (tenant_id, grant_id, asset_id, revision, rights_holder_ref, json.dumps(purposes), json.dumps(channels), json.dumps(languages), effective_at, expires_at, approval_ref))


def next_rights_revision(conn: Any, *, tenant_id: str, asset_id: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM asset_rights_grant WHERE tenant_id=%s AND asset_id=%s", (tenant_id, asset_id)).fetchone()
    return int(row[0])


def get_rights_grant(conn: Any, *, tenant_id: str, grant_id: str) -> dict[str, Any] | None:
    return _one(conn, "SELECT tenant_id,id,asset_id,revision,rights_holder_ref,permitted_purposes,permitted_channels,permitted_languages,effective_at,expires_at,status,approval_ref FROM asset_rights_grant WHERE tenant_id=%s AND id=%s", _RIGHTS, (tenant_id, grant_id))


def revoke_asset(conn: Any, *, tenant_id: str, asset_id: str) -> dict[str, Any] | None:
    return _one(conn, "UPDATE asset SET lifecycle_status='REVOKED' WHERE tenant_id=%s AND id=%s AND lifecycle_status NOT IN ('REVOKED','REJECTED') RETURNING tenant_id,id,material_request_id,proposal_id,parent_asset_id,source_scope,media_kind,source_ref,content_hash,scan_status,lifecycle_status,metadata", _ASSET, (tenant_id, asset_id))


def revoke_rights_grant(conn: Any, *, tenant_id: str, grant_id: str) -> dict[str, Any] | None:
    return _one(conn, "UPDATE asset_rights_grant SET status='REVOKED' WHERE tenant_id=%s AND id=%s AND status='APPROVED' RETURNING tenant_id,id,asset_id,revision,rights_holder_ref,permitted_purposes,permitted_channels,permitted_languages,effective_at,expires_at,status,approval_ref", _RIGHTS, (tenant_id, grant_id))


def bind_asset_use(conn: Any, *, tenant_id: str, proposal_id: str, asset_id: str, rights_grant_id: str, purpose: str, channel: str, language: str) -> None:
    conn.execute("INSERT INTO proposal_asset_use (tenant_id,proposal_id,asset_id,rights_grant_id,purpose,channel,language) VALUES (%s,%s,%s,%s,%s,%s,%s)", (tenant_id, proposal_id, asset_id, rights_grant_id, purpose, channel, language))


def usable_asset_uses(conn: Any, *, tenant_id: str, proposal_id: str, now: str) -> list[dict[str, Any]]:
    rows = conn.execute("""WITH RECURSIVE ancestry AS (
          SELECT a.tenant_id,a.id AS leaf_id,a.id,a.parent_asset_id,a.source_scope,a.lifecycle_status FROM asset a
          JOIN proposal_asset_use u ON (u.tenant_id=a.tenant_id AND u.asset_id=a.id)
          WHERE u.tenant_id=%s AND u.proposal_id=%s
          UNION ALL SELECT parent.tenant_id,child.leaf_id,parent.id,parent.parent_asset_id,parent.source_scope,parent.lifecycle_status
          FROM asset parent JOIN ancestry child ON (parent.tenant_id=child.tenant_id AND parent.id=child.parent_asset_id)
       ) SELECT u.asset_id,u.rights_grant_id,u.purpose,u.channel,u.language,a.content_hash
       FROM proposal_asset_use u JOIN asset a ON (a.tenant_id=u.tenant_id AND a.id=u.asset_id)
       JOIN asset_rights_grant r ON (r.tenant_id=u.tenant_id AND r.id=u.rights_grant_id AND r.asset_id=u.asset_id)
       WHERE u.tenant_id=%s AND u.proposal_id=%s AND a.scan_status='CHECKED' AND a.lifecycle_status='AVAILABLE'
         AND a.source_scope <> 'COMPLAINT_EVIDENCE' AND r.status='APPROVED' AND r.effective_at<=%s
         AND (r.expires_at IS NULL OR r.expires_at>%s) AND r.permitted_purposes ? u.purpose
         AND r.permitted_channels ? u.channel AND r.permitted_languages ? u.language
         AND NOT EXISTS (SELECT 1 FROM ancestry x WHERE x.leaf_id=a.id AND (x.source_scope='COMPLAINT_EVIDENCE' OR x.lifecycle_status IN ('REVOKED','EXPIRED','REJECTED')))""", (tenant_id, proposal_id, now, now)).fetchall()
    return [row_as_dict(["asset_id","rights_grant_id","purpose","channel","language","content_hash"], row) for row in rows]


def find_usable_assets(conn: Any, *, tenant_id: str, now: str) -> list[dict[str, Any]]:
    """Tenant-wide catalog search used before asking a merchant for another file."""
    rows = conn.execute("""WITH RECURSIVE ancestry AS (
         SELECT tenant_id,id AS leaf_id,id,parent_asset_id,source_scope,lifecycle_status FROM asset WHERE tenant_id=%s
         UNION ALL SELECT parent.tenant_id,child.leaf_id,parent.id,parent.parent_asset_id,parent.source_scope,parent.lifecycle_status
         FROM asset parent JOIN ancestry child ON (parent.tenant_id=child.tenant_id AND parent.id=child.parent_asset_id)
       ) SELECT a.id,r.id,a.content_hash,purpose.value AS purpose,channel.value AS channel,language.value AS language
       FROM asset a JOIN asset_rights_grant r ON (r.tenant_id=a.tenant_id AND r.asset_id=a.id)
       CROSS JOIN LATERAL jsonb_array_elements_text(r.permitted_purposes) purpose
       CROSS JOIN LATERAL jsonb_array_elements_text(r.permitted_channels) channel
       CROSS JOIN LATERAL jsonb_array_elements_text(r.permitted_languages) language
       WHERE a.tenant_id=%s AND a.scan_status='CHECKED' AND a.lifecycle_status='AVAILABLE'
         AND a.source_scope <> 'COMPLAINT_EVIDENCE' AND r.status='APPROVED' AND r.effective_at<=%s
         AND (r.expires_at IS NULL OR r.expires_at>%s)
         AND NOT EXISTS (SELECT 1 FROM ancestry x WHERE x.tenant_id=a.tenant_id AND x.leaf_id=a.id AND (x.source_scope='COMPLAINT_EVIDENCE' OR x.lifecycle_status IN ('REVOKED','EXPIRED','REJECTED')))""", (tenant_id, tenant_id, now, now)).fetchall()
    return [row_as_dict(["asset_id","rights_grant_id","content_hash","purpose","channel","language"], row) for row in rows]


def update_proposal_status(conn: Any, *, tenant_id: str, proposal_id: str, expected_revision: int, status: str, allowed_statuses: tuple[str, ...]) -> dict[str, Any] | None:
    return _one(conn, """UPDATE change_proposal SET status=%s,revision=revision+1 WHERE tenant_id=%s AND id=%s AND revision=%s AND status = ANY(%s)
       RETURNING tenant_id,id,case_id,work_id,insight_id,revision,status,evidence_refs,hypothesis_refs,content_diff,cost_impact,shared_resource_impact,required_material""", _PROPOSAL, (status, tenant_id, proposal_id, expected_revision, list(allowed_statuses)))


def revise_proposal(conn: Any, *, tenant_id: str, proposal_id: str, expected_revision: int, content_diff: dict[str, Any], cost_impact: dict[str, Any], shared_resource_impact: dict[str, Any], required_material: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _one(conn, """UPDATE change_proposal SET content_diff=%s,cost_impact=%s,shared_resource_impact=%s,required_material=%s,status='DISCUSSING',revision=revision+1
       WHERE tenant_id=%s AND id=%s AND revision=%s AND status IN ('DISCUSSING','VALIDATED','AWAITING_APPROVAL')
       RETURNING tenant_id,id,case_id,work_id,insight_id,revision,status,evidence_refs,hypothesis_refs,content_diff,cost_impact,shared_resource_impact,required_material""", _PROPOSAL, (json.dumps(content_diff), json.dumps(cost_impact), json.dumps(shared_resource_impact), json.dumps(required_material), tenant_id, proposal_id, expected_revision))
