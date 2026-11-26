# 0003_decision_approval_authorization

## 內容

`decision_request`（`(tenant_id, id, revision)` 複合鍵，同一 `id` 的每個 revision 是
獨立列；內容欄位以 trigger 擋 UPDATE，只放行 `status`／`selected_option_id`／
`impact_summary`／`context_refs`）、`approval_record`（append-only，FK 到
`decision_request(tenant_id, id, revision)`，`UNIQUE(tenant_id, decision_id,
reviewed_revision)` 防重複核准）、`customer_consent`、`approval_revocation`、
`execution_authorization`、`authorization_use`（append-only；
`UNIQUE(tenant_id, authorization_id)` 對應 `AUTHORIZATION_USE_ALREADY_BOUND`）。

## 設計決策：DecisionRequest 的 revision 建模

`specs/domain/decision-request.schema.json` 與 `approval-record.schema.json` 的敘述
（`UNIQUE(tenant_id, decision_id, reviewed_revision)` 須在持久層落實；「舊 revision 的
展示內容只追加保存」）隱含「同一 decision `id` 的每個 revision 是一筆獨立、內容不可變
的紀錄，`id` 在跨 revision 間保持穩定」，而不是單列覆寫 `revision` 欄位。本 migration
採用 `(tenant_id, id, revision)` 複合 PK 實作這個解讀；舊 revision 轉 `SUPERSEDED` 是對
「同一列」的 status-only UPDATE（trigger 允許），不是建立新列也不是改寫展示內容本身。

## Rollback

反向刪除；先移除 `execution_task.authorization_use_id` 的延後 FK。

## Forward-fix

`decision_request_guard_mutation()` 日後若需放寬允許的可變欄位（例如新增
`impact_summary` 以外的可更新欄位），用新 migration 改寫 trigger function body，
不 rollback 已有 decision/approval 資料。
