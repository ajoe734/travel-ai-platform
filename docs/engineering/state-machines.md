# 狀態機與轉移條件 v0.1.0

本文件的狀態是平台內部狀態，不是任何供應商的原生狀態。Adapter 必須將供應商狀態映射至此模型，同時保存原始狀態字串與原始回應證據。

## 1. Case（接單／營運案件）

狀態：
- OPEN：已建立，尚未形成可執行工作。
- QUALIFYING：正在釐清需求。
- READY：必要資訊已齊，可建立／推進 Work。
- IN_PROGRESS：至少一項相關 Work 正在執行。
- WAITING_CUSTOMER：等待旅客補資料或確認。
- WAITING_MERCHANT：等待商家營運決定。
- RESOLVED：需求已處理並有結果。
- CLOSED：結案；不可直接恢復，需建立 follow-up Case 或 reopen command 並留稽核。
- SPAM、DUPLICATE：非有效需求／併案，需記錄原因與主案件。

允許轉移：
- OPEN → QUALIFYING / SPAM / DUPLICATE
- QUALIFYING → READY / WAITING_CUSTOMER / WAITING_MERCHANT / SPAM / DUPLICATE
- READY → IN_PROGRESS / WAITING_CUSTOMER / WAITING_MERCHANT
- IN_PROGRESS → WAITING_CUSTOMER / WAITING_MERCHANT / RESOLVED
- WAITING_CUSTOMER → QUALIFYING / READY / CLOSED
- WAITING_MERCHANT → QUALIFYING / READY / IN_PROGRESS / CLOSED
- RESOLVED → CLOSED
- CLOSED 不可直接回到 OPEN

## 2. Work

狀態：
- DRAFT：已建立但尚未排程。
- READY：所有前置條件滿足，可執行。
- RUNNING：至少一個 ExecutionTask 正在執行。
- WAITING_DECISION：需要人類／政策決定。
- WAITING_EXTERNAL：外部已受理，等待處理或 webhook。
- RECONCILIATION_REQUIRED：結果未知或本地與外部狀態不一致，必須先查核。
- BLOCKED：缺少資訊、能力、授權或資源；必須有 reason code。
- SUCCEEDED：完成條件全部滿足且證據齊全。
- FAILED：確定不可恢復失敗；保留補救 Work。
- CANCELLED：尚未產生不可逆副作用，或取消已由上游確認。
- EXPIRED：超過有效期限且無待確認副作用。

轉移原則：
- DRAFT → READY / CANCELLED
- READY → RUNNING / WAITING_DECISION / BLOCKED / CANCELLED / EXPIRED
- RUNNING → WAITING_DECISION / WAITING_EXTERNAL / RECONCILIATION_REQUIRED / BLOCKED / SUCCEEDED / FAILED / CANCELLED
- WAITING_DECISION → READY / BLOCKED / CANCELLED / EXPIRED
- WAITING_EXTERNAL → RUNNING / RECONCILIATION_REQUIRED / SUCCEEDED / FAILED / BLOCKED / CANCELLED
- RECONCILIATION_REQUIRED → RUNNING / WAITING_EXTERNAL / SUCCEEDED / FAILED / BLOCKED
- BLOCKED → READY / WAITING_DECISION / CANCELLED / EXPIRED
- 終態 SUCCEEDED／FAILED／CANCELLED／EXPIRED 不可原地重啟；新需求建立新 Work，並可關聯 `supersedes_work_id`。

SUCCEEDED 條件：
1. 所有 required ExecutionTask 已達可接受終態；
2. 必要外部結果已查核（不是只有 HTTP 200）；
3. 完成證據符合 acceptance_criteria；
4. 無未處理的高風險 reconciliation；
5. 若有付款／預訂，兩者各自的狀態已符合該 Work 的完成定義。
通知送達不是 Work 成功的必要條件；通知失敗建立獨立通知任務。

## 3. ExecutionTask

狀態：
- QUEUED、RUNNING、PENDING、UNKNOWN、RECONCILIATION_REQUIRED、SUCCEEDED、FAILED、CANCELLED、SKIPPED。

重要區分：
- PENDING：上游明確回覆已受理／處理中，具有 provider reference 或等效證據。
- UNKNOWN：呼叫逾時、連線中斷、回應無法解析等，無法判斷上游是否已執行。
- FAILED：有證據證明上游未成功且不再處理，或本地驗證在呼叫前拒絕。
- RECONCILIATION_REQUIRED：查核佇列狀態，不代表上游失敗。

轉移：
- QUEUED → RUNNING / CANCELLED / SKIPPED
- RUNNING → PENDING / UNKNOWN / SUCCEEDED / FAILED / CANCELLED
- PENDING → RUNNING（查詢／輪詢 attempt）/ RECONCILIATION_REQUIRED / SUCCEEDED / FAILED
- UNKNOWN → RECONCILIATION_REQUIRED
- RECONCILIATION_REQUIRED → PENDING / SUCCEEDED / FAILED / UNKNOWN
- FAILED 可在政策允許且確認無外部副作用時建立新 Task；不得覆寫原 Task。
- SUCCEEDED、CANCELLED、SKIPPED 為終態。

## 4. Booking

平台狀態：
- DRAFT：尚未送上游。
- QUOTED：已取得有效報價。
- HOLD_PENDING：建立暫留中。
- HELD：上游明確確認暫留。
- CONFIRM_PENDING：確認預訂中。
- CONFIRMED：上游明確確認預訂，已取得 provider reference／證據。
- REJECTED：上游明確拒絕。
- CANCEL_PENDING：取消處理中。
- CANCELLED：上游確認取消。
- CHANGE_PENDING：改期／變更處理中。
- UNKNOWN：副作用結果未知，先 reconciliation。
- EXPIRED：暫留／報價逾期且查核確認沒有有效預訂。
- MANUAL_REVIEW：需要人工與上游確認。

付款狀態獨立：
- NOT_REQUIRED、NOT_STARTED、REQUIRES_ACTION、PROCESSING、AUTHORIZED、CAPTURED、PARTIALLY_REFUNDED、REFUNDED、FAILED、UNKNOWN。
不得把 Booking CONFIRMED 自動推成 CAPTURED，也不得把付款成功推成 Booking CONFIRMED。

## 5. DecisionRequest 與 Approval

DecisionRequest：
- OPEN、APPROVED、REJECTED、EXPIRED、CANCELLED、SUPERSEDED。

Approval：
- ACTIVE、REVOKED、EXPIRED、CONSUMED。
批准資料不可更新；撤回新增一筆撤回事件／紀錄。
批准必須包含 tenant_id、actor_id、decision_request_id、decision_revision、payload_hash、policy_version、scope、approved_at、expires_at。
執行前比對當前 payload hash、decision revision、policy version、批准 scope、tenant、actor、資源及撤回狀態；任何不符均拒絕。
若執行參數改變（人數、日期、供應商、金額、服務版本、取消條款等），必須重新產生決策版本並重新批准。

## 6. Complaint

- OPEN、INVESTIGATING、WAITING_CUSTOMER、WAITING_MERCHANT、REMEDIATION_IN_PROGRESS、RESOLVED、CLOSED、REOPENED。
- 退款／補償成功只是 remediation 的一部分；需依客訴政策與必要通知完成後才 RESOLVED。
- 標準改期、取消或退款可不建立 Complaint。
- CLOSED 後有新爭議需建立 REOPENED 事件或新 Complaint 並保留原始關聯，不可刪除歷史。

## 7. Service publication（後續 ENG-08）

每個 channel publication 獨立：
- DRAFT、READY、SUBMITTED、UNDER_REVIEW、LIVE_VERIFIED、REJECTED、FAILED、UNKNOWN、WITHDRAW_PENDING、WITHDRAWN。
- SUBMITTED 不是 LIVE；只有渠道讀回正確 service_version 或取得等效可信證據，才能 LIVE_VERIFIED。
- 一個渠道 LIVE_VERIFIED 不代表其他渠道成功。
- 舊 webhook 不得覆蓋較新的 revision；依 provider event time、revision 與 sequence 去重排序。

## 8. 狀態實作規範

- 所有轉移由 domain service 執行；禁止任意 PATCH status。
- 每次轉移新增 audit/event record，含 from、to、reason_code、actor、correlation_id、occurred_at。
- API 回傳 409 STATE_TRANSITION_NOT_ALLOWED，並包含 safe current state，不洩漏其他 tenant 資料。
- Worker crash 後以 DB state + outbox 重建流程；不得靠記憶體 timer。
- 定期 reconciliation 掃描 PENDING 超時、UNKNOWN、外部與本地不一致項目；掃描本身也要有冪等與告警。
