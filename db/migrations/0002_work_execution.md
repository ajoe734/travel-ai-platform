# 0002_work_execution

## 內容

`work`（含依 status 條件必填的 jsonb 欄位與對應 CHECK，直接把
`specs/domain/work.schema.json` 的 `allOf` 轉成資料列層級約束）、`work_plan`
（append-only）、`work_context`、`completion_evidence`（append-only）、`escalation`、
`work_event`（append-only）、`execution_task`、`execution_attempt`（append-only）、
`execution_attempt_observation`（append-only）。

`execution_task.parent_task_id` 透過 `(tenant_id, work_id, id)` 的 UNIQUE 鍵，讓
`FOREIGN KEY (tenant_id, work_id, parent_task_id) REFERENCES execution_task(tenant_id, work_id, id)`
同時保證「同租戶」與「同 Work」兩個 SD §2 要求的不變量，不需額外 trigger。

## Rollback

依賴順序反向刪除；對空庫安全。先移除指向 `execution_task` 的兩個延後 FK
（`completion_evidence.task_id`、`escalation.task_id`），再刪表。

## Forward-fix

`work` 的狀態對應 CHECK（例如 `work_completion_record_matches_status`）一旦上線後
要放寬，使用後續 migration 以 `ALTER TABLE ... DROP CONSTRAINT` +
新 CHECK（`NOT VALID` 後 `VALIDATE CONSTRAINT`）取代，不對已有 Work 資料做 rollback。
