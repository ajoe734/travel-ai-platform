# ENG-05：第一條接單耐久流程

版本：v1，2026-11-27 新增。依 [backlog ENG-05](../../docs/collaboration/backlog.md#eng-05第一條接單耐久流程)
產出，讀取順序見 [AI_COLLABORATION_GUIDE.md §1](../../AI_COLLABORATION_GUIDE.md)：先讀
[SD work-execution-contract.md](../../docs/sd/work-execution-contract.md) 與
[connector-result-and-reconciliation.md](../../docs/sd/connector-result-and-reconciliation.md)，
再讀 [ENG-01 domain 契約](../domain/README.md)、[ENG-02 db 層](../../db/README.md)、
[ENG-03 授權](../authorization/README.md)、[ENG-04 connector](../connector/README.md)——本目錄是把這四項既有產出
接成第一條可執行、可重啟、可核對的接單流程，不是另起一套新語意。

## 這個目錄回答什麼問題

HerdR 第一個工程里程碑要求「建立接單案件與工作 → 取得資料 → 形成正式報價 → 判定授權 → mock 預訂 →
外部結果查核 → 保存完成證據」可在本機（經由 hosted CI 的真實 Postgres）跑通一次，並通過重啟、重複
webhook、取消競態、UNKNOWN 不盲目重送、查核逾時、通知與預訂分離六項反例。本目錄：

1. 用 `db/repository/work_repository.py`、`db/repository/fulfillment_repository.py`，以及對
   `db/repository/execution_repository.py`／`outbox_inbox_repository.py`／`approval_repository.py`
   的擴充，把 ENG-02 已建好但尚無 repository 函式的 `work`／`execution_task`（lease／fence）／
   `quote_snapshot`／`order_record` 四張表接上真正的讀寫路徑。
2. 用 `services/fulfillment/service.py` 的 `FulfillmentService` 把上述持久層、ENG-04 的
   `ExperienceReservationMock`，以及 ENG-02 已有的 `decision_request`／`approval_record` SQL
   （`db/repository/approval_repository.py`）接成一條完整流程：`accept_order` → `approve_consent` →
   `dispatch_booking` → `reconcile_booking`／`process_booking_webhook` → `check_deadlines`／
   `cancel_booking`／`send_notification`。
3. 用 `tests/db/test_fulfillment_workflow.py`（pytest，須真實 Postgres，見下方「如何驗證」）逐項驗證
   backlog ENG-05 的驗收句，對照見 [acceptance-trace.md](acceptance-trace.md)。

這是把既有四項產出接成一條耐久流程的驗收，不是重新定義 Work／ExecutionTask／Connector 契約；本目錄
沒有新增或修改 `specs/domain/*.schema.json` 的欄位形狀。

## 範圍邊界（依 AI_COLLABORATION_GUIDE.md §0.7 揭露）

- **授權／同意**：本候選直接呼叫 `db/repository/approval_repository.py` 的 `create_decision_request`／
  `approve_decision`／`reject_decision`（皆為已合併、已走過 revision guard 的真 SQL），作為這條流程的同意
  閘門。`services/authorization/service.py`（ENG-03）針對 `ExecutionAuthorization`／`AuthorizationUse` 的
  manifest 消耗鏈，建在一個獨立的 `InMemoryAuthorizationRepository` 上，本候選未將它接上
  `db/repository`——`execution_task.authorization_use_id` 在本流程中維持 `NULL`（schema／DB CHECK 皆允許
  此狀態）。把 ENG-03 的判定邏輯接到持久層，是後續任務，不在本候選重做一次。
- **Connector**：只使用 `ExperienceReservationMock`（同步、TIMESLOT）。`booking.create` 本身永遠終局
  （`Succeeded`／`Failed`），所以 UNKNOWN／逾時案例是在 worker 呼叫端模擬「已送出但沒收到回應」
  （`dispatch_booking(simulate_timeout=True)`：mock 的 ledger 真的寫入一筆，呼叫端刻意不讀取回應），
  之後用 `booking.lookup`（已宣告唯讀）的 `reconcile_booking` 找回同一筆結果——這正是
  [SD-C-01](../../docs/sd/connector-result-and-reconciliation.md) 的情境，不是虛構一個新的 mock 行為。
- **通知**：`send_notification` 的 `notifier` 是呼叫端注入的 callable（測試用 `lambda: True/False`），
  不是新增的 connector 能力；真正的通知管道整合在後續任務。
- **並行驗證邊界**：取消與 dispatch 的競態（SD-W-11）靠 `execution_task.revision` 的樂觀鎖本身解題——兩個
  交易對同一列各自送出 `revision`-guarded `UPDATE`，Postgres 的列鎖決定先後，輸家收到
  `VersionConflict`。本目錄沒有另外引入 advisory lock 或應用層鎖。

## 如何驗證

```bash
pip install -r db/requirements.txt
export ENG02_ADMIN_DATABASE_URL=postgresql://admin_role:...@host:5432/eng05
python3 db/migrate.py upgrade   # 本流程完全建在既有 0001-0005 migration 上，沒有新增 0006
pytest tests/db/test_fulfillment_workflow.py -v
```

本機這台沙箱 VM 沒有網路安裝 `psycopg`、沒有本機 Postgres（與 [db/README.md 本機無法執行的部分
](../../db/README.md#本機無法執行的部分)相同限制）；`.github/workflows/repository-validation.yml` 既有的
`db-repository-tests` job（`pytest tests/db -v`）會原樣涵蓋這個新增檔案，不需要額外改 CI 設定或
`db-migration-lifecycle` 的 migration 計數（本候選沒有新增 migration 檔）。

## 目錄結構

| 路徑 | 內容 |
|---|---|
| `db/repository/work_repository.py` | Work／WorkPlan／WorkContext／CompletionEvidence／Escalation／WorkEvent 的讀寫 |
| `db/repository/fulfillment_repository.py` | QuoteSnapshot／Order 的讀寫（`order_record.supplier_booking_status` 的轉移） |
| `db/repository/execution_repository.py`（擴充） | `get_execution_task`／`list_tasks_for_work`／`acquire_lease`／`release_lease`／`update_task_status`／`list_tasks_due_for_reconciliation`／`list_tasks_overdue_for_escalation`／`next_attempt_no` |
| `db/repository/approval_repository.py`（擴充） | `get_decision_request`／`reject_decision` |
| `db/repository/outbox_inbox_repository.py`（擴充） | `mark_inbox_processed` |
| `services/fulfillment/service.py` | `FulfillmentService`：本目錄的流程引擎 |
| `services/fulfillment/errors.py` | 對照 `specs/domain/error-codes.json` 的例外類別 |
| `tests/db/test_fulfillment_workflow.py` | 驗收測試（真實 Postgres） |

## 與正式後端的邊界

本目錄沒有 HTTP 層；`FulfillmentService` 的每個公開方法對應一個未來端點（`accept_order` ≈
`POST /v1/works`、`approve_consent` ≈ `POST /v1/decisions/{id}/approve`、`process_booking_webhook` ≈
connector webhook 入口），但 HTTP 路由、認證與 session 推導 tenant_id 是後續任務範圍，延續
ENG-03／ENG-06 已採用的相同邊界揭露方式（`services/workbench/service.py`／`services/authorization/service.py`
的 docstring 皆同樣聲明尚無 HTTP handler）。
