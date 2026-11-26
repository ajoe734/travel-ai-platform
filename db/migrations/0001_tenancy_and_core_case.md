# 0001_tenancy_and_core_case

## 內容

`tenant` 登記表（含 `environment` 標記正式／sandbox／測試資料）、`app_role`、兩個共用
trigger function（`forbid_update_delete`、`set_updated_at`），以及 `case_record`／
`case_conversation`／`complaint`。對應 `specs/domain/case.schema.json`、
`specs/domain/complaint.schema.json`。

每個租戶表都 `ENABLE ROW LEVEL SECURITY` 並 `FORCE ROW LEVEL SECURITY`，policy 比對
`current_setting('app.tenant_id', true)`；由 `app_role`（非 superuser、非 table owner）
連線才會真正受限，migration 本身用的 admin 角色不受 RLS 限制。

## Rollback

`0001_tenancy_and_core_case.down.sql` 對空庫（无业务资料）安全：依賴順序刪除
`complaint` → `case_conversation` → `case_record` → 兩個 trigger function →
`tenant`，並 `DROP EXTENSION pgcrypto`。`app_role` 是 cluster-level 角色，不在這裡刪除
（见 down.sql 內註解）。

## Forward-fix（已有正式資料時，不能用 rollback 的情境）

一旦 `case_record`/`complaint` 已有正式租戶資料，直接 rollback 會刪除這些表、連帶刪除
引用它們的 `case_conversation`／之後 migration 的外鍵資料。正式環境改用 forward-fix：
新增一個後續 migration 修正欄位/約束（例如新增可為 null 的欄位、新增 CHECK 並先以
`NOT VALID` + 背景 `VALIDATE CONSTRAINT` 避免長鎖表），不對已上線 schema 執行破壞性
rollback。本檔的 `.down.sql` 只保證「空庫 rebuild」情境（backlog ENG-02 驗收：空庫升級、
重建）可重複執行，不是正式環境的回復手冊。
