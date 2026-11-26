"""In-memory workbench repository.

Explicitly a placeholder pending ENG-02's persistence layer (UNIQUE/FK/RLS),
same disclosed boundary as services/authorization/repository.py on
claude/eng-03: this fixes the read/write shape ENG-02 must support, it does
not claim to be the durable store. Every read returns a deep copy so a
caller mutating the result can never corrupt this repository's state behind
its back (the same bug class services/authorization's R1 review found and
fixed with copy.deepcopy).

Tenant isolation: every lookup is keyed by (tenant_id, id); a lookup for the
wrong tenant_id is treated as a miss, not a cross-tenant leak -- callers
translate a miss into WORK_NOT_FOUND or CROSS_TENANT_REFERENCE_REJECTED
depending on which is more appropriate, but either way nothing about another
tenant's object is observable.
"""
from __future__ import annotations

import copy


class WorkbenchRepository:
    def __init__(self) -> None:
        self._works: dict[tuple[str, str], dict] = {}
        self._decisions: dict[tuple[str, str], dict] = {}
        self._tasks: dict[tuple[str, str], dict] = {}
        self._drafts: dict[tuple[str, str], dict] = {}
        self._task_context: dict[tuple[str, str], dict] = {}

    # -- Work -----------------------------------------------------------
    def put_work(self, work: dict) -> None:
        key = (work["tenant_id"], work["id"])
        self._works[key] = copy.deepcopy(work)

    def get_work(self, tenant_id: str, work_id: str) -> dict | None:
        found = self._works.get((tenant_id, work_id))
        return copy.deepcopy(found) if found is not None else None

    def list_works(self, tenant_id: str) -> list[dict]:
        return [copy.deepcopy(w) for (t, _), w in self._works.items() if t == tenant_id]

    # -- DecisionRequest --------------------------------------------------
    def put_decision(self, decision: dict) -> None:
        key = (decision["tenant_id"], decision["id"])
        self._decisions[key] = copy.deepcopy(decision)

    def get_decision(self, tenant_id: str, decision_id: str) -> dict | None:
        found = self._decisions.get((tenant_id, decision_id))
        return copy.deepcopy(found) if found is not None else None

    # -- ExecutionTask ----------------------------------------------------
    def put_task(self, task: dict) -> None:
        key = (task["tenant_id"], task["id"])
        self._tasks[key] = copy.deepcopy(task)

    def get_task(self, tenant_id: str, task_id: str) -> dict | None:
        found = self._tasks.get((tenant_id, task_id))
        return copy.deepcopy(found) if found is not None else None

    def list_tasks_for_work(self, tenant_id: str, work_id: str) -> list[dict]:
        return [
            copy.deepcopy(t)
            for (t_tenant, _), t in self._tasks.items()
            if t_tenant == tenant_id and t["work_id"]["id"] == work_id
        ]

    # -- Pre-decision drafts ----------------------------------------------
    # A ServiceRevisionProposal under construction (WAITING_INPUT) is not
    # yet a schema-validated domain entity; it only becomes one -- a
    # DecisionRequest.display_payload -- once complete. Keeping the draft
    # separate from Work/DecisionRequest means an incomplete proposal can
    # never be mistaken for one the merchant actually submitted for a
    # decision (backlog ENG-06 acceptance: 模型解析出的內容可核對且不被固定範例覆蓋).
    def put_draft(self, tenant_id: str, work_id: str, draft: dict) -> None:
        self._drafts[(tenant_id, work_id)] = copy.deepcopy(draft)

    def get_draft(self, tenant_id: str, work_id: str) -> dict | None:
        found = self._drafts.get((tenant_id, work_id))
        return copy.deepcopy(found) if found is not None else None

    # -- Connector dispatch context ---------------------------------------
    # Not a domain entity: the opaque reconciliation_token/external_reference
    # a connector hands back at dispatch time (connectors/types.py Pending/
    # Unknown) has nowhere to live on the schema-validated ExecutionTask
    # (additionalProperties: false). A real deployment keeps this on its
    # ExecutionAttempt/outbox rows (ENG-02 scope); this is that row's
    # in-memory stand-in, scoped to one task.
    def put_task_context(self, tenant_id: str, task_id: str, context: dict) -> None:
        self._task_context[(tenant_id, task_id)] = copy.deepcopy(context)

    def get_task_context(self, tenant_id: str, task_id: str) -> dict | None:
        found = self._task_context.get((tenant_id, task_id))
        return copy.deepcopy(found) if found is not None else None
