# 0005_idempotency_outbox_inbox

## 內容

`idempotency_key_record`（`(tenant_id, actor_id, operation, idempotency_key)` PK，
append-only；同 key 同 hash 由 repository 層回放，同 key 不同 hash 由 repository 層
拋 `IDEMPOTENCY_CONFLICT`，不在 DB 層用 CHECK 比較兩個不同列的 hash）、
`outbox_event`（`(tenant_id, aggregate_type, aggregate_id, sequence)` 唯一；trigger 只
放行 `published_at`／`dispatch_attempts` 這兩個 worker 記帳欄位）、`inbox_event`（
`(tenant_id, connector_account_id, environment, producer, source_event_id)` 唯一；
trigger 只放行 `processing_status`／`processed_at`）、`inbox_event_conflict`
（append-only，記錄「同 ID 不同 hash」告警，不覆寫原 `inbox_event`）。

## Rollback

反向刪除 trigger／function／table；對空庫安全。

## Forward-fix

若需要放寬 outbox/inbox 的可變欄位集合（例如新增 `last_error` 欄位給 worker
記錄失敗原因），新增 migration 同時更新對應 guard trigger function body，不
rollback 已產生的事件歷史。
