"""Application boundary for ENG-11.

The caller supplies only results of a controlled query.  This service binds a
result hash to its query metadata, keeps hypotheses separate, and makes a
proposal usable by ENG-08 only after its required asset uses remain valid.
"""
from __future__ import annotations

import uuid
from urllib.parse import urlparse
from typing import Any

from db.repository import insight_repository as repo
from services.authorization import canonical_json
from services.authorization.temporal import is_at_or_before
from services.publication import PublicationService


class InsightError(ValueError):
    pass


def _id(value: str | None) -> str:
    return value or str(uuid.uuid4())


def _required_key(item: dict[str, Any]) -> str:
    """A requirement is its declared scope, not merely an optional file hash."""
    required = ("purpose", "channel", "language")
    if any(not isinstance(item.get(key), str) or not item[key].strip() for key in required):
        raise InsightError("MATERIAL_SCOPE_REQUIRED")
    if not item.get("content_hash") and (not isinstance(item.get("requirement_id"), str) or not item["requirement_id"].strip()):
        raise InsightError("MATERIAL_REQUIREMENT_ID_REQUIRED")
    return canonical_json.payload_hash({key: item.get(key) for key in ("requirement_id", "content_hash", *required)})


def _asset_matches_requirement(asset: dict[str, Any], requirement: dict[str, Any]) -> bool:
    return (asset.get("purpose") == requirement.get("purpose")
            and asset.get("channel") == requirement.get("channel")
            and asset.get("language") == requirement.get("language")
            and (not requirement.get("content_hash") or asset.get("content_hash") == requirement["content_hash"]))


def _safe_source_ref(source_ref: str) -> bool:
    parsed = urlparse(source_ref)
    if parsed.scheme not in ("http", "https"):
        return True  # durable provider/object references are not fetched here
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".localhost"):
        return False
    import ipaddress
    try:
        address = ipaddress.ip_address(host)
        return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)
    except ValueError:
        return True


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
        if any(not isinstance(value, str) or not value.strip() for value in (query_version, metric_key, case_dedupe_version)):
            raise InsightError("INSIGHT_REPRODUCIBILITY_METADATA_REQUIRED")
        if not all(isinstance(value, dict) and value for value in (numerator, denominator, coverage)):
            raise InsightError("INSIGHT_MEASURE_STRUCTURE_REQUIRED")
        # Hypotheses are recorded alongside a result, but must not alter the
        # identity of the controlled query result which they interpret.
        result = {"query_version": query_version, "metric_key": metric_key, "period_start": period_start, "period_end": period_end,
                  "numerator": numerator, "denominator": denominator, "coverage": coverage, "case_dedupe_version": case_dedupe_version,
                  "observed_facts": observed_facts, "evidence_refs": evidence_refs}
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
        for item in required_material:
            _required_key(item)
        return repo.create_proposal(conn, tenant_id=tenant_id, proposal_id=_id(proposal_id), case_id=case_id, work_id=work_id,
            insight_id=insight_id, evidence_refs=evidence_refs, hypothesis_refs=hypothesis_refs, content_diff=content_diff,
            cost_impact=cost_impact, shared_resource_impact=shared_resource_impact, required_material=required_material)

    def ask_missing_material(self, conn: Any, *, tenant_id: str, proposal_id: str, requested_channels: list[str], deadline: str | None,
                             now: str, request_id: str | None = None) -> list[dict[str, Any]]:
        proposal = repo.get_proposal(conn, tenant_id=tenant_id, proposal_id=proposal_id)
        if proposal is None:
            raise InsightError("PROPOSAL_NOT_FOUND")
        available = repo.find_usable_assets(conn, tenant_id=tenant_id, now=now)
        missing = [item for item in proposal["required_material"] if not any(_asset_matches_requirement(asset, item) for asset in available)]
        if missing:
            repo.create_material_request(conn, tenant_id=tenant_id, request_id=_id(request_id), proposal_id=proposal_id,
                required_items=missing, requested_channels=requested_channels, deadline=deadline)
        return missing

    def ingest_asset(self, conn: Any, *, tenant_id: str, source_scope: str, media_kind: str, source_ref: str, content_hash: str,
                     metadata: dict[str, Any], material_request_id: str | None = None, proposal_id: str | None = None,
                     parent_asset_id: str | None = None, asset_id: str | None = None) -> dict[str, Any]:
        if not source_ref or not _safe_source_ref(source_ref):
            raise InsightError("ASSET_SOURCE_REF_UNSAFE")
        return repo.create_asset(conn, tenant_id=tenant_id, asset_id=_id(asset_id), material_request_id=material_request_id,
            proposal_id=proposal_id, parent_asset_id=parent_asset_id, source_scope=source_scope, media_kind=media_kind,
            source_ref=source_ref, content_hash=content_hash, metadata=metadata)

    def record_scan(self, conn: Any, *, tenant_id: str, asset_id: str, accepted: bool) -> dict[str, Any]:
        asset = repo.get_asset(conn, tenant_id=tenant_id, asset_id=asset_id)
        if asset is None:
            raise InsightError("ASSET_NOT_FOUND")
        if asset["lifecycle_status"] not in ("RECEIVED", "CLARIFYING", "READY_FOR_REVIEW"):
            raise InsightError("ASSET_SCAN_STATE_INVALID")
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
        grant = repo.create_rights_grant(conn, tenant_id=tenant_id, grant_id=_id(grant_id), asset_id=asset_id, revision=repo.next_rights_revision(conn, tenant_id=tenant_id, asset_id=asset_id),
            rights_holder_ref=rights_holder_ref, purposes=purposes, channels=channels, languages=languages,
            effective_at=effective_at, expires_at=expires_at, approval_ref=approval_ref)
        repo.set_asset_scan(conn, tenant_id=tenant_id, asset_id=asset_id, scan_status="CHECKED", lifecycle_status="AVAILABLE")
        return grant

    def bind_asset_to_proposal(self, conn: Any, *, tenant_id: str, proposal_id: str, asset_id: str, rights_grant_id: str,
                               purpose: str, channel: str, language: str) -> None:
        asset, grant = repo.get_asset(conn, tenant_id=tenant_id, asset_id=asset_id), repo.get_rights_grant(conn, tenant_id=tenant_id, grant_id=rights_grant_id)
        if asset is None or grant is None or grant["asset_id"] != asset_id or asset["source_scope"] == "COMPLAINT_EVIDENCE" or asset["lifecycle_status"] != "AVAILABLE":
            raise InsightError("ASSET_USE_INVALID")
        if purpose not in grant["permitted_purposes"] or channel not in grant["permitted_channels"] or language not in grant["permitted_languages"]:
            raise InsightError("ASSET_RIGHTS_SCOPE_MISMATCH")
        repo.bind_asset_use(conn, tenant_id=tenant_id, proposal_id=proposal_id, asset_id=asset_id, rights_grant_id=rights_grant_id,
                            purpose=purpose, channel=channel, language=language)

    def revoke_asset(self, conn: Any, *, tenant_id: str, asset_id: str) -> dict[str, Any]:
        row = repo.revoke_asset(conn, tenant_id=tenant_id, asset_id=asset_id)
        if row is None:
            raise InsightError("ASSET_REVOKE_INVALID")
        return row

    def revoke_rights(self, conn: Any, *, tenant_id: str, rights_grant_id: str) -> dict[str, Any]:
        row = repo.revoke_rights_grant(conn, tenant_id=tenant_id, grant_id=rights_grant_id)
        if row is None:
            raise InsightError("RIGHTS_REVOKE_INVALID")
        return row

    def append_discussion(self, conn: Any, *, tenant_id: str, proposal_id: str, speaker: str, message_kind: str, body: dict[str, Any], source_refs: list[dict[str, Any]], message_id: str | None = None) -> int:
        return repo.append_discussion(conn, tenant_id=tenant_id, message_id=_id(message_id), proposal_id=proposal_id, speaker=speaker, message_kind=message_kind, body=body, source_refs=source_refs)

    def revise_proposal(self, conn: Any, *, tenant_id: str, proposal_id: str, expected_revision: int, content_diff: dict[str, Any], cost_impact: dict[str, Any], shared_resource_impact: dict[str, Any], required_material: list[dict[str, Any]]) -> dict[str, Any]:
        if not cost_impact or not shared_resource_impact:
            raise InsightError("COST_AND_SHARED_RESOURCE_IMPACT_REQUIRED")
        for item in required_material:
            _required_key(item)
        row = repo.revise_proposal(conn, tenant_id=tenant_id, proposal_id=proposal_id, expected_revision=expected_revision, content_diff=content_diff, cost_impact=cost_impact, shared_resource_impact=shared_resource_impact, required_material=required_material)
        if row is None:
            raise InsightError("PROPOSAL_VERSION_CONFLICT")
        return row

    def approve_proposal_for_service_version(self, conn: Any, *, tenant_id: str, proposal_id: str, expected_revision: int,
                                             now: str, base_content: dict[str, Any]) -> dict[str, Any]:
        proposal = repo.get_proposal(conn, tenant_id=tenant_id, proposal_id=proposal_id)
        if proposal is None or proposal["revision"] != expected_revision:
            raise InsightError("PROPOSAL_VERSION_CONFLICT")
        uses = repo.usable_asset_uses(conn, tenant_id=tenant_id, proposal_id=proposal_id, now=now)
        if proposal.get("status", "DISCUSSING") not in ("DISCUSSING", "VALIDATED", "AWAITING_APPROVAL"):
            raise InsightError("PROPOSAL_STATE_INVALID")
        if any(not any(_asset_matches_requirement(use, required) for use in uses) for required in proposal["required_material"]):
            raise InsightError("REQUIRED_MATERIAL_RIGHTS_MISSING")
        # This prepares exact version content; an ENG-03 ApprovalRecord and
        # PublicationService still own the APPROVED state and channel dispatch.
        approved = repo.update_proposal_status(conn, tenant_id=tenant_id, proposal_id=proposal_id, expected_revision=expected_revision, status="AWAITING_APPROVAL", allowed_statuses=("DISCUSSING", "VALIDATED"))
        if approved is None:
            raise InsightError("PROPOSAL_VERSION_CONFLICT")
        content = dict(base_content)
        content.update(proposal["content_diff"])
        content["eng11_proposal"] = {"proposal_id": proposal_id, "proposal_revision": approved["revision"], "cost_impact": proposal["cost_impact"],
            "shared_resource_impact": proposal["shared_resource_impact"], "asset_uses": uses}
        return content

    def create_and_prepare_publications(self, conn: Any, *, tenant_id: str, proposal_id: str, expected_revision: int,
                                        now: str, base_content: dict[str, Any], service_id: str, version: int,
                                        approval_id: str, targets: list[dict[str, str]], base_version: int | None = None,
                                        publication_service: PublicationService | None = None) -> dict[str, Any]:
        """Bridge a material-complete proposal into the ENG-03/ENG-08 pipeline.

        The service version is never created from a conversational status: the
        caller must supply the durable ApprovalRecord id, which ENG-08 verifies
        against exact content and each channel scope before dispatch rows exist.
        """
        content = self.approve_proposal_for_service_version(conn, tenant_id=tenant_id, proposal_id=proposal_id,
            expected_revision=expected_revision, now=now, base_content=base_content)
        publication_service = publication_service or PublicationService()
        version_id = publication_service.create_approved_version(conn, tenant_id=tenant_id, service_id=service_id,
            version=version, content=content, approval_id=approval_id, now=now, base_version=base_version, base_content=base_content)
        intents, blocked = publication_service.prepare_publications(conn, tenant_id=tenant_id, service_version_id=version_id,
            service_version=version, targets=targets, now=now)
        approved = repo.update_proposal_status(conn, tenant_id=tenant_id, proposal_id=proposal_id,
            expected_revision=expected_revision + 1, status="APPROVED", allowed_statuses=("AWAITING_APPROVAL",))
        if approved is None:
            raise InsightError("PROPOSAL_VERSION_CONFLICT")
        return {"service_version_id": version_id, "publication_intents": intents, "blocked_publications": blocked, "proposal": approved}
