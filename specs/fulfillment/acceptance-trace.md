# ENG-05 驗收對照表

依 [AI_COLLABORATION_GUIDE.md §0.7](../../AI_COLLABORATION_GUIDE.md) 的交付證據表格式，逐項對照
[backlog ENG-05](../../docs/collaboration/backlog.md#eng-05第一條接單耐久流程) 的八項驗收句。

執行環境：本機沙箱 VM 沒有網路安裝 `psycopg`、沒有本機 Postgres（與
[db/README.md 本機無法執行的部分](../../db/README.md#本機無法執行的部分)相同限制）。以下每一列的「結果」
欄只記錄本機靜態驗證（`python3 -m py_compile`、手動核對 SQL 與 schema、`scripts/validate_repository.py`）；
真正跑過 `tests/db/test_fulfillment_workflow.py` 的結果由 `.github/workflows/repository-validation.yml`
既有的 `db-repository-tests` job（`pytest tests/db -v`）產生——這份檔案沒有新增 job，該 job 本來就會收錄新檔案。
在讀到那次 hosted CI 結果之前，以下驗收屬「已實作、未在真實資料庫執行過」，不是「已通過」。

## 八項驗收句對照

| 驗收項（backlog 原文） | 原始碼依據與修改位置 | 對應測試 | 命令與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| 正常完成 | `services/fulfillment/service.py` `accept_order`→`approve_consent`(approve)→`dispatch_booking`→`_complete_booking`：RUNNING→WAITING_DECISION→RUNNING→VERIFYING→COMPLETED，`order_record.supplier_booking_status`→CONFIRMED | `test_normal_completion_has_real_completion_evidence` | `pytest tests/db/test_fulfillment_workflow.py::test_normal_completion_has_real_completion_evidence -v`（未在本機執行；由 hosted `db-repository-tests` 執行，見下方「本機靜態驗證」） | 只驗證 `ExperienceReservationMock` 的同步成功路徑；真實供應商帳號、真實付款捕獲不在本輪 |
| Worker 重啟後可延續 | `services/fulfillment/service.py` 的 `worker_connection_factory` 對每個 worker transaction 開新連線；`dispatch_booking`／`reconcile_booking` 固定切成 TX1 durable intent → 無 DB transaction 的 connector I/O → TX2 outcome。`test_restart_continuation_...` 驗 UNKNOWN 查核，`test_crash_after_external_success_...` 驗外部成功後 TX2 前崩潰仍以 stable business key lookup 恢復 | `test_restart_continuation_reconciles_an_unknown_task_via_lookup_not_a_new_create`、`test_crash_after_external_success_recovers_executing_intent_via_lookup` | `pytest tests/db/test_fulfillment_workflow.py -v`（未在本機執行；由 hosted `db-repository-tests` 執行） | 只模擬「同一 Postgres、新連線」的重啟；真正跨 process／跨機器重啟（例如 Temporal worker 换節點）的 lease 交接時序本輪未另外驗證，但 `execution_task.lease_fence_token` 的單調遞增本身就是為此設計 |
| 重複／亂序 webhook 不倒退狀態 | `services/fulfillment/service.py` `process_booking_webhook`：先呼叫 `outbox_inbox_repository.record_inbound_event` 去重；任務已是 `DONE`/`FAILED`/`CANCELLED` 時直接回 `applied=False` 並 ACK，不重新套用事件 | `test_duplicate_and_stale_webhook_never_regress_an_already_terminal_task` | 同上 | 只驗證同 tenant 單一 task 的晚到/重複事件；跨 connector_account/environment 的簽章驗證（SD §7 "驗 provider 原始簽章"）不在本輪範圍，`process_booking_webhook` 的呼叫端目前信任已驗簽的上游 |
| 取消與執行競態有明確結果 | `services/fulfillment/service.py` `cancel_booking`／`dispatch_booking` 皆以 `execution_task.revision` 的樂觀鎖做唯一仲裁；`db/repository/execution_repository.py` `update_task_status` 的 `WHERE revision = %s` 由 Postgres 列鎖序列化兩筆交易 | `test_cancel_vs_dispatch_race_has_exactly_one_deterministic_winner`（兩條執行緒、兩條獨立連線、`threading.Barrier` 對齊） | 同上 | 只驗證「同一 task 的取消 vs 第一次 dispatch」；取消 vs reconcile（已在 WAITING/UNKNOWN 之後）本輪由 `TaskAlreadyDispatchedError` 一律拒絕取消，未另寫競態測試 |
| 未知結果不盲目重送 | `services/fulfillment/service.py` `dispatch_booking(simulate_timeout=True)` 只送出一次 `create_booking`；`reconcile_booking` 永遠呼叫宣告唯讀的 `lookup_booking`，從不呼叫 `create_booking` 第二次 | `test_restart_continuation_...` 最後以 `len(fulfillment._connector._store._records) == 1` 證明整個流程只建立過一筆外部資源 | 同上 | 只驗證單一 task 一次 timeout 後的查核；長期停留 UNKNOWN 超過多次排程 tick 的退避頻率曲線本輪未定義（SD §5 "重試間隔...由 capability/operation policy 設定"，本候選未實作該 policy 層） |
| 超過查核期限產生待處理工作 | `services/fulfillment/service.py` `check_deadlines`→`work_repository.create_escalation_if_absent`：UNKNOWN／WAITING 逾 `deadline` 只建立 `Escalation`（`status=OPEN`），不改變 task／Work 狀態；兩次呼叫不重複建立（`get_open_escalation_for_task` 先查） | `test_overdue_unknown_task_gets_one_idempotent_escalation_not_an_automatic_failure` | 同上 | 只驗證單一 task 的 escalation 冪等性；`due_at`／值班角色的實際指派流程（通知誰、SLA）本輪未實作，`owner` 由呼叫端直接指定 |
| 未取得外部證據不得顯示完成 | `services/fulfillment/service.py` `_complete_booking` 一律先 `work_repository.create_completion_evidence` 寫入不可變 `completion_evidence` 列，取得其 `id` 後才呼叫 `update_work_status(new_status="COMPLETED", completion_record={"evidence_refs": [...]})`；DB 層另有 `db/migrations/0002` 的 `work_completion_record_matches_status` CHECK 做第二層保證 | `test_normal_completion_has_real_completion_evidence`（直接查 `completion_evidence` 表確認至少一列） | 同上 | 只驗證「本流程唯一的完成路徑確實先寫證據」；沒有另外測試「繞過 service 直接對 DB 下指令可否偽造完成」，那屬 DB CHECK 約束本身的職責（已在 0002 migration 存在，非本輪新增） |
| 通知失敗與預訂失敗分開 | `services/fulfillment/service.py` `send_notification` 是獨立 `ExecutionTask`（`operation=notification.send`），失敗只建立該 task 自己的 `Escalation`，完全不呼叫 `work_repository.update_work_status`——已 `COMPLETED` 的 Work 不受影響（SD-W-09） | `test_notification_failure_is_separate_from_booking_success` | 同上 | 只驗證「通知失敗不影響已成功的預訂」；通知重送的實際排程（誰在什麼時候重送）本輪未實作，只建立 Escalation 標記待處理 |

## R1 退修紀錄（candidate `a3e44e2` → owner branch `e9776de`）

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| F1 UUID JSON 序列化 | `connectors/idempotency.py:request_hash`、`db/repository/outbox_inbox_repository.py` | 舊 hosted CI 的 webhook／notification 以 psycopg `UUID` 呼叫 `json.dumps` 會 `TypeError`；hash 與 inbox JSON 現統一以 `default=str` 正規化 | `python3 -m py_compile ...` exit 0；需 hosted PostgreSQL 重跑原兩案例 | 尚未讀到新 hosted run |
| F3 取消 vs dispatch | `execution_repository.claim_new_task_for_dispatch`、`FulfillmentService.dispatch_booking` | 舊版先取得 lease、寫 attempt 後才 revision lock；現以 `status='NEW'` 單一條件 UPDATE 取得 lease、轉 `EXECUTING`，失去競態時不寫 attempt、不呼叫 connector | `python3 -m py_compile ...` exit 0；`test_cancel_vs_dispatch_race_has_exactly_one_deterministic_winner` 需 hosted PostgreSQL | 要在 hosted run 確認 cancel winner 的 attempt count=0 |
| F4 hash／同意範圍／撤回 | `accept_order`、`approve_consent`、`_assert_dispatch_approval`、`approval_repository` | 舊版使用無 prefix hash、沒有 `work_id`／角色／scope／expiry 檢查；現採 `canonical_json.payload_hash`，核對 decision 綁定與 scope，發出前重新核對 approval expiry/revocation | `python3 -m py_compile ...` exit 0 | 尚缺實際 DB 負向案例與 hosted 結果 |
| F5 webhook fence、通知重試 | `process_booking_webhook`、`send_notification` | 舊版 webhook 使用舊 fence，通知固定 attempt=1 且 DONE 會重送；現 webhook 套用前取得 lease/fence，通知 DONE no-op、retry 使用 next attempt number | `python3 -m py_compile ...` exit 0 | 尚缺 applied=True、same source ID different payload、notification retry 的 DB 例 |
| F2 外部 I/O transaction boundary | `FulfillmentService._worker_transaction`、`dispatch_booking`、`reconcile_booking`；`test_crash_after_external_success_recovers_executing_intent_via_lookup` | 舊版在 caller tenant transaction 內 claim/attempt 後直接 connector I/O，外部成功與本地 rollback 會回到 NEW。新版以 fresh worker connection 提交 TX1 `EXECUTING` + `DISPATCH` attempt，交易外呼叫 connector，再以 fresh TX2 保存結果；若 TX2 前崩潰，`EXECUTING` 在 lease 過期後只能 lookup，不可重送。 | `python3 -m py_compile services/fulfillment/service.py tests/db/test_fulfillment_workflow.py` exit 0；`pytest tests/db/test_fulfillment_workflow.py::test_crash_after_external_success_recovers_executing_intent_via_lookup -v` 待 hosted PostgreSQL | 本機無 psycopg/PostgreSQL，尚未讀到本 SHA 的 hosted run；外部邊界是 `ExperienceReservationMock`，未涵蓋真實供應商 |

## R2 CI 退修紀錄（candidate `9aebed8a`）

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| Hosted DB：合法 Work 綁定被錯拒 | `FulfillmentService.approve_consent` 的 DecisionRequest `work_id` 比對 | `9aebed8a` 在 GitHub Actions run `45981333112` 的 `pytest tests/db -v` 中，所有 9 個 ENG-05 workflow 測試都因 `str(decision["work_id"]) != work_id`（psycopg `UUID` 對 API string）誤拋 `WORK_PHASE_MISMATCH`；修正版以 `str()` 正規化兩側後仍要求相同 canonical Work ID，沒有移除 tenant／Work 歸屬檢查。 | 最小正式重現：`pytest tests/db/test_fulfillment_workflow.py::test_normal_completion_has_real_completion_evidence -v`；舊候選由 hosted run 失敗（9 failed, 10 passed）。本機無 psycopg/PostgreSQL，修正版須等待下一個 hosted `db-repository-tests`。 | 本機只能跑語法與非 DB 回歸；hosted DB run 尚未產生 |
| Hosted DB：cancel 勝出時 worker 誤拋 phase error | `FulfillmentService.dispatch_booking` 的 TX1 state gate | `1b9b06b` 在 GitHub Actions run `45981629163` 使 7 個 workflow 測試通過，但 cancel 勝出後 dispatch 讀到 `CANCELLED` 時誤拋 `WORK_PHASE_MISMATCH`，留下執行緒結果為空；修正版明確回傳 `CANCELLED_BEFORE_DISPATCH`，而且在寫 attempt／呼叫 connector 前返回。 | 最小正式重現：`pytest tests/db/test_fulfillment_workflow.py::test_cancel_vs_dispatch_race_has_exactly_one_deterministic_winner -v`；舊候選 hosted 結果 `TypeError: 'NoneType' object is not subscriptable`，根因見同 run 的 dispatch thread stack trace。 | 本機無 psycopg/PostgreSQL；下一個 hosted DB job 待驗 |
| Hosted DB：通知 task snapshot 含 UUID 無法寫 JSONB | `execution_repository.create_execution_task` 的 JSONB serialization | `1b9b06b` 的 notification acceptance test 將 repository 回傳的 `uuid.UUID` 放入 notification snapshot；`json.dumps` 直接崩潰。修正版在正式 repository JSONB 邊界統一以 `default=str` 持久化 canonical wire IDs，並不改變 task 的 tenant／business-key 去重條件。 | 最小正式重現：`pytest tests/db/test_fulfillment_workflow.py::test_notification_failure_is_separate_from_booking_success -v`；舊候選 hosted 結果 `TypeError: Object of type UUID is not JSON serializable`（run `45981629163`，2 failed, 17 passed）。 | 本機無 psycopg/PostgreSQL；下一個 hosted DB job 待驗 |

R2 修正版 candidate `c2994fe8a81e91e0a26b0ce4b3392032b03d48c8` 已由 GitHub Actions
run `45981890206` 的 `db-repository-tests` 實際執行確認：`19 passed in 0.89s`。
同 run 的 `validate` 與 `db-migration-lifecycle` 亦通過；這些是 PostgreSQL container
模擬與 repository 層驗證，不是實際供應商或生產驗收。

## 本機靜態驗證（已實跑，非假設）

```text
$ python3 -m py_compile db/repository/*.py services/fulfillment/*.py tests/db/test_fulfillment_workflow.py
exit 0，無輸出

$ python3 -m unittest tests.domain_contract_test tests.connector_contract_test tests.authorization_service_test tests.workbench_service_test -v
Ran 154 tests in 3.869s — OK
（確認既有既合併測試套件未被本次變更破壞——本候選沒有改動 specs/domain/*.schema.json 的任何既有欄位，
 只在 specs/domain/error-codes.json 追加兩個新錯誤碼 TASK_LEASE_CONTENDED／TASK_ALREADY_DISPATCHED，
 兩者皆為新增 x_added_by:"ENG-05" 條目，未改動既有條目）

$ python3 scripts/validate_repository.py
Repository checks: passed
Original files verified: 12
Local documentation links checked: 247
JavaScript scripts checked: 4
```

`db/migrate.py upgrade|downgrade|status` 與 `pytest tests/db` 在本機無法執行（無 `psycopg`、無本機
Postgres）；上列指令的實際退出碼與輸出，見 handoff 時附上的本機執行紀錄。

## 後續工程

- 把 `services/authorization/service.py`（ENG-03）的 `ExecutionAuthorization`／`AuthorizationUse` 判定邏輯
  接到 `db/repository`，取代本候選直接使用 `approval_repository.py` 的簡化同意閘門。
- `check_deadlines`／`list_tasks_due_for_reconciliation` 目前由呼叫端（測試或未來的排程器）主動呼叫；
  真正的排程 worker（cron／Temporal timer）屬 ENG-07／09 範圍，本輪只固定它們要呼叫的函式介面。
- 退避頻率、`deadline`／`escalation_due_seconds` 的實際秒數目前由呼叫端傳入常數，不是正式政策值
  （AGENTS.md「不預設商業條件」）；正式值由部署設定決定。
