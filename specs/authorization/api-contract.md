# DecisionRequest API 契約

來源：[docs/sd/authorization-and-approval.md §4](../../docs/sd/authorization-and-approval.md#4-決策生命週期與命令)。
本檔固定 HTTP 入口與請求／回應形狀；實際 handler 接 HTTP 框架、資料庫 transaction 與 worker dispatch
是 ENG-05 範圍（backlog ENG-05 依賴 ENG-03）。每個入口在下表對應到
[`services/authorization/service.py`](../../services/authorization/service.py) 的一個
`AuthorizationService` 方法；handler 的工作只是解析請求、注入已驗證的 `tenant_id`/`actor`、呼叫該方法、
把 `AuthorizationError` 轉成 `common/error-envelope.schema.json` 回應（`AuthorizationError.to_envelope`
已經做好這個轉換）。

原 SA 的 quote confirmations／proposal approve／remedy confirmations 等業務入口保留各自的 URL 與呈現文案，
但內部一律呼叫這裡的同一個 `AuthorizationService`，不得另外產生一套互不相認的授權紀錄。

所有 mutation 皆需 `Idempotency-Key` header（SD §4）；冪等鍵範圍是
`(tenant_id, actor_id, operation, idempotency_key)`，與
[`common/identifiers.schema.json#/$defs/IdempotencyKey`](../domain/common/identifiers.schema.json)一致。

## POST /v1/decisions

建立新的 DecisionRequest（revision 1）。

- 對應：`AuthorizationService.create_decision`
- 請求：`work_id`、`decision_type`、`options`、`display_payload`（內容須滿足
  `services/authorization/service.py` 的 `REQUIRED_CANONICAL_PAYLOAD_FIELDS`，即 SD §3.1 清單）、
  `target_revision`、`expires_at`、`requested_role`、`context_refs?`
- 成功：201，body 為符合 `decision-request.schema.json` 的 DecisionRequest（含 `id`／`revision`／
  `payload_hash`），另回 `confirmation_nonce_id`（只回給受信任的 UI 確認端點或語音確認服務，不回給一般
  呼叫端或模型工具清單）
- 失敗：`CROSS_TENANT_REFERENCE_REJECTED`（`display_payload.tenant_id` 與呼叫者不符）；
  `display_payload` 缺必填欄位時回 422（`ValueError`，尚未分配專屬 registry code，由 handler 層映射）

## POST /v1/decisions/{id}/revisions

提案改版：新 revision，舊 pending 版 SUPERSEDED。

- 對應：`AuthorizationService.propose_revision`
- 請求：`expected_revision`（= 目前 revision；可由 If-Match 代入，見下方「ETag」段）、其餘欄位同建立決策
- 成功：201，新 DecisionRequest + 新 `confirmation_nonce_id`
- 失敗：`VERSION_CONFLICT`（`expected_revision` 不是目前 PENDING revision）

## POST /v1/decisions/{id}/approve

- 對應：`AuthorizationService.approve_decision`
- Header：`Idempotency-Key`（必填）；`If-Match`（選填，需與 `expected_revision` 一致，否則拒絕，見 SD §4）
- 請求：`expected_revision`、`selected_option_id`、`nonce_id`（受信任 UI／語音確認端點核發，**不是**
  呼叫端自選字串）、`approved_by`、`verified_actor_ref`、`scope_manifest`、`approved_at`、
  `policy_version?`、`expires_at?`、`confirmation_evidence?`
- 成功：201，ApprovalRecord；同 Idempotency-Key 同內容重送回同一筆（SD-A-03）
- 失敗映射：
  - 舊 ETag／展示內容已變 → `AUTHORIZATION_STALE`（SD-A-02）
  - 同 key 改內容（含金額、manifest）→ `IDEMPOTENCY_CONFLICT`（SD-A-04）
  - `nonce_id` 缺失、已用過或綁定別的決策/tenant/revision → `UNVERIFIED_APPROVAL_REJECTED`（SD-A-01：
    模型文字或前端旗標自稱 `accepted=true` 必落在此分支，因為它們從未取得一個由本服務核發的有效 nonce）
  - 角色不符 → `ACTOR_ROLE_MISMATCH`
  - 決策已被其他有效命令解決（已核准/拒絕/過期/取代）→ `VERSION_CONFLICT`
  - 跨租戶或找不到 → `CROSS_TENANT_REFERENCE_REJECTED`（不揭露存在性）

## POST /v1/decisions/{id}/reject

- 對應：`AuthorizationService.reject_decision`
- Header：`Idempotency-Key`（必填）
- 請求：`expected_revision`、`selected_option_id`、`rejected_by`、`reason`
- 成功：200／201，更新後的 DecisionRequest（`status=REJECTED`）；同 key 同內容重送回同結果
- 失敗映射：同上 approve 的 `AUTHORIZATION_STALE`／`VERSION_CONFLICT`／`ACTOR_ROLE_MISMATCH`／
  `IDEMPOTENCY_CONFLICT`

## POST /v1/approvals/{id}/revocations

- 對應：`AuthorizationService.revoke_approval`
- 請求：`revoked_by`、`reason`、`effective_at`
- 成功：201，`{revocation, resent, affected_authorizations}`；`affected_authorizations` 逐筆列出
  `NOT_YET_DISPATCHED_BLOCKED` 或 `DISPATCHED_PROCEEDS_TO_RECONCILIATION`（SD §6 競態結果，見
  `acceptance-trace.md` SD-A-07/08 列）；撤回同一批准的重送回同一筆撤回紀錄（`resent=true`）
- 失敗映射：`REVOCATION_NOT_PERMITTED`（actor_kind 不允許撤回）、`CROSS_TENANT_REFERENCE_REJECTED`

## 非公開 HTTP 入口（ENG-05 worker 內部呼叫）

以下方法沒有獨立的公開 REST 入口，是 Work/ExecutionTask 執行路徑在建立授權與每次對外呼叫前呼叫的
服務方法，由 ENG-05 的 worker/activity 直接呼叫同一個 `AuthorizationService` 實例：

| 方法 | 用途 | SD 來源 |
|---|---|---|
| `try_issue_policy_covered_authorization` | 已有政策覆蓋時直接核發授權，不建立 DecisionRequest | §1/§5, SD-A-10 |
| `issue_execution_authorization` | 從 grant_refs 或 approval_refs 核發 ExecutionAuthorization | §1/§5 |
| `consume_authorization_use` | 消耗到唯一 root ExecutionTask | §5, SD-A-06 |
| `precheck_before_dispatch` | 每次對外呼叫前的最後一次核對 | §6 |
| `mark_dispatched` | 標記已實際送出，供撤回競態判斷使用 | §6 |
| `is_approval_effective` | 撤回有效性 read model | §2, ADR 0003 |
| `expire_decisions` | 背景查核過期 PENDING 決策 | §4 |

## ETag／If-Match

`expected_revision`（body）與 `If-Match`（header，若呼叫端支援）都對應同一個 revision 概念。兩者同時
出現且不一致時，`approve_decision` 直接回 `VERSION_CONFLICT`，不挑一個使用（SD §4：「若兩者同時存在且
不一致則拒絕，不能挑一個使用」）。
