# 關聯圖與 cardinality

來源：[SD work-execution-contract.md §1](../../docs/sd/work-execution-contract.md)、
[authorization-and-approval.md §1/§5](../../docs/sd/authorization-and-approval.md)、[ADR 0001](../../docs/adr/0001-case-work-execution.md)。
本檔把 SD 的 mermaid ERD 轉成逐關聯的 cardinality 與外鍵規則，對照本目錄的 schema 檔案；不改變 SD 已決定的語意。

## 核心關聯

| 關聯 | Cardinality | 外鍵規則 | 對應 schema |
|---|---|---|---|
| Case → Work | 1 : 0..N | `Work.case_id` 必填，複合 `(tenant_id, id)`；一個 Case 可同時有查價、改期、通知等多個 Work | `case.schema.json` → `work.schema.json` |
| Case → Complaint | 1 : 0..N | `Complaint.case_id` 必填；Complaint 不是 Case 的別名，也不取代 Case 的需求版本 | `case.schema.json` → `complaint.schema.json` |
| Case → Conversation | 1 : 0..N | 透過 `CASE_CONVERSATION`（ENG-02 持久層）；本輪只固定 `Case.conversation_refs` 的參照形狀 | `case.schema.json` |
| Work → ExecutionTask | 1 : 0..N | `ExecutionTask.work_id` 必填；一個 Work 常見對應多個 ExecutionTask（例如預訂 + 通知） | `work.schema.json` → `execution-task.schema.json` |
| ExecutionTask → ExecutionAttempt | 1 : 1..N | `ExecutionAttempt.task_id` 必填；重試只增加 Attempt，不建立新 ExecutionTask | `execution-task.schema.json` → `execution-attempt.schema.json` |
| ExecutionTask → ExecutionTask（父子） | 1 : 0..N（自參照） | `parent_task_id` 必須同 `tenant_id` 與同 `work_id`；GROUP 不直接呼叫外部寫入，ACTION 才有真正副作用 | `execution-task.schema.json` |
| Complaint → RemedyAction | 1 : 0..N | `Complaint.remedy_action_refs`；RemedyAction／Refund 完整 schema 是 ENG-07 範圍，本輪只固定參照形狀與「不自動改變 Complaint.status」的規則 | `complaint.schema.json` |
| Work → DecisionRequest | 1 : 0..N | `DecisionRequest.work_id` 必填；Work 進入 `WAITING_DECISION` 時必須有至少一個有效 `decision_ref` | `work.schema.json` ↔ `decision-request.schema.json` |
| DecisionRequest → ApprovalRecord | 1 : 0..N（同一 `reviewed_revision` 僅一次） | `ApprovalRecord.decision_id` + `reviewed_revision`；新 revision 不可用舊批准 | `decision-request.schema.json` → `approval-record.schema.json` |
| ApprovalRecord → ApprovalRevocation | 1 : 0..N | `ApprovalRevocation.approval_id`；append-only，不回寫原批准 | `approval-record.schema.json`（`$defs/ApprovalRevocation`） |
| ExecutionAuthorization → AuthorizationUse | 1 : 0..1 | `AuthorizationUse.authorization_id`；同一授權只能消耗到一個 root ExecutionTask，重試找回同一筆 | `approval-record.schema.json`（`$defs/ExecutionAuthorization`／`$defs/AuthorizationUse`） |
| Work → Order（透過 WorkContext） | 0..N : 0..N | `WorkContext.ref_kind=ORDER`，`target` 是實體 FK，不是自由字串；Order 不是 Work 的子類 | `work.schema.json`（`$defs/WorkContext`） → `order.schema.json` |
| Order → Case／Quote | 1 : 1 | `Order.case_id`、`Order.quote_id` 必填；Order 是客戶投影，不合併 booking/payment/refund 三個來源狀態 | `order.schema.json` |

## 不可變與 append-only 物件

以下物件一旦寫入即不可變（UPDATE/DELETE 由 ENG-02 的資料庫層以 trigger 或缺少 UPDATE 權限保證；本輪只固定其欄位形狀）：

- `WorkPlan`（`(tenant_id, work_id, plan_revision)` 唯一，只追加新 revision）
- `ExecutionAttempt` 本體與其 `observations`（新觀察只追加 `sequence`，不覆寫舊紀錄）
- `CompletionEvidence`
- `CustomerConsent`、`ApprovalRecord`、`ApprovalRevocation`、`ExecutionAuthorization`、`AuthorizationUse`

## 跨租戶規則

所有上述關聯的兩端都必須是同一 `tenant_id`；`common/identifiers.schema.json#/$defs/TenantScopedRef` 把
`tenant_id` 和 `id` 綁在同一個物件裡，使任何參照欄位都無法只傳裸 `id`。純 JSON Schema 無法表達「參照的
`tenant_id` 必須等於父物件自己的 `tenant_id`」這種跨欄位相等；`tests/domain_contract_test.py` 的
`test_cross_tenant_parent_task_reference_is_rejected_shape` 用範例示範這種不一致的形狀，並記錄為 ENG-02
資料庫 FK／RLS 必須擋下的情況（對應 SA-AT-045、SD-W-03）。
