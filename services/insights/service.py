"""Application boundary for ENG-11.

The caller supplies only results of a controlled query.  This service binds a
result hash to its query metadata, keeps hypotheses separate, and makes a
proposal usable by ENG-08 only after its required asset uses remain valid.
"""
from __future__ import annotations

import uuid
from typing import Any

from db.repository import insight_repository as repo
from services.authorization import canonical_json
from services.authorization.temporal import is_at_or_before


class InsightError(ValueError):
    pass


def _id(value: str | None) -> str:
    return value or str(uuid.uuid4())


class InsightService:
    def record_observation(self, conn: Any, *, tenant_id: str, case_id: str, query_version: str, metric_key: str,
                           period_start: str, period_end: str, numerator: dict[str, Any], denominator: dict[str, Any],
                           coverage: dict[str, Any], case_dedupe_version: str, observed_facts: list[dict[str, Any]],
                           hypotheses: list[dict[str, Any]], evidence_refs: list[dict[str, Any]], insight_id: str | None = None) -> dict[str, Any]:
        if is_at_or_before(period_end, period_start):
            raise InsightError("INSIGHT_PERIOD_INVALID")
        if any(not fact.get("source_ref") for fact in observed_facts):
            raise InsightError("OBSERVED_FACT_SOURCE_REQUIRED")
        if any("source_ref" in hypothesis for hypothesis in hypotheses):
            raise InsightError("HYPOTHESIS_MUST_NOT_MASQUERADE_AS_FACT")
        result = {"query_version": query_version, "metric_key": metric_key, "period_start": period_start, "period_end": period_end,
                  "numerator": numerator, "denominator": denominator, "coverage": coverage, "case_dedupe_version": case_dedupe_version,
                  "observed_facts": observed_facts, "hypotheses": hypotheses, "evidence_refs": evidence_refs}
        return repo.create_insight(conn, tenant_id=tenant_id, insight_id=_id(insight_id), case_id=case_id, query_version=query_version,
            metric_key=metric_key, period_start=period_start, period_end=period_end, numerator=numerator, denominator=denominator,
            coverage=coverage, case_dedupe_version=case_dedupe_version, observed_facts=observed_facts, hypotheses=hypotheses,
            evidence_refs=evidence_refs, result_hash=canonical_json.payload_hash(result))

    def propose_change(self, conn: Any, *, tenant_id: str, case_id: str, work_id: str, insight_id: str | None,
                       evidence_refs: list[dict[str, Any]], hypothesis_refs: list[dict[str, Any]], content_diff: dict[str, Any],
                       cost_impact: dict[str, Any], shared_resource_impact: dict[str, Any], required_material: list[dict[str, Any]],
                       proposal_id: str | None = None) -> dict[str, Any]:
        if not evidence_refs and not hypothesis_refs:
            raise InsightError("PROPOSAL_EVIDENCE_OR_HYPOTHESIS_REQUIRED")
        if not cost_impact or not shared_resource_impact:
            raise InsightError("COST_AND_SHARED_RESOURCE_IMPACT_REQUIRED")
        return repo.create_proposal(conn, tenant_id=tenant_id, proposal_id=_id(proposal_id), case_id=case_id, work_id=work_id,
            insight_id=insight_id, evidence_refs=evidence_refs, hypothesis_refs=hypothesis_refs, content_diff=content_diff,
            cost_impact=cost_impact, shared_resource_impact=shared_resource_impact, required_material=required_material)

    def ask_missing_material(self, conn: Any, *, tenant_id: str, proposal_id: str, requested_channels: list[str], deadline: str | None,
                             now: str, request_id: str | None = None) -> list[dict[str, Any]]:
        proposal = repo.get_proposal(conn, tenant_id=tenant_id, proposal_id=proposal_id)
        if proposal is None:
            raise InsightError("PROPOSAL_NOT_FOUND")
        available = repo.usable_asset_uses(conn, tenant_id=tenant_id, proposal_id=proposal_id, now=now)
        available_hashes = {item["content_hash"] for item in available}
        missing = [item for item in proposal["required_material"] if item.get("content_hash") not in available_hashes]
        if missing:
            repo.create_material_request(conn, tenant_id=tenant_id, request_id=_id(request_id), proposal_id=proposal_id,
                required_items=missing, requested_channels=requested_channels, deadline=deadline)
        return missing

    def ingest_asset(self, conn: Any, *, tenant_id: str, source_scope: str, media_kind: str, source_ref: str, content_hash: str,
                     metadata: dict[str, Any], material_request_id: str | None = None, proposal_id: str | None = None,
                     parent_asset_id: str | None = None, asset_id: str | None = None) -> dict[str, Any]:
        return repo.create_asset(conn, tenant_id=tenant_id, asset_id=_id(asset_id), material_request_id=material_request_id,
            proposal_id=proposal_id, parent_asset_id=parent_asset_id, source_scope=source_scope, media_kind=media_kind,
            source_ref=source_ref, content_hash=content_hash, metadata=metadata)

    def record_scan(self, conn: Any, *, tenant_id: str, asset_id: str, accepted: bool) -> dict[str, Any]:
        row = repo.set_asset_scan(conn, tenant_id=tenant_id, asset_id=asset_id, scan_status="CHECKED" if accepted else "REJECTED",
                                  lifecycle_status="READY_FOR_REVIEW" if accepted else "REJECTED")
        if row is None:
            raise InsightError("ASSET_NOT_FOUND")
        return row

    def approve_rights(self, conn: Any, *, tenant_id: str, asset_id: str, rights_holder_ref: str, purposes: list[str], channels: list[str],
                       languages: list[str], effective_at: str, expires_at: str | None, approval_ref: str, grant_id: str | None = None) -> dict[str, Any]:
        asset = repo.get_asset(conn, tenant_id=tenant_id, asset_id=asset_id)
        if asset is None:
            raise InsightError("ASSET_NOT_FOUND")
        if asset["source_scope"] == "COMPLAINT_EVIDENCE":
            raise InsightError("COMPLAINT_ASSET_MARKETING_PROHIBITED")
        if asset["scan_status"] != "CHECKED":
            raise InsightError("ASSET_SCAN_REQUIRED")
        if not approval_ref or not purposes or not channels or not languages:
            raise InsightError("RIGHTS_SCOPE_AND_APPROVAL_REQUIRED")
        grant = repo.create_rights_grant(conn, tenant_id=tenant_id, grant_id=_id(grant_id), asset_id=asset_id, revision=1,
            rights_holder_ref=rights_holder_ref, purposes=purposes, channels=channels, languages=languages,
            effective_at=effective_at, expires_at=expires_at, approval_ref=approval_ref)
        repo.set_asset_scan(conn, tenant_id=tenant_id, asset_id=asset_id, scan_status="CHECKED", lifecycle_status="AVAILABLE")
        return grant

    def bind_asset_to_proposal(self, conn: Any, *, tenant_id: str, proposal_id: str, asset_id: str, rights_grant_id: str,
                               purpose: str, channel: str, language: str) -> None:
        repo.bind_asset_use(conn, tenant_id=tenant_id, proposal_id=proposal_id, asset_id=asset_id, rights_grant_id=rights_grant_id,
                            purpose=purpose, channel=channel, language=language)

    def approve_proposal_for_service_version(self, conn: Any, *, tenant_id: str, proposal_id: str, expected_revision: int,
                                             now: str, base_content: dict[str, Any]) -> dict[str, Any]:
        proposal = repo.get_proposal(conn, tenant_id=tenant_id, proposal_id=proposal_id)
        if proposal is None or proposal["revision"] != expected_revision:
            raise InsightError("PROPOSAL_VERSION_CONFLICT")
        uses = repo.usable_asset_uses(conn, tenant_id=tenant_id, proposal_id=proposal_id, now=now)
        required_hashes = {item.get("content_hash") for item in proposal["required_material"] if item.get("content_hash")}
        if not required_hashes.issubset({item["content_hash"] for item in uses}):
            raise InsightError("REQUIRED_MATERIAL_RIGHTS_MISSING")
        approved = repo.update_proposal_status(conn, tenant_id=tenant_id, proposal_id=proposal_id, expected_revision=expected_revision, status="APPROVED")
        if approved is None:
            raise InsightError("PROPOSAL_VERSION_CONFLICT")
        content = dict(base_content)
        content.update(proposal["content_diff"])
        content["eng11_proposal"] = {"proposal_id": proposal_id, "proposal_revision": approved["revision"], "cost_impact": proposal["cost_impact"],
            "shared_resource_impact": proposal["shared_resource_impact"], "asset_uses": uses}
        return content
