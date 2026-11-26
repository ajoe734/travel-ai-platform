"""ENG-06 merchant workbench service.

Implements the backlog.md#eng-06 flow -- 商家工作清單、補資料、決策卡、執行進度、
完成證據 -- directly on top of the ENG-01 domain contracts
(specs/domain/work.schema.json, execution-task.schema.json,
decision-request.schema.json) and the ENG-04 connector SDK
(connectors/mocks/ota_delayed_publication.py), instead of the UX 2.1
prototype's client-held localStorage state and setTimeout-simulated
execution (docs/verification/prototype-audit.md §6).

Boundary, same disclosure pattern as services/authorization on claude/eng-03:
- Persistence is services/workbench/repository.py's in-memory store, an
  explicit placeholder pending ENG-02.
- ApprovalRecord / ExecutionAuthorization / AuthorizationUse (the reusable,
  cross-Work authorization objects in docs/sd/authorization-and-approval.md)
  are ENG-03 scope. This service drives a Work's own DecisionRequest
  directly; it does not fabricate an ApprovalRecord to stand in for that
  pipeline.
- Who may call propose_service_revision/submit_missing_input/request_decision
  /submit_decision for a given tenant/case (authn/session/role) is a caller
  concern; this service only checks tenant_id matches and, for
  submit_decision, that requested_role is respected by the caller -- it does
  not itself authenticate actor.

advance_execution() stands in for a durable worker tick (ENG-05 scope once a
real scheduler exists). It is never called by, or on behalf of, a single
merchant click -- backlog ENG-06 acceptance: 正常工作不用商家逐步按執行按鈕.

Known simplification: a tick collapses ExecutionTask NEW->VALIDATING->READY
->EXECUTING into one step instead of three separate short transactions with
their own outbox/lease/fence (SD work-execution-contract.md §4/§6.3). There
is no persisted lease/fence or multi-worker contention control here; that is
ENG-02/05 scope. This service is scoped to getting the Work/DecisionRequest
/ExecutionTask *state* and merchant-visible progress right against the
ENG-01 contracts, not to the durable-executor concurrency story.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from connectors.base import Connector
from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock
from connectors.types import Failed, OperationResult, Pending, Succeeded, Unknown

from . import canonical_json, schema_validation
from .errors import (
    AuthorizationStaleError,
    CrossTenantReferenceRejectedError,
    DecisionNotPendingError,
    DecisionOptionUnknownError,
    InvalidServiceRevisionFieldError,
    MissingRequiredInputError,
    WorkNotFoundError,
    WorkPhaseMismatchError,
)
from .repository import WorkbenchRepository


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

SYSTEM_ACTOR = {"actor_kind": "SYSTEM", "actor_id": "00000000-0000-4000-8000-000000000000"}

_CHANNEL_DISPLAY_STATE = {
    "NEW": "not_started",
    "VALIDATING": "not_started",
    "READY": "not_started",
    "EXECUTING": "pending",
    "WAITING": "pending",
    "UNKNOWN": "pending",
    "DONE": "live",
    "FAILED": "rejected",
    "CANCELLED": "cancelled",
}


def _new_id() -> str:
    return str(uuid.uuid4())


def _ref(tenant_id: str, id_: str) -> dict:
    return {"tenant_id": tenant_id, "id": id_}


def _missing_fields(draft: dict) -> list[str]:
    if not draft.get("asset_ref") and not draft.get("asset_waived"):
        return ["asset_ref", "rights_confirmed"]
    if draft.get("asset_ref") and not draft.get("rights_confirmed"):
        return ["rights_confirmed"]
    return []


class WorkbenchService:
    def __init__(self, repository: WorkbenchRepository | None = None, connector: Connector | None = None) -> None:
        self._repo = repository or WorkbenchRepository()
        self._connector = connector or OtaDelayedPublicationMock()

    # -- Propose a new service revision (UX 2.1 discuss()) -----------------
    def propose_service_revision(self, tenant_id: str, case_id: dict, actor: dict, now: str, due_at: str, merchant_text: str, fields: dict) -> dict:
        if case_id.get("tenant_id") != tenant_id:
            raise CrossTenantReferenceRejectedError(
                "case_id belongs to a different tenant than the caller (SD-W-03 cross-tenant reference rejection)"
            )
        if fields.get("content") != merchant_text:
            raise InvalidServiceRevisionFieldError(
                "fields['content'] must equal the merchant's own text verbatim; a service must never substitute a "
                "canned example or a rewritten summary (backlog ENG-06 acceptance: 模型解析出的內容可核對且不被固定範例覆蓋)"
            )
        if any(key in fields for key in ("asset_ref", "asset_waived", "rights_confirmed")):
            raise InvalidServiceRevisionFieldError(
                "asset_ref/asset_waived/rights_confirmed are supplied later via submit_missing_input, not at proposal time"
            )
        self._validate_bounds(fields)
        work_id = _new_id()
        work = {
            "tenant_id": tenant_id,
            "id": work_id,
            "case_id": case_id,
            "work_type": "SERVICE_REVISION",
            "objective": f"核准並發布服務改版：{fields['name']}",
            "completion_contract_version": "service-revision-completion-v1",
            "completion_conditions": [
                {"condition_id": f"channel_{channel.lower()}_live", "description": f"{channel} 讀回已核准版本並確認生效", "satisfied": False}
                for channel in fields["channels"]
            ],
            "principal": actor,
            "status": "WAITING_INPUT",
            "revision": 1,
            "waiting_input": {"missing_fields": ["asset_ref", "rights_confirmed"], "requested_from": actor, "due_at": due_at},
            "created_at": now,
            "updated_at": now,
        }
        schema_validation.validate_work(work)
        self._repo.put_work(work)
        self._repo.put_draft(tenant_id, work_id, fields)
        return work

    # -- Provide missing material (UX 2.1 material()) -----------------------
    def submit_missing_input(
        self,
        tenant_id: str,
        work_id: str,
        now: str,
        asset_ref: str | None = None,
        asset_waived: bool = False,
        rights_confirmed: bool = False,
    ) -> dict:
        work = self._require_work(tenant_id, work_id)
        if work["status"] != "WAITING_INPUT":
            raise WorkPhaseMismatchError(f"Work is {work['status']}, not WAITING_INPUT")
        if asset_ref is not None and asset_waived:
            raise InvalidServiceRevisionFieldError("asset_ref and asset_waived must not both be provided in the same call")
        if asset_ref == "":
            raise InvalidServiceRevisionFieldError("asset_ref must not be an empty string; omit it or use asset_waived instead")
        draft = self._repo.get_draft(tenant_id, work_id)
        if draft is None:
            raise WorkNotFoundError(f"no pending proposal draft for work {work_id}")
        if asset_ref is not None:
            draft["asset_ref"] = asset_ref
            draft.pop("asset_waived", None)
            # A newly supplied asset carries no rights confirmation of its
            # own; a stale rights_confirmed=True left over from a previous,
            # different asset_ref must not leak onto this one.
            draft["rights_confirmed"] = bool(rights_confirmed)
        elif asset_waived:
            draft["asset_waived"] = True
            draft.pop("asset_ref", None)
            draft.pop("rights_confirmed", None)
        elif rights_confirmed:
            draft["rights_confirmed"] = True
        draft.setdefault("rights_confirmed", False)
        self._repo.put_draft(tenant_id, work_id, draft)
        # work.schema.json requires waiting_input.missing_fields to stay
        # non-empty while status=WAITING_INPUT; once the draft is actually
        # complete there is nothing truthful left to put there, so this
        # snapshot is only ever updated while something genuinely remains
        # missing. The live answer merchants and get_home_view see comes
        # from _missing_fields(draft), not from this field -- see
        # get_home_view below (backlog ENG-06: status text must match
        # actual state, docs/verification/prototype-audit.md §9).
        still_missing = _missing_fields(draft)
        if still_missing:
            work["waiting_input"]["missing_fields"] = still_missing
        work["updated_at"] = now
        schema_validation.validate_work(work)
        self._repo.put_work(work)
        return work

    # -- Turn a complete proposal into a decision card (UX 2.1 review()) ----
    def request_decision(self, tenant_id: str, work_id: str, now: str, expires_at: str) -> tuple[dict, dict]:
        work = self._require_work(tenant_id, work_id)
        if work["status"] != "WAITING_INPUT":
            raise WorkPhaseMismatchError(f"Work is {work['status']}, not WAITING_INPUT")
        draft = self._repo.get_draft(tenant_id, work_id)
        if draft is None:
            raise WorkNotFoundError(f"no pending proposal draft for work {work_id}")
        missing = _missing_fields(draft)
        if missing:
            raise MissingRequiredInputError(f"still missing: {missing}")
        schema_validation.validate_service_revision(draft)

        decision = {
            "tenant_id": tenant_id,
            "id": _new_id(),
            "work_id": _ref(tenant_id, work_id),
            "decision_type": "SERVICE_REVISION_APPROVAL",
            "revision": 1,
            "status": "PENDING",
            "options": [
                {"option_id": "approve", "description": f"核准並發布至 {'、'.join(draft['channels'])}"},
                {"option_id": "defer", "description": "先不核准，維持原服務"},
            ],
            "display_payload": dict(draft),
            "payload_hash": canonical_json.decision_payload_hash(draft),
            "canonicalization_version": canonical_json.CANONICALIZATION_VERSION,
            "target_revision": work["revision"],
            "expires_at": expires_at,
            "requested_role": "MERCHANT_OWNER",
            "created_at": now,
        }
        schema_validation.validate_decision_request(decision)
        self._repo.put_decision(decision)

        work["status"] = "WAITING_DECISION"
        work.pop("waiting_input", None)
        work["waiting_decision"] = {"decision_ref": _ref(tenant_id, decision["id"])}
        work["revision"] += 1
        work["updated_at"] = now
        schema_validation.validate_work(work)
        self._repo.put_work(work)
        return work, decision

    # -- Merchant decides (UX 2.1 approve()) ---------------------------------
    def submit_decision(
        self,
        tenant_id: str,
        decision_id: str,
        now: str,
        selected_option_id: str,
        if_match_revision: int,
        if_match_payload_hash: str,
    ) -> dict:
        decision = self._repo.get_decision(tenant_id, decision_id)
        if decision is None:
            raise WorkNotFoundError(f"no decision {decision_id}")
        if decision["status"] != "PENDING":
            raise DecisionNotPendingError(f"decision is {decision['status']}")
        if _parse_timestamp(now) >= _parse_timestamp(decision["expires_at"]):
            raise DecisionNotPendingError(f"decision expired at {decision['expires_at']}")
        if decision["revision"] != if_match_revision or decision["payload_hash"] != if_match_payload_hash:
            raise AuthorizationStaleError(
                "decision content changed since it was shown to the merchant; re-fetch the current card before deciding again"
            )
        option_ids = {option["option_id"] for option in decision["options"]}
        if selected_option_id not in option_ids:
            raise DecisionOptionUnknownError(selected_option_id)

        work = self._require_work(tenant_id, decision["work_id"]["id"])
        if work["status"] != "WAITING_DECISION":
            raise WorkPhaseMismatchError(f"Work is {work['status']}, not WAITING_DECISION")

        decision["status"] = "APPROVED" if selected_option_id == "approve" else "REJECTED"
        decision["selected_option_id"] = selected_option_id
        schema_validation.validate_decision_request(decision)
        self._repo.put_decision(decision)

        if decision["status"] == "APPROVED":
            return self._start_execution(tenant_id, work, decision["display_payload"], now)

        work["status"] = "CANCELLED"
        work.pop("waiting_decision", None)
        work["cancellation"] = {"reason": "merchant did not approve the proposed service revision"}
        work["revision"] += 1
        work["updated_at"] = now
        schema_validation.validate_work(work)
        self._repo.put_work(work)
        return work

    def _start_execution(self, tenant_id: str, work: dict, draft: dict, now: str) -> dict:
        group_task_id = _new_id()
        group_snapshot = {"work_id": work["id"], "channels": list(draft["channels"])}
        group_task = {
            "tenant_id": tenant_id,
            "id": group_task_id,
            "work_id": _ref(tenant_id, work["id"]),
            "kind": "GROUP",
            "operation": "publication.batch",
            "business_key": f"publication.batch:{work['id']}",
            "request_hash": canonical_json.sha256_hex(group_snapshot),
            "request_snapshot": group_snapshot,
            "status": "EXECUTING",
            "revision": 1,
            "owner_revision": 0,
            "postcondition_version": "service-revision-publication-v1",
            "postcondition": {"all_channels_done": True},
            "created_at": now,
            "updated_at": now,
        }
        schema_validation.validate_execution_task(group_task)
        self._repo.put_task(group_task)

        task_refs = [_ref(tenant_id, group_task_id)]
        for channel in draft["channels"]:
            task_id = _new_id()
            snapshot = {
                "channel": channel,
                "service_name": draft["name"],
                "price": draft["price"],
                "duration_minutes": draft["duration_minutes"],
                "capacity": draft["capacity"],
            }
            task = {
                "tenant_id": tenant_id,
                "id": task_id,
                "work_id": _ref(tenant_id, work["id"]),
                "kind": "ACTION",
                "parent_task_id": _ref(tenant_id, group_task_id),
                "operation": "publication.update",
                "business_key": f"publication.update:{work['id']}:{channel.lower()}",
                "request_hash": canonical_json.sha256_hex(snapshot),
                "request_snapshot": snapshot,
                "status": "NEW",
                "revision": 1,
                "owner_revision": 0,
                "postcondition_version": "service-revision-publication-v1",
                "postcondition": {"channel_live_with_evidence": True},
                "created_at": now,
                "updated_at": now,
            }
            schema_validation.validate_execution_task(task)
            self._repo.put_task(task)
            task_refs.append(_ref(tenant_id, task_id))

        work["status"] = "RUNNING"
        work.pop("waiting_decision", None)
        work["execution_task_refs"] = task_refs
        work["revision"] += 1
        work["updated_at"] = now
        schema_validation.validate_work(work)
        self._repo.put_work(work)
        return work

    # -- Worker tick: never called on behalf of a single merchant click -----
    def advance_execution(self, tenant_id: str, work_id: str, now: str) -> dict:
        work = self._require_work(tenant_id, work_id)
        if work["status"] not in ("RUNNING", "WAITING_EXTERNAL"):
            # Covers both ends of work-execution-contract.md §3: a tick on
            # WAITING_INPUT/WAITING_DECISION/CANCELLED has no GROUP task to
            # advance, and a tick on an already-terminal COMPLETED/FAILED
            # /PARTIAL Work must not rewrite its completion evidence.
            raise WorkPhaseMismatchError(f"Work is {work['status']}, not RUNNING/WAITING_EXTERNAL")
        tasks = self._repo.list_tasks_for_work(tenant_id, work_id)
        group_task = next(t for t in tasks if t["kind"] == "GROUP")
        children = [t for t in tasks if t["kind"] == "ACTION"]

        new_children = []
        new_evidence = []
        fail_reasons: dict[str, str] = {}
        for task in children:
            advanced, evidence = self._advance_task(tenant_id, task, now)
            self._repo.put_task(advanced)
            new_children.append(advanced)
            if evidence is not None:
                new_evidence.append(evidence)
            if advanced["status"] == "FAILED":
                ctx = self._repo.get_task_context(tenant_id, advanced["id"]) or {}
                fail_reasons[advanced["request_snapshot"]["channel"]] = ctx.get("fail_reason", "channel rejected")

        if new_evidence:
            work.setdefault("completion_evidence", [])
            work["completion_evidence"].extend(new_evidence)
            for evidence in new_evidence:
                channel = next(
                    t["request_snapshot"]["channel"] for t in new_children if t["id"] == evidence["task_id"]["id"]
                )
                condition_id = f"channel_{channel.lower()}_live"
                for condition in work["completion_conditions"]:
                    if condition["condition_id"] == condition_id:
                        condition["satisfied"] = True
                        condition["evidence_ref"] = evidence["id"]

        statuses = [t["status"] for t in new_children]
        all_done = all(s == "DONE" for s in statuses)
        any_done = any(s == "DONE" for s in statuses)
        any_failed = any(s == "FAILED" for s in statuses)
        all_failed = all(s == "FAILED" for s in statuses)

        for field in ("waiting_external", "partial_summary", "failure", "completion_record"):
            work.pop(field, None)

        if all_done:
            group_task["status"] = "DONE"
            work["status"] = "COMPLETED"
            work["completion_record"] = {
                "evidence_refs": [_ref(tenant_id, e["id"]) for e in work["completion_evidence"]],
                "verifier_version": "service-revision-verifier-v1",
                "completed_at": now,
                "completion_contract_version": work["completion_contract_version"],
            }
        elif any_failed and all_failed:
            group_task["status"] = "FAILED"
            work["status"] = "FAILED"
            work["failure"] = {"reason": "所有渠道發布均失敗", "irreversible_effects_resolved": True}
        elif any_failed and any_done:
            group_task["status"] = "PARTIAL"
            work["status"] = "PARTIAL"
            channels = {t["id"]: t["request_snapshot"]["channel"] for t in new_children}
            work["partial_summary"] = {
                "completed_items": [channels[t["id"]] for t in new_children if t["status"] == "DONE"],
                "incomplete_items": [
                    {"item": channels[t["id"]], "reason": fail_reasons.get(channels[t["id"]], "尚未完成")}
                    for t in new_children
                    if t["status"] != "DONE"
                ],
                "as_of": now,
            }
        else:
            waiting = [t for t in new_children if t["status"] in ("WAITING", "UNKNOWN")]
            if waiting:
                group_task["status"] = "EXECUTING"
                work["status"] = "WAITING_EXTERNAL"
                reason = "RESULT_UNKNOWN" if any(t["status"] == "UNKNOWN" for t in waiting) else "KNOWN_PENDING"
                work["waiting_external"] = {
                    "task_refs": [_ref(tenant_id, t["id"]) for t in waiting],
                    "waiting_reason": reason,
                    "responsible": SYSTEM_ACTOR,
                }
            else:
                group_task["status"] = "EXECUTING"
                work["status"] = "RUNNING"

        group_task["revision"] += 1
        group_task["updated_at"] = now
        schema_validation.validate_execution_task(group_task)
        self._repo.put_task(group_task)

        work["revision"] += 1
        work["updated_at"] = now
        schema_validation.validate_work(work)
        self._repo.put_work(work)
        return work

    def _advance_task(self, tenant_id: str, task: dict, now: str) -> tuple[dict, dict | None]:
        if task["status"] in ("DONE", "FAILED", "CANCELLED"):
            return task, None
        channel = task["request_snapshot"]["channel"]
        business_key = task["business_key"]
        ctx = self._repo.get_task_context(tenant_id, task["id"]) or {}
        if task["status"] in ("NEW", "VALIDATING", "READY"):
            result: OperationResult = self._connector.submit_publication(
                tenant_id, business_key, channel, str(task["revision"]), now
            )
        else:  # WAITING / UNKNOWN
            result = self._connector.reconcile(tenant_id, business_key, ctx.get("reconciliation_token", ""), now)
        return self._apply_operation_result(tenant_id, task, result, now, ctx)

    def _apply_operation_result(
        self, tenant_id: str, task: dict, result: OperationResult, now: str, ctx: dict
    ) -> tuple[dict, dict | None]:
        task = dict(task)
        evidence = None
        if isinstance(result, Pending):
            task["status"] = "WAITING"
            ctx["reconciliation_token"] = result.reconciliation_token
            ctx["external_reference"] = result.external_reference
        elif isinstance(result, Unknown):
            task["status"] = "UNKNOWN"
            ctx["reconciliation_token"] = result.reconciliation_token
        elif isinstance(result, Succeeded):
            task["status"] = "DONE"
            evidence = {
                "tenant_id": tenant_id,
                "id": _new_id(),
                "work_id": task["work_id"],
                "task_id": _ref(tenant_id, task["id"]),
                "evidence_type": "CHANNEL_PUBLICATION_READBACK",
                "environment": "SANDBOX",
                "external_ref": result.external_reference,
                "observed_at": result.observed_at,
                "verifier_version": "service-revision-verifier-v1",
            }
            if result.source_revision:
                evidence["source_revision"] = result.source_revision
        elif isinstance(result, Failed):
            task["status"] = "FAILED"
            ctx["fail_reason"] = result.message
        else:
            raise TypeError(f"unhandled OperationResult: {result!r}")
        task["revision"] += 1
        task["updated_at"] = now
        schema_validation.validate_execution_task(task)
        self._repo.put_task_context(tenant_id, task["id"], ctx)
        return task, evidence

    # -- Test/demo-only helper, never a production merchant endpoint --------
    def simulate_channel_review_result(self, tenant_id: str, work_id: str, channel: str, outcome: str) -> None:
        """Stands in for the channel's own review finishing, exactly like
        the UX 2.1 prototype's '示範情境切換' demo control
        (docs/verification/prototype-audit.md §2). A real deployment learns
        this from a webhook or a scheduled reconcile() call landing a
        terminal result, never from a merchant action."""
        business_key = f"publication.update:{work_id}:{channel.lower()}"
        self._connector.advance_review(tenant_id, business_key, outcome)

    # -- Merchant-safe reads -------------------------------------------------
    def get_work_status(self, tenant_id: str, work_id: str) -> dict:
        work = self._require_work(tenant_id, work_id)
        tasks = self._repo.list_tasks_for_work(tenant_id, work_id)
        channels = {
            task["request_snapshot"]["channel"]: _CHANNEL_DISPLAY_STATE[task["status"]]
            for task in tasks
            if task["kind"] == "ACTION"
        }
        return {
            "work_id": work_id,
            "status": work["status"],
            "channels": channels,
            "waiting_input": work.get("waiting_input"),
            "waiting_decision": work.get("waiting_decision"),
            "waiting_external": work.get("waiting_external"),
            "partial_summary": work.get("partial_summary"),
            "failure": work.get("failure"),
            "cancellation": work.get("cancellation"),
            "completion_record": work.get("completion_record"),
        }

    def get_home_view(self, tenant_id: str) -> list[dict]:
        items = []
        for work in self._repo.list_works(tenant_id):
            entry = {"work_id": work["id"], "status": work["status"], "objective": work["objective"]}
            if work["status"] == "WAITING_INPUT":
                # Recomputed live from the draft rather than read back from
                # work["waiting_input"]["missing_fields"], which can go
                # stale the instant the draft becomes complete (see
                # submit_missing_input above).
                entry["missing_fields"] = _missing_fields(self._repo.get_draft(tenant_id, work["id"]))
            elif work["status"] == "WAITING_DECISION":
                decision = self._repo.get_decision(tenant_id, work["waiting_decision"]["decision_ref"]["id"])
                entry["decision_card"] = {
                    "decision_id": decision["id"],
                    "revision": decision["revision"],
                    "payload_hash": decision["payload_hash"],
                    "options": decision["options"],
                    "display_payload": decision["display_payload"],
                    "expires_at": decision["expires_at"],
                }
            else:
                entry["work_status"] = self.get_work_status(tenant_id, work["id"])
            items.append(entry)
        return items

    # -- internals -------------------------------------------------------
    def _require_work(self, tenant_id: str, work_id: str) -> dict:
        work = self._repo.get_work(tenant_id, work_id)
        if work is None:
            raise WorkNotFoundError(f"no work {work_id} for this tenant")
        return work

    def _validate_bounds(self, fields: dict) -> None:
        """Runs the real specs/workbench/service-revision.schema.json over a
        probe copy so the capacity/duration/price/channel bounds are
        enforced from a single source of truth, even before an asset has
        been provided (backlog ENG-06 acceptance: 容量等不合法值在前後端都被拒絕)."""
        probe = dict(fields)
        probe.pop("asset_ref", None)
        probe["asset_waived"] = True
        probe["rights_confirmed"] = True
        try:
            schema_validation.validate_service_revision(probe)
        except Exception as exc:  # jsonschema.ValidationError
            raise InvalidServiceRevisionFieldError(str(getattr(exc, "message", exc))) from exc
        # Money.schema.json (ENG-01, shared) deliberately permits a zero
        # amount for ledgers that legitimately carry one; a merchant's own
        # service price does not, and that bound is this workbench's rule,
        # not a cross-ENG change to the shared Money contract.
        price = fields.get("price") or {}
        try:
            positive_price = int(price.get("amount_minor_units", "0")) >= 1
        except ValueError:
            positive_price = False
        if not positive_price:
            raise InvalidServiceRevisionFieldError("price.amount_minor_units must be at least 1 minor unit")
