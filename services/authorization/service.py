"""AuthorizationService: the ENG-03 授權判定服務 and DecisionRequest API logic.

Implements docs/sd/authorization-and-approval.md end to end on top of the
in-memory repository: DecisionRequest create/propose-revision/approve/reject/
expire, canonical payload hashing (canonical_json.py), ApprovalRecord and
ApprovalRevocation issuance, ExecutionAuthorization issuance from either a
policy grant or an approval, AuthorizationUse consumption, and the
pre-dispatch recheck + revoke/dispatch race ordering (SD §6).

Every public method here maps 1:1 to an endpoint in
specs/authorization/api-contract.md; that document is the "DecisionRequest
API" deliverable, this module is what a future HTTP handler (ENG-05 scope)
calls into.

Design rule enforced throughout (backlog ENG-03 acceptance: "不得以模型文字或
前端旗標授權交易"): nothing here accepts a bare client-asserted
"approved"/"accepted" boolean. ``approve_decision`` only honors a
confirmation nonce this service itself issued from ``create_decision`` /
``propose_revision`` — i.e. one that was handed to a trusted UI confirmation
endpoint or voice confirmation service, never synthesized by a model or a
front-end flag (SD §1, SD-A-01).
"""
from __future__ import annotations

import uuid
from typing import Any, Callable

from . import canonical_json, schema_validation
from .errors import (
    actor_role_mismatch,
    authorization_revoked,
    authorization_scope_mismatch,
    authorization_stale,
    authorization_use_already_bound,
    cross_tenant_rejected,
    idempotency_conflict,
    policy_approval_required,
    revocation_not_permitted,
    unverified_approval_rejected,
    version_conflict,
)
from .repository import InMemoryAuthorizationRepository

REQUIRED_CANONICAL_PAYLOAD_FIELDS = (
    # SD §3.1 "批准 payload 至少包含" checklist, operationalized as field names.
    # amount/currency, beneficiary_or_commodity, cost_bearer and
    # asset_usage_and_rights_version are conditional ("適用時") and not
    # required here; everything else in the prose list is mandatory.
    "schema_version",
    "canonicalization_version",
    "tenant_id",
    "purpose",
    "target_type",
    "target_id",
    "target_revision",
    "work_id",
    "operation",
    "service_or_policy_version",
    "expires_at",
    "data_purpose",
    "manifest_items",
    "customer_impact",
    "required_consent_refs",
)


def _default_id_factory() -> str:
    return str(uuid.uuid4())


def validate_canonical_payload(payload: dict[str, Any]) -> None:
    """Raise ValueError listing any SD §3.1 mandatory field missing from ``payload``.

    This is a service-level business rule on top of (not a replacement for)
    decision-request.schema.json's generic ``display_payload`` shape, which
    deliberately leaves the payload's internal fields open so each
    decision_type can carry its own content.
    """
    missing = [f for f in REQUIRED_CANONICAL_PAYLOAD_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"display_payload is missing required SD §3.1 fields: {missing}")
    if payload["canonicalization_version"] != canonical_json.CANONICALIZATION_VERSION:
        raise ValueError(
            f"display_payload.canonicalization_version must be {canonical_json.CANONICALIZATION_VERSION!r}"
        )


class AuthorizationService:
    def __init__(
        self,
        repository: InMemoryAuthorizationRepository,
        id_factory: Callable[[], str] = _default_id_factory,
    ) -> None:
        self.repository = repository
        self._new_id = id_factory

    # -- DecisionRequest lifecycle (SD §4) --------------------------------------

    def create_decision(
        self,
        *,
        tenant_id: str,
        work_id: dict[str, Any],
        decision_type: str,
        options: list[dict[str, Any]],
        display_payload: dict[str, Any],
        target_revision: int,
        expires_at: str,
        requested_role: str,
        created_at: str,
        context_refs: list[dict[str, Any]] | None = None,
        id: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        if display_payload.get("tenant_id") != tenant_id:
            raise cross_tenant_rejected("display_payload.tenant_id does not match the requesting tenant")
        validate_canonical_payload(display_payload)
        decision: dict[str, Any] = {
            "tenant_id": tenant_id,
            "id": id or self._new_id(),
            "work_id": work_id,
            "decision_type": decision_type,
            "revision": 1,
            "status": "PENDING",
            "options": options,
            "payload_hash": canonical_json.payload_hash(display_payload),
            "canonicalization_version": canonical_json.CANONICALIZATION_VERSION,
            "display_payload": display_payload,
            "target_revision": target_revision,
            "expires_at": expires_at,
            "requested_role": requested_role,
            "created_at": created_at,
        }
        if context_refs:
            decision["context_refs"] = context_refs
        schema_validation.validate("DecisionRequest", decision)
        self.repository.put_decision(decision)
        nonce_id = self.repository.issue_nonce(tenant_id, decision["id"], 1, decision["payload_hash"])
        return decision, nonce_id

    def propose_revision(
        self,
        *,
        tenant_id: str,
        decision_id: str,
        expected_revision: int,
        decision_type: str,
        options: list[dict[str, Any]],
        display_payload: dict[str, Any],
        target_revision: int,
        expires_at: str,
        requested_role: str,
        created_at: str,
        context_refs: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        current = self.repository.get_decision_latest(tenant_id, decision_id)
        if current is None:
            raise cross_tenant_rejected("decision not found in this tenant")
        if current["revision"] != expected_revision or current["status"] != "PENDING":
            raise version_conflict(
                f"decision {decision_id} is at revision {current['revision']} ({current['status']}), "
                f"not the expected PENDING revision {expected_revision}"
            )
        if display_payload.get("tenant_id") != tenant_id:
            raise cross_tenant_rejected("display_payload.tenant_id does not match the requesting tenant")
        validate_canonical_payload(display_payload)
        self.repository.update_decision_status(tenant_id, decision_id, expected_revision, "SUPERSEDED")
        new_revision = expected_revision + 1
        decision: dict[str, Any] = {
            "tenant_id": tenant_id,
            "id": decision_id,
            "work_id": current["work_id"],
            "decision_type": decision_type,
            "revision": new_revision,
            "status": "PENDING",
            "options": options,
            "payload_hash": canonical_json.payload_hash(display_payload),
            "canonicalization_version": canonical_json.CANONICALIZATION_VERSION,
            "display_payload": display_payload,
            "target_revision": target_revision,
            "expires_at": expires_at,
            "requested_role": requested_role,
            "created_at": created_at,
        }
        if context_refs:
            decision["context_refs"] = context_refs
        schema_validation.validate("DecisionRequest", decision)
        self.repository.put_decision(decision)
        nonce_id = self.repository.issue_nonce(tenant_id, decision_id, new_revision, decision["payload_hash"])
        return decision, nonce_id

    def approve_decision(
        self,
        *,
        tenant_id: str,
        decision_id: str,
        expected_revision: int,
        selected_option_id: str,
        nonce_id: str,
        approved_by: dict[str, Any],
        verified_actor_ref: str,
        scope_manifest: list[dict[str, Any]],
        approved_at: str,
        idempotency_key: str,
        if_match_revision: int | None = None,
        policy_version: str | None = None,
        expires_at: str | None = None,
        confirmation_evidence: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        if if_match_revision is not None and if_match_revision != expected_revision:
            raise version_conflict("expected_revision and If-Match ETag disagree; refusing to guess which applies")

        request_hash = canonical_json.payload_hash(
            {
                "decision_id": decision_id,
                "reviewed_revision": expected_revision,
                "selected_option_id": selected_option_id,
                "scope_manifest": sorted(scope_manifest, key=lambda item: item["item_id"]),
            }
        )
        idem = self.repository.get_idempotency(tenant_id, approved_by["actor_id"], "approve_decision", idempotency_key)
        if idem is not None:
            if idem["request_hash"] != request_hash:
                raise idempotency_conflict(
                    "Idempotency-Key reused with different amount/content/tenant for approve_decision"
                )
            return self.repository.get_approval(tenant_id, idem["result_ref"]["id"])  # SD-A-03 replay

        decision = self.repository.get_decision_latest(tenant_id, decision_id)
        if decision is None:
            raise cross_tenant_rejected("decision not found in this tenant")
        if decision["revision"] != expected_revision:
            raise authorization_stale(
                f"decision {decision_id} is now at revision {decision['revision']}, not {expected_revision}"
            )
        if decision["status"] != "PENDING":
            raise version_conflict(f"decision {decision_id} revision {expected_revision} is already {decision['status']}")

        nonce = self.repository.consume_nonce(nonce_id)
        if nonce is None:
            raise unverified_approval_rejected(
                "approve_decision requires a confirmation nonce issued by create_decision/propose_revision "
                "through a trusted UI or voice confirmation flow; no model text or client flag substitutes for it"
            )
        if nonce["tenant_id"] != tenant_id or nonce["decision_id"] != decision_id:
            raise unverified_approval_rejected("confirmation nonce was not issued for this tenant/decision")
        if nonce["revision"] != expected_revision or nonce["payload_hash"] != decision["payload_hash"]:
            raise authorization_stale("confirmation nonce is bound to a superseded display content")

        if approved_by["actor_kind"] != decision["requested_role"]:
            raise actor_role_mismatch(
                f"decision requires requested_role={decision['requested_role']!r}, "
                f"approved_by.actor_kind={approved_by['actor_kind']!r}"
            )
        option_ids = {o["option_id"] for o in decision["options"]}
        if selected_option_id not in option_ids:
            raise ValueError(f"selected_option_id {selected_option_id!r} is not one of {sorted(option_ids)}")

        approval: dict[str, Any] = {
            "tenant_id": tenant_id,
            "id": approval_id or self._new_id(),
            "decision_id": {"tenant_id": tenant_id, "id": decision_id},
            "reviewed_revision": expected_revision,
            "approved_by": approved_by,
            "verified_actor_ref": verified_actor_ref,
            "approved_payload": decision["display_payload"],
            "canonicalization_version": canonical_json.CANONICALIZATION_VERSION,
            "payload_hash": decision["payload_hash"],
            "scope_manifest": scope_manifest,
            "approved_at": approved_at,
        }
        if policy_version is not None:
            approval["policy_version"] = policy_version
        if expires_at is not None:
            approval["expires_at"] = expires_at
        if confirmation_evidence is not None:
            approval["confirmation_evidence"] = confirmation_evidence
        schema_validation.validate("ApprovalRecord", approval)

        stored, created = self.repository.put_approval_if_absent(approval)
        if not created and stored["id"] != approval["id"]:
            # UNIQUE(tenant_id, decision_id, reviewed_revision): a concurrent approve under a
            # different Idempotency-Key already landed between our PENDING check and here.
            raise version_conflict(f"decision {decision_id} revision {expected_revision} was already approved")

        if created:
            self.repository.update_decision_status(tenant_id, decision_id, expected_revision, "APPROVED", selected_option_id)
            self.repository.put_idempotency(
                tenant_id, approved_by["actor_id"], "approve_decision", idempotency_key, request_hash, {"id": stored["id"]}
            )
        return stored

    def reject_decision(
        self,
        *,
        tenant_id: str,
        decision_id: str,
        expected_revision: int,
        selected_option_id: str,
        rejected_by: dict[str, Any],
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_hash = canonical_json.payload_hash(
            {
                "decision_id": decision_id,
                "revision": expected_revision,
                "selected_option_id": selected_option_id,
                "reason": reason,
            }
        )
        idem = self.repository.get_idempotency(tenant_id, rejected_by["actor_id"], "reject_decision", idempotency_key)
        if idem is not None:
            if idem["request_hash"] != request_hash:
                raise idempotency_conflict("Idempotency-Key reused with different content for reject_decision")
            return self.repository.get_decision_revision(tenant_id, decision_id, idem["result_ref"]["revision"])

        decision = self.repository.get_decision_latest(tenant_id, decision_id)
        if decision is None:
            raise cross_tenant_rejected("decision not found in this tenant")
        if decision["revision"] != expected_revision:
            raise authorization_stale(
                f"decision {decision_id} is now at revision {decision['revision']}, not {expected_revision}"
            )
        if decision["status"] != "PENDING":
            raise version_conflict(f"decision {decision_id} revision {expected_revision} is already {decision['status']}")
        if rejected_by["actor_kind"] != decision["requested_role"]:
            raise actor_role_mismatch(
                f"decision requires requested_role={decision['requested_role']!r}, "
                f"rejected_by.actor_kind={rejected_by['actor_kind']!r}"
            )
        option_ids = {o["option_id"] for o in decision["options"]}
        if selected_option_id not in option_ids:
            raise ValueError(f"selected_option_id {selected_option_id!r} is not one of {sorted(option_ids)}")

        updated = self.repository.update_decision_status(tenant_id, decision_id, expected_revision, "REJECTED", selected_option_id)
        self.repository.put_idempotency(
            tenant_id, rejected_by["actor_id"], "reject_decision", idempotency_key, request_hash,
            {"decision_id": decision_id, "revision": expected_revision},
        )
        return updated

    def expire_decisions(self, *, tenant_id: str, now: str) -> list[dict[str, Any]]:
        expired = []
        for decision in self.repository.list_pending_decisions(tenant_id):
            if decision["expires_at"] <= now:
                expired.append(
                    self.repository.update_decision_status(tenant_id, decision["id"], decision["revision"], "EXPIRED")
                )
        return expired

    # -- ExecutionAuthorization (SD §1/§5) ----------------------------------------

    def issue_execution_authorization(
        self,
        *,
        tenant_id: str,
        work_id: dict[str, Any],
        root_business_key: str,
        capabilities: list[str],
        manifest: list[dict[str, Any]],
        issued_at: str,
        now: str,
        resource_refs: list[dict[str, Any]] | None = None,
        grant_refs: list[dict[str, Any]] | None = None,
        approval_refs: list[dict[str, Any]] | None = None,
        consent_refs: list[dict[str, Any]] | None = None,
        policy_versions: list[str] | None = None,
        expiry: str | None = None,
        id: str | None = None,
    ) -> dict[str, Any]:
        if not grant_refs and not approval_refs:
            raise policy_approval_required(
                "ExecutionAuthorization needs at least one of grant_refs (policy) or approval_refs (decision)"
            )
        for ref in approval_refs or []:
            if ref["tenant_id"] != tenant_id:
                raise cross_tenant_rejected("approval_refs entry belongs to a different tenant")
            approval = self.repository.get_approval(tenant_id, ref["id"])
            if approval is None:
                raise cross_tenant_rejected("approval not found in this tenant")
            if not self.repository.is_approval_effective(tenant_id, ref["id"], now):
                raise authorization_revoked(f"approval {ref['id']} has been revoked")
            allowed_operations = {item["operation"] for item in approval["scope_manifest"]}
            for item in manifest:
                if item["operation"] not in allowed_operations:
                    raise authorization_scope_mismatch(
                        f"manifest item {item['item_id']!r} operation {item['operation']!r} is outside "
                        f"approval {ref['id']}'s scope_manifest"
                    )
        for ref in grant_refs or []:
            if ref["tenant_id"] != tenant_id:
                raise cross_tenant_rejected("grant_refs entry belongs to a different tenant")
            grant = self.repository.get_grant(tenant_id, ref["id"])
            if grant is None:
                raise cross_tenant_rejected("grant not found in this tenant")
            if grant.get("revoked") or grant["expiry"] <= now:
                raise authorization_revoked(f"grant {ref['id']} is revoked or expired")
            for capability in capabilities:
                if capability not in grant.get("capabilities", []):
                    raise policy_approval_required(f"grant {ref['id']} does not cover capability {capability!r}")

        sorted_manifest = sorted(manifest, key=lambda item: item["item_id"])
        authorization: dict[str, Any] = {
            "tenant_id": tenant_id,
            "id": id or self._new_id(),
            "work_id": work_id,
            "root_business_key": root_business_key,
            "capabilities": capabilities,
            "manifest_hash": canonical_json.payload_hash(sorted_manifest),
            "issued_at": issued_at,
        }
        if resource_refs:
            authorization["resource_refs"] = resource_refs
        if grant_refs:
            authorization["grant_refs"] = grant_refs
        if consent_refs:
            authorization["consent_refs"] = consent_refs
        if approval_refs:
            authorization["approval_refs"] = approval_refs
        if policy_versions:
            authorization["policy_versions"] = policy_versions
        if expiry:
            authorization["expiry"] = expiry
        schema_validation.validate("ExecutionAuthorization", authorization)

        # Budget is consumed only after everything else has already succeeded,
        # so a rejected request never burns a reusable grant's period budget.
        for ref in grant_refs or []:
            self.repository.consume_grant_budget(tenant_id, ref["id"])

        self.repository.put_authorization(authorization)
        return authorization

    def try_issue_policy_covered_authorization(
        self,
        *,
        tenant_id: str,
        work_id: dict[str, Any],
        root_business_key: str,
        capabilities: list[str],
        manifest: list[dict[str, Any]],
        issued_at: str,
        now: str,
        expiry: str | None = None,
    ) -> dict[str, Any] | None:
        """Backlog ENG-03 acceptance / SD-A-10: skip the manual decision entirely
        when a reusable grant already covers every requested capability.
        Returns None (never raises) when no covering grant exists, so the
        caller falls back to create_decision/approve_decision."""
        grant_refs = []
        for capability in capabilities:
            grant = self.repository.find_covering_grant(tenant_id, capability, now)
            if grant is None:
                return None
            grant_refs.append({"tenant_id": tenant_id, "id": grant["id"]})
        return self.issue_execution_authorization(
            tenant_id=tenant_id,
            work_id=work_id,
            root_business_key=root_business_key,
            capabilities=capabilities,
            manifest=manifest,
            grant_refs=grant_refs,
            issued_at=issued_at,
            now=now,
            expiry=expiry,
        )

    # -- AuthorizationUse + pre-dispatch recheck (SD §5/§6) -----------------------

    def _check_authorization_still_valid(self, tenant_id: str, authorization: dict[str, Any], now: str) -> None:
        if authorization.get("expiry") and authorization["expiry"] <= now:
            raise authorization_stale(f"authorization {authorization['id']} expired at {authorization['expiry']}")
        for ref in authorization.get("approval_refs", []):
            if not self.repository.is_approval_effective(tenant_id, ref["id"], now):
                raise authorization_revoked(f"approval {ref['id']} backing this authorization has been revoked")
        for ref in authorization.get("grant_refs", []):
            grant = self.repository.get_grant(tenant_id, ref["id"])
            if grant is not None and grant.get("revoked"):
                raise authorization_revoked(f"grant {ref['id']} backing this authorization has been revoked")

    def consume_authorization_use(
        self,
        *,
        tenant_id: str,
        authorization_id: str,
        root_task_id: dict[str, Any],
        root_business_key: str,
        request_hash: str,
        used_at: str,
        now: str,
    ) -> dict[str, Any]:
        with self.repository.lock_for(tenant_id, authorization_id):
            authorization = self.repository.get_authorization(tenant_id, authorization_id)
            if authorization is None:
                raise cross_tenant_rejected("authorization not found in this tenant")
            self._check_authorization_still_valid(tenant_id, authorization, now)

            existing = self.repository.get_authorization_use(tenant_id, authorization_id)
            if existing is not None:
                if existing["root_task_id"]["id"] == root_task_id["id"]:
                    return existing  # SD-A-06: resend finds the same use, not a new one
                raise authorization_use_already_bound(
                    f"authorization {authorization_id} already consumed by root task "
                    f"{existing['root_task_id']['id']}; cannot bind a second root"
                )

            use: dict[str, Any] = {
                "tenant_id": tenant_id,
                "id": self._new_id(),
                "authorization_id": {"tenant_id": tenant_id, "id": authorization_id},
                "root_task_id": root_task_id,
                "root_business_key": root_business_key,
                "request_hash": request_hash,
                "used_at": used_at,
            }
            schema_validation.validate("AuthorizationUse", use)
            stored, _created = self.repository.put_authorization_use_if_absent(tenant_id, authorization_id, use)
            return stored

    def precheck_before_dispatch(self, *, tenant_id: str, authorization_id: str, now: str) -> None:
        """SD §6: "worker 發出前持有效 lease/fence，再確認沒有已生效的撤回及目標版衝突".

        Call this immediately before the first (and every retried) external
        call for a root task. Raises AuthorizationError and the caller must
        not call out externally if it does.
        """
        with self.repository.lock_for(tenant_id, authorization_id):
            authorization = self.repository.get_authorization(tenant_id, authorization_id)
            if authorization is None:
                raise cross_tenant_rejected("authorization not found in this tenant")
            self._check_authorization_still_valid(tenant_id, authorization, now)

    def mark_dispatched(self, *, tenant_id: str, authorization_id: str, now: str) -> None:
        """Record that a worker actually sent the external call, under the same
        root lock precheck_before_dispatch/revoke_approval use, so revoke can
        tell whether it won the race against dispatch (SD §6)."""
        with self.repository.lock_for(tenant_id, authorization_id):
            self.repository.mark_dispatched(tenant_id, authorization_id, now)

    def is_approval_effective(self, *, tenant_id: str, approval_id: str, at: str) -> bool:
        return self.repository.is_approval_effective(tenant_id, approval_id, at)

    # -- ApprovalRevocation (SD §2/§6, ADR 0003) -----------------------------------

    def revoke_approval(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        revoked_by: dict[str, Any],
        reason: str,
        effective_at: str,
        created_at: str,
        id: str | None = None,
    ) -> dict[str, Any]:
        approval = self.repository.get_approval(tenant_id, approval_id)
        if approval is None:
            raise cross_tenant_rejected("approval not found in this tenant")
        if revoked_by["actor_kind"] not in ("EMPLOYEE", "SYSTEM"):
            raise revocation_not_permitted(f"actor_kind {revoked_by['actor_kind']!r} may not revoke an approval")

        revocation: dict[str, Any] = {
            "tenant_id": tenant_id,
            "id": id or self._new_id(),
            "approval_id": {"tenant_id": tenant_id, "id": approval_id},
            "revoked_by": revoked_by,
            "reason": reason,
            "effective_at": effective_at,
            "created_at": created_at,
        }
        schema_validation.validate("ApprovalRevocation", revocation)
        stored, created = self.repository.put_revocation_if_absent(tenant_id, approval_id, revocation)

        affected: list[dict[str, Any]] = []
        if created:
            for authorization in self.repository.find_authorizations_referencing_approval(tenant_id, approval_id):
                auth_id = authorization["id"]
                with self.repository.lock_for(tenant_id, auth_id):
                    if self.repository.is_dispatched(tenant_id, auth_id):
                        # SD §6: already sent externally; revoke only blocks *new* dispatch
                        # attempts from here on (enforced by precheck_before_dispatch), the
                        # action already in flight proceeds to reconciliation (ENG-05 scope).
                        affected.append({"authorization_id": auth_id, "outcome": "DISPATCHED_PROCEEDS_TO_RECONCILIATION"})
                    else:
                        affected.append({"authorization_id": auth_id, "outcome": "NOT_YET_DISPATCHED_BLOCKED"})
        return {"revocation": stored, "resent": not created, "affected_authorizations": affected}
