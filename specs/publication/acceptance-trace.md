# ENG-08 驗收對照

執行環境：本機 Python 3；服務層測試只替換 repository 邊界，不替換
`PublicationService` 或 ENG-04 `OperationResult` 型別。未啟動 PostgreSQL、瀏覽器或真實
渠道；PostgreSQL migration/RLS 的正式路徑交由本候選 push 後的 hosted CI 驗證。

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| 官網成功不使 OTA 同時成功；部分成功可呈現 | `db/migrations/0006_service_version_publication.up.sql` 的 `(tenant_id, id)` 主列與每渠道唯一鍵；`services/publication/service.py::record_connector_result` 僅以傳入的 `publication_id` 寫入 | `ResultSafetyTest.test_matching_formal_readback_marks_only_that_publication_live` 對 website publication 的同版正式 readback，只呼叫 website ID 的 `observe_publication`；不會觸及 OTA ID | `python3 -m unittest tests.publication_service_test -v` → 4 tests, exit 0；本候選 `1399934` 後新增案例，完整輸出見本 task handoff | 服務層測試替換 repository 邊界；每渠道資料列/RLS/transaction 需 hosted PostgreSQL CI 驗證 |
| 已知審核中不當 UNKNOWN | `PublicationService.record_connector_result` 的 `Pending → PENDING` 映射；`channel_publication.status` CHECK | `ResultSafetyTest.test_known_pending_is_not_unknown`：正式 `Pending` 結果保存為 `PENDING` | 同上 | 尚未對真實 OTA 審核帳號驗證 |
| 新版本不改寫舊訂單承諾 | `service_version` 為 append-only（`service_version_immutable` trigger）；本 migration 未修改 `order_record` | 靜態核對：`0006` 僅新增 service/publication tables，版本以 `(tenant_id,service_id,version)` 唯一，不會 UPDATE 已有 Order | migration SQL 人工核對；hosted `db-migration-lifecycle` 在候選 push 後待執行 | 本機沒有 PostgreSQL；不能把 migration 靜態核對宣稱為既有訂單實際升級驗收 |
| 各渠道讀回正式版本後才完成；舊事件不蓋掉新版 | `record_connector_result` 的 `source_revision == desired_version` 比對與 optimistic `expected_revision`；`publication_live_is_readback` constraint | `test_source_revision_must_match_before_live`：source revision `1`、desired `2` → `FAILED/STALE_CHANNEL_READBACK`；`test_matching_formal_readback_marks_only_that_publication_live`：source revision `2` → `LIVE` | 同上 | DB CAS/constraint 的實際執行待 hosted PostgreSQL CI |
| 發布不支援或權限失效有清楚待處理原因 | `prepare_publications` 讀 `channel_publication_access`；`PublicationPreparationTest.test_disabled_channel_is_blocked_without_a_dispatch_intent` | OTA access disabled 並給 `CHANNEL_AUTHORIZATION_EXPIRED` 時，只回 website dispatch intent；OTA 保存 `BLOCKED` 與同一原因 | 同上 | capability descriptor 與 adapter 的實際帳號授權整合仍屬後續渠道啟用範圍 |
| CI migration lifecycle 隨 0006 失敗 | `.github/workflows/repository-validation.yml` 的 empty-db/rebuild assertions | 前候選 `99d9de4264d3` 的 hosted run `45985067237`/job `140458457558`：upgrade 已套用 `0001`–`0006`，但 workflow 寫死 `expected 5 applied migrations, got 6`。修正版 `1399934` 將兩個完整 migration-set 斷言改為 `6` | `git diff 99d9de4..1399934 -- .github/workflows/repository-validation.yml`；`python3 scripts/validate_repository.py` → exit 0 | 修正版 hosted CI 尚未完成；不得把舊 SHA 的 failure 當新 SHA 結果 |

本機整體回歸：`python3 -m unittest discover -s tests -p '*_test.py' -v` → 158 tests,
exit 0；`python3 scripts/validate_repository.py` → exit 0（12 original files、247 local links、4 JavaScript scripts）；
`python3 -m py_compile tests/publication_service_test.py services/publication/service.py db/repository/publication_repository.py db/migrate.py` → exit 0。
