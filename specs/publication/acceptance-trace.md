# ENG-08 驗收對照

執行環境：本機 Python 3。服務層測試只替換 repository 邊界，不替換
`PublicationService`、ENG-04 `OperationResult` 或 mock adapter；本 VM 沒有 psycopg/PostgreSQL，
資料庫案例由 hosted CI 的正式 migration/repository 路徑執行。

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| F2：OTA REJECTED crash | `service.py::record_connector_result` 不再讀取 `Failed.external_reference` | 舊候選會 `AttributeError`；`test_rejected_ota_reconcile_maps_failed_without_missing_external_reference` 以正式 Ota mock 的 REJECTED readback 寫成 FAILED | `python3 -m unittest tests.publication_service_test -v` → 11 tests, exit 0 | DB write 分支待 hosted |
| F3：過期／終態與跨版本 readback | `record_connector_result` 拒絕 `FAILED → PENDING`，並在寫 LIVE 前由 repository 查詢同 target 的較新 LIVE 版本 | `test_late_pending_cannot_regress_failed_publication` 及 `test_late_old_version_readback_cannot_overwrite_newer_live_target` 均驗證不寫入 | 同上；跨版本 SQL path 待 hosted | 本機無 PostgreSQL |
| F4：批准內容、tenant、scope 與撤回 | `create_approved_version` 以 `canonical_json.payload_hash` 綁 `approved_payload.content`；`prepare`／`claim_dispatch` 每次重查有效期、`resource_ref.tenant_id`、service/version、channel/account | DB `test_approval_content_tenant_expiry_and_revocation_are_rechecked` 驗 tampered price、錯 tenant、過期拒絕；`test_unapproved_target_and_revocation_block_before_connector_write` 驗未授權 target 與撤回後 connector backend 為空 | `pytest tests/db/test_publication_workflow.py -v` hosted pending | 本機缺 psycopg/PostgreSQL |
| F7：外部 I/O 交易邊界 | `claim_dispatch`/`claim_reconciliation` 為 TX1；`dispatch_publication`/`reconcile_publication` 只回 connector result；`record_connector_result` 為 TX2。0007 加入 durable `DISPATCHING` CAS claim | DB workflow 明確在 transaction 外呼叫兩個 connector 方法；`BLOCKED`、批准撤回與 capability 不會生成 dispatch | scoped unit 11 passed；hosted DB pending | 尚未接入 worker/outbox scheduler；無真實 OTA |
| 批准、差異及舊訂單 | migration approval FK/不可變 trigger/base_version/change_diff；`create_approved_version` 驗完整批准 binding | `test_approved_version_is_immutable_and_keeps_old_order_untouched` 現建立 payment/order chain，讀回差異並確認既有 order 金額未變 | hosted `db-repository-tests` | 本機無 PostgreSQL |
| 每渠道獨立與部分成功 | 每渠道 publication key、`publication_summary`、正式 Ota UNKNOWN→reconcile | `test_ota_unknown_then_reconcile_and_rejected_are_independent_and_summarised` 讀到獨立 LIVE summary | hosted `db-repository-tests` | 真實 OTA 未驗 |
| PENDING/UNKNOWN 與 schema integrity | migration tenant FK、service-version 三欄 FK、PENDING/UNKNOWN/FAILED/BLOCKED CHECK | `test_known_pending_is_not_unknown`；DB `test_publication_rls_and_pending_constraints` 驗 PENDING 缺 token 被拒與跨 tenant 讀取不可見 | scoped unit exit 0；DB hosted pending | 本機無 PostgreSQL |
| 能力預檢與重試邊界 | `prepare_publications`／`claim_dispatch` 的四維 capability check、`PublicationService.retry_failed_publication` | `test_unsupported_pms_is_blocked_before_dispatch` 驗 Pms mock call count 0；`test_retry_uses_the_same_claim_gate_and_refuses_non_failed_rows` 驗非 FAILED 不可重開且 retry 必重走 claim gate | scoped unit 11 passed | 真實帳號權限未驗 |
| F1 migration lifecycle 與 ENG-10 共用序列 | `0007_service_version_publication`、`0008_publication_dispatch_claim`；workflow count 8 | 前候選的兩個 0006 導致 runner 僅能取其一；同步 `dev` 後保留 ENG-10 0006，ENG-08 順序化為 0007/0008，並修正舊訂單 numeric 斷言 | 本機靜態 migration discovery、publication/full unit tests、repository validation；hosted lifecycle 與 DB suite 待此 SHA | 不以舊 SHA CI 冒充本輪結果 |

修復 anchor：`17c4c1cc9ac9fc2537def20ad3dcef03229fb6e4`；closeout candidate 的完整 SHA 以 handoff machine truth 為準。
本機已執行：`python3 -m unittest tests.publication_service_test -v`（11 passed）、
`python3 -m py_compile tests/publication_service_test.py tests/db/test_publication_workflow.py services/publication/service.py db/repository/publication_repository.py`（exit 0）、
`git diff --check`（exit 0）、`python3 -m unittest discover -s tests -p '*_test.py' -v`（162 passed）及
`python3 scripts/validate_repository.py`（passed；12 originals、251 local links、4 JavaScript）。未執行：
`tests/db/test_publication_workflow.py`；本 VM 缺 psycopg/PostgreSQL，需 hosted `db-repository-tests` 驗證。
