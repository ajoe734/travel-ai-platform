# ENG-08 驗收對照

本輪修復基線：`4944cfff5de286bc2b21c00b9afd09b1a6cd0d61`（reviewer reopen）；本文件所在
closeout commit 是待交審的新 candidate，SHA 與 hosted run 由 handoff machine truth 鎖定。服務層
測試只替換 persistence 邊界，不替換 `PublicationService`、ENG-04 `OperationResult` 或 mock adapter。
本 VM 沒有 psycopg/PostgreSQL；下列標為 DB 的案例必須由 hosted CI 的正式 migration/repository
路徑執行，不能把本機 syntax pass 當成 PostgreSQL 驗收。

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| R2 rollback：`DISPATCHING → UNKNOWN` | `0008_publication_dispatch_claim.down.sql` 對 `reconciliation_token` 使用 `COALESCE(..., 'rollback-dispatch-claim:' \|\| business_key)` | 舊版在 `DISPATCHING` 且 token 為 NULL 時違反 0007 `publication_unknown_has_reconciliation` CHECK；新版 downgrade SQL 留下 deterministic token | 靜態 SQL 與 migration 約束逐欄核對；hosted `db-migration-lifecycle` 待新 candidate | 本機無 PostgreSQL，空庫 downgrade 不足以覆蓋此列資料情境 |
| F4 R4：item expiry、JSON 型別與 base version binding | `service.py::_scope_matches` 現收 `now` 並用 `is_at_or_before` 拒絕 scope item expiry；`_assert_approval_integrity` 對 content 使用 canonical payload hash、且比對 payload 中存在的 `base_version` | 舊 `expires_at=2020` scope 在 2026 仍可用，`True == 1` 可繞過內容比對，base version 未綁定；新 unit 四個拒絕案例均通過 | `python3 -m unittest tests.publication_service_test -v` → 15 passed, exit 0（本機 Python 3.12） | DB approval-record 路徑待 hosted DB suite；真實商家批准／帳號未驗 |
| R-BASE：base version 綁定的核准在發佈前重驗 | `publication_repository.get_publication_service_version` 讀取 `sv.base_version`；`PublicationService.prepare_publications` 與 `claim_dispatch` 都傳遞該持久化值給 `_assert_approval_integrity`；base version 採 canonical JSON hash，比較不接受 `True == 1` | 舊候選可建立 `approved_payload.base_version=1` 的 v2，但 prepare/claim 省略該值而一律 BLOCKED `APPROVAL_CONTENT_MISMATCH`；新版 DB regression 以 v1 綁定建立 v2，完整跑 `create_approved_version → prepare_publications → claim_dispatch`，三個已核准渠道都可 claim，PMS 僅因不支援而獨立 BLOCKED | `python3 -m unittest tests.publication_service_test -v` 及 hosted `db-repository-tests`（新 candidate）待本輪執行；測試：`tests/db/test_publication_workflow.py::test_multi_channel_partial_publication_retry_and_summary` | 本機無 psycopg/PostgreSQL；真實 OTA/PMS、browser、worker scheduler 不屬本候選驗證 |
| F6：mock patch binding | `tests/publication_service_test.py` 將 `observe_publication` 的 patch 明確綁到 `observe`，不再把 `has_newer_live_publication`／`get_service_version` 誤當寫入 mock | 舊測試的 call-count 不驗證實際寫入 boundary；新版 `observe.assert_called_once()`／`assert_not_called()` 直接核對 | 同上，14 passed | 仍是 repository-boundary unit test；SQL CAS 由 DB suite 驗證 |
| 多渠道部分成功、PMS capability 與 retry | `tests/db/test_publication_workflow.py::test_multi_channel_partial_publication_retry_and_summary` 使用正式 repository：website LIVE、OTA-1 PENDING→UNKNOWN、OTA-2 REJECTED→FAILED、PMS BLOCKED；assert `publication_summary` 和 `publication_call_count == 0`，並只重開 FAILED | 前候選只有一個 OTA、沒有 REJECTED/summary/PMS/retry 實證；新增案例保留每一列獨立狀態，且 LIVE/UNKNOWN/BLOCKED retry 皆拒絕 | `python3 -m py_compile tests/db/test_publication_workflow.py` → exit 0；hosted `db-repository-tests` 待新 candidate | 本機缺 psycopg/PostgreSQL；mock 不代表真實 OTA/PMS |
| 舊事件不覆蓋新版 | `test_late_v1_readback_cannot_overwrite_real_newer_live_publication` 以 production `has_newer_live_publication` SQL join 建立 v2 LIVE，再送 v1 成功 readback | 舊事件不應把 v1 推到 LIVE；新 DB 測試 assert SQL 回 true、v1 維持 PENDING 與 revision 不變 | py_compile exit 0；hosted `db-repository-tests` 待新 candidate | 本機無 PostgreSQL |
| 前輪既有 migration/DB 證據 | `0007_service_version_publication` + `0008_publication_dispatch_claim`；workflow count 8 | 舊 migration collision 已解；基線 candidate 的 hosted CI 完成 0→8→0→8 及 repository suite | GitHub Actions run `45990635589`（SHA `4944cfff`）：validate、db-migration-lifecycle、db-repository-tests 全綠，**36 passed** | 此 run 不涵蓋本輪新測試；不可當作新 candidate green |

本機已完成：`python3 -m unittest tests.publication_service_test -v`（14 passed）、
`python3 -m py_compile services/publication/service.py tests/publication_service_test.py tests/db/test_publication_workflow.py`
（exit 0）與 `git diff --check`（exit 0）。交審前仍需跑完整 unittest、repository validation 與
hosted PostgreSQL migration/repository checks；真實 OTA/PMS、browser 和 worker scheduler 不屬本候選驗證。
