# ENG-08 驗收對照

執行環境：本機 Python 3。服務層測試只替換 repository 邊界，不替換
`PublicationService`、ENG-04 `OperationResult` 或 mock adapter；本 VM 沒有 psycopg/PostgreSQL，
資料庫案例由 hosted CI 的正式 migration/repository 路徑執行。

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| F2：OTA REJECTED crash | `service.py::record_connector_result` 不再讀取 `Failed.external_reference` | 舊候選會 `AttributeError`；`test_rejected_ota_reconcile_maps_failed_without_missing_external_reference` 以正式 Ota mock 的 REJECTED readback 寫成 FAILED | `python3 -m unittest tests.publication_service_test -v` → 8 tests, exit 0 | DB write 分支待 hosted |
| F3：stale readback 不得 brick v2 | 同函式在 source revision 過舊時不寫入；成功時核對 external reference | 舊候選把 v1 readback 寫成 terminal FAILED；`test_stale_readback_does_not_brick_new_version_then_matching_readback_lives` 證明 v2 隨後可 LIVE | 同上 | DB optimistic CAS 待 hosted |
| 批准、差異及舊訂單 | migration 的 approval FK/不可變 trigger/base_version/change_diff；`create_approved_version` 驗有效期、撤回、canonical hash 與 manifest | `test_approved_version_is_immutable_and_keeps_old_order_untouched` 建立有效批准、讀回差異、驗 admin UPDATE 被拒；migration 不修改 `order_record` | hosted `db-repository-tests` | 本機無 PostgreSQL；既有 Order 升級未實跑 |
| 每渠道獨立與部分成功 | 每渠道 publication key、`publication_summary`、正式 Ota UNKNOWN→reconcile | `test_ota_unknown_then_reconcile_and_rejected_are_independent_and_summarised` 讀到獨立 LIVE summary | hosted `db-repository-tests` | 真實 OTA 未驗 |
| PENDING/UNKNOWN 與 schema integrity | migration tenant FK、service-version 三欄 FK、PENDING/UNKNOWN/FAILED/BLOCKED CHECK | `test_known_pending_is_not_unknown`；DB `test_publication_rls_and_pending_constraints` 驗 PENDING 缺 token 被拒與跨 tenant 讀取不可見 | scoped unit exit 0；DB hosted pending | 本機無 PostgreSQL |
| 能力預檢與重試邊界 | `prepare_publications` 的四維 capability check、`retry_failed_publication` | `test_unsupported_pms_is_blocked_before_dispatch` 驗 Pms mock call count 0；disabled access 案例保持 BLOCKED | scoped unit exit 0 | 真實帳號權限未驗 |
| F1 migration count | workflow assertion 已於前候選 `bc9091c` 修成 6 | hosted migration lifecycle 曾對該候選通過；本輪 schema 變更需重新跑同 job | hosted CI pending for closeout candidate | 不以舊 SHA CI 冒充本輪結果 |

修復 anchor：`17c4c1cc9ac9fc2537def20ad3dcef03229fb6e4`；closeout candidate 的完整 SHA 以 handoff machine truth 為準。
本機已執行：`python3 -m unittest tests.publication_service_test -v`（8 passed）、
`python3 -m py_compile tests/publication_service_test.py tests/db/test_publication_workflow.py services/publication/service.py db/repository/publication_repository.py`（exit 0）、
`git diff --check`（exit 0）、`python3 -m unittest discover -s tests -p '*_test.py' -v`（162 passed）及
`python3 scripts/validate_repository.py`（passed；12 originals、251 local links、4 JavaScript）。未執行：
`tests/db/test_publication_workflow.py`；本 VM 缺 psycopg/PostgreSQL，需 hosted `db-repository-tests` 驗證。
