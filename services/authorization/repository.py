"""Repository port for the authorization service, plus an in-memory stand-in.

ENG-03's task brief defers real persistence to ENG-02: "持久化部分待 ENG-02
合併後再接上". ``AuthorizationRepository`` is the seam — every method
AuthorizationService needs from storage, expressed so a future
Postgres-backed implementation (UNIQUE constraints, RLS, real transactions)
satisfies the exact same contract. ``InMemoryAuthorizationRepository`` here
is a same-process stand-in used by the service and its tests today; it
enforces the same uniqueness/atomicity rules as cooperating locks rather than
database constraints, so the race-handling tests in
tests/authorization_service_test.py already exercise real ordering, not a
mocked-out no-op.

AuthorityGrant/PolicyVersion (SD §1) does not have a specs/domain schema yet —
no ENG task has formalized it. The lightweight dict shape used here
(``capability``, ``expiry``, ``revoked``, ``budget_remaining``) is an ENG-03
internal stand-in for "a pre-approved policy grant exists and is checked",
not a claim that this is the final AuthorityGrant contract.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator


class InMemoryAuthorizationRepository:
    def __init__(self) -> None:
        self._master_lock = threading.Lock()

        # (tenant_id, decision_id) -> {revision: DecisionRequest dict}
        self._decisions: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}

        # (tenant_id, approval_id) -> ApprovalRecord dict
        self._approvals: dict[tuple[str, str], dict[str, Any]] = {}
        # (tenant_id, decision_id, reviewed_revision) -> approval_id
        self._approval_by_decision_revision: dict[tuple[str, str, int], str] = {}

        # (tenant_id, approval_id) -> [ApprovalRevocation dict, ...] (append-only, first wins)
        self._revocations: dict[tuple[str, str], list[dict[str, Any]]] = {}

        # (tenant_id, authorization_id) -> ExecutionAuthorization dict
        self._authorizations: dict[tuple[str, str], dict[str, Any]] = {}
        # (tenant_id, authorization_id) -> AuthorizationUse dict (0..1)
        self._authorization_uses: dict[tuple[str, str], dict[str, Any]] = {}
        # (tenant_id, authorization_id) -> dispatched_at ISO string, once a worker has
        # actually sent the external call (SD §6; not a domain schema field, ENG-03/05
        # execution-time bookkeeping only).
        self._dispatched_at: dict[tuple[str, str], str] = {}

        # (tenant_id, authorization_id) -> per-root-operation lock (SD §6: "撤回與 dispatch
        # 需在同一授權/根操作鎖上有明確排序").
        self._root_locks: dict[tuple[str, str], threading.Lock] = {}

        # (tenant_id, actor_id, operation, idempotency_key) -> {"request_hash", "result_ref"}
        self._idempotency: dict[tuple[str, str, str, str], dict[str, Any]] = {}

        # nonce_id -> {"tenant_id", "decision_id", "revision", "payload_hash", "consumed"}
        self._nonces: dict[str, dict[str, Any]] = {}
        self._nonce_seq = 0

        # (tenant_id, grant_id) -> grant dict
        self._grants: dict[tuple[str, str], dict[str, Any]] = {}

    # -- DecisionRequest -----------------------------------------------

    def get_decision_latest(self, tenant_id: str, decision_id: str) -> dict[str, Any] | None:
        revisions = self._decisions.get((tenant_id, decision_id))
        if not revisions:
            return None
        return dict(revisions[max(revisions)])

    def get_decision_revision(self, tenant_id: str, decision_id: str, revision: int) -> dict[str, Any] | None:
        revisions = self._decisions.get((tenant_id, decision_id))
        if not revisions or revision not in revisions:
            return None
        return dict(revisions[revision])

    def put_decision(self, decision: dict[str, Any]) -> None:
        key = (decision["tenant_id"], decision["id"])
        self._decisions.setdefault(key, {})[decision["revision"]] = dict(decision)

    def list_pending_decisions(self, tenant_id: str) -> list[dict[str, Any]]:
        out = []
        for (t, _decision_id), revisions in self._decisions.items():
            if t != tenant_id:
                continue
            latest = revisions[max(revisions)]
            if latest["status"] == "PENDING":
                out.append(dict(latest))
        return out

    def update_decision_status(
        self,
        tenant_id: str,
        decision_id: str,
        revision: int,
        status: str,
        selected_option_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._decisions[(tenant_id, decision_id)][revision]
        row["status"] = status
        if selected_option_id is not None:
            row["selected_option_id"] = selected_option_id
        return dict(row)

    # -- ApprovalRecord --------------------------------------------------

    def get_approval(self, tenant_id: str, approval_id: str) -> dict[str, Any] | None:
        row = self._approvals.get((tenant_id, approval_id))
        return dict(row) if row is not None else None

    def get_approval_by_decision_revision(
        self, tenant_id: str, decision_id: str, reviewed_revision: int
    ) -> dict[str, Any] | None:
        approval_id = self._approval_by_decision_revision.get((tenant_id, decision_id, reviewed_revision))
        if approval_id is None:
            return None
        return self.get_approval(tenant_id, approval_id)

    def put_approval_if_absent(self, approval: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Atomically enforce UNIQUE(tenant_id, decision_id, reviewed_revision)."""
        tenant_id = approval["tenant_id"]
        decision_id = approval["decision_id"]["id"]
        reviewed_revision = approval["reviewed_revision"]
        key = (tenant_id, decision_id, reviewed_revision)
        with self._master_lock:
            existing_id = self._approval_by_decision_revision.get(key)
            if existing_id is not None:
                return dict(self._approvals[(tenant_id, existing_id)]), False
            self._approval_by_decision_revision[key] = approval["id"]
            self._approvals[(tenant_id, approval["id"])] = dict(approval)
            return dict(approval), True

    # -- ApprovalRevocation (append-only, first wins) ---------------------

    def put_revocation_if_absent(
        self, tenant_id: str, approval_id: str, revocation: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        key = (tenant_id, approval_id)
        with self._master_lock:
            existing = self._revocations.get(key, [])
            if existing:
                return dict(existing[0]), False
            self._revocations[key] = [dict(revocation)]
            return dict(revocation), True

    def list_revocations(self, tenant_id: str, approval_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._revocations.get((tenant_id, approval_id), [])]

    def is_approval_effective(self, tenant_id: str, approval_id: str, at: str) -> bool:
        """Read-model projection per ADR 0003: revoked_at is never a column, only derived."""
        approval = self.get_approval(tenant_id, approval_id)
        if approval is None:
            return False
        for revocation in self.list_revocations(tenant_id, approval_id):
            if revocation["effective_at"] <= at:
                return False
        return True

    # -- ExecutionAuthorization -------------------------------------------

    def put_authorization(self, authorization: dict[str, Any]) -> None:
        self._authorizations[(authorization["tenant_id"], authorization["id"])] = dict(authorization)

    def get_authorization(self, tenant_id: str, authorization_id: str) -> dict[str, Any] | None:
        row = self._authorizations.get((tenant_id, authorization_id))
        return dict(row) if row is not None else None

    def find_authorizations_referencing_approval(self, tenant_id: str, approval_id: str) -> list[dict[str, Any]]:
        out = []
        for (t, _auth_id), auth in self._authorizations.items():
            if t != tenant_id:
                continue
            for ref in auth.get("approval_refs", []):
                if ref["id"] == approval_id:
                    out.append(dict(auth))
                    break
        return out

    # -- AuthorizationUse ---------------------------------------------------

    @contextmanager
    def lock_for(self, tenant_id: str, authorization_id: str) -> Iterator[None]:
        key = (tenant_id, authorization_id)
        with self._master_lock:
            lock = self._root_locks.setdefault(key, threading.Lock())
        with lock:
            yield

    def get_authorization_use(self, tenant_id: str, authorization_id: str) -> dict[str, Any] | None:
        row = self._authorization_uses.get((tenant_id, authorization_id))
        return dict(row) if row is not None else None

    def put_authorization_use_if_absent(
        self, tenant_id: str, authorization_id: str, use: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Caller must hold ``lock_for(tenant_id, authorization_id)``."""
        key = (tenant_id, authorization_id)
        existing = self._authorization_uses.get(key)
        if existing is not None:
            return dict(existing), False
        self._authorization_uses[key] = dict(use)
        return dict(use), True

    def mark_dispatched(self, tenant_id: str, authorization_id: str, now: str) -> None:
        """Caller must hold ``lock_for(tenant_id, authorization_id)``."""
        self._dispatched_at[(tenant_id, authorization_id)] = now

    def is_dispatched(self, tenant_id: str, authorization_id: str) -> bool:
        return (tenant_id, authorization_id) in self._dispatched_at

    # -- Idempotency ----------------------------------------------------------

    def get_idempotency(self, tenant_id: str, actor_id: str, operation: str, key: str) -> dict[str, Any] | None:
        row = self._idempotency.get((tenant_id, actor_id, operation, key))
        return dict(row) if row is not None else None

    def put_idempotency(
        self, tenant_id: str, actor_id: str, operation: str, key: str, request_hash: str, result_ref: dict[str, Any]
    ) -> None:
        self._idempotency[(tenant_id, actor_id, operation, key)] = {
            "request_hash": request_hash,
            "result_ref": dict(result_ref),
        }

    # -- Confirmation nonce (SD §1: only a trusted UI/voice confirmation endpoint issues these) --

    def issue_nonce(self, tenant_id: str, decision_id: str, revision: int, payload_hash: str) -> str:
        with self._master_lock:
            self._nonce_seq += 1
            nonce_id = f"nonce-{self._nonce_seq}"
            self._nonces[nonce_id] = {
                "tenant_id": tenant_id,
                "decision_id": decision_id,
                "revision": revision,
                "payload_hash": payload_hash,
                "consumed": False,
            }
            return nonce_id

    def peek_nonce(self, nonce_id: str) -> dict[str, Any] | None:
        row = self._nonces.get(nonce_id)
        return dict(row) if row is not None else None

    def consume_nonce(self, nonce_id: str) -> dict[str, Any] | None:
        with self._master_lock:
            row = self._nonces.get(nonce_id)
            if row is None or row["consumed"]:
                return None
            row["consumed"] = True
            return dict(row)

    # -- AuthorityGrant stand-in (SD §1; no formal schema yet, see module docstring) --

    def put_grant(self, grant: dict[str, Any]) -> None:
        self._grants[(grant["tenant_id"], grant["id"])] = dict(grant)

    def get_grant(self, tenant_id: str, grant_id: str) -> dict[str, Any] | None:
        row = self._grants.get((tenant_id, grant_id))
        return dict(row) if row is not None else None

    def find_covering_grant(self, tenant_id: str, capability: str, now: str) -> dict[str, Any] | None:
        for (t, _gid), grant in self._grants.items():
            if t != tenant_id:
                continue
            if grant.get("revoked"):
                continue
            if grant["expiry"] <= now:
                continue
            if capability not in grant.get("capabilities", []):
                continue
            if grant.get("budget_remaining") is not None and grant["budget_remaining"] <= 0:
                continue
            return dict(grant)
        return None

    def consume_grant_budget(self, tenant_id: str, grant_id: str) -> None:
        with self._master_lock:
            grant = self._grants[(tenant_id, grant_id)]
            if grant.get("budget_remaining") is not None:
                grant["budget_remaining"] -= 1

    def revoke_grant(self, tenant_id: str, grant_id: str) -> None:
        self._grants[(tenant_id, grant_id)]["revoked"] = True
