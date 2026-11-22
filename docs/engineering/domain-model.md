# 領域模型與關聯契約 v0.1.0

## 1. 核心實體

| Entity | 意義 | 不代表 |
|---|---|---|
| Tenant | 一個簽約商家／營運組織的資料隔離邊界 | 不等於單一分店 |
| Branch | Tenant 旗下實際營運據點 | 不等於渠道帳號 |
| Actor | 商家人員、旅客、平台服務或合作渠道的行為身分 | 不等於模型推理出的名字 |
| Conversation | 一段通訊上下文；可來自 LINE、Web、電話或內部工作台 | 不等於交易案件 |
| Case | SA 定義的接單／營運案件，承接一個客戶需求 | 不等於客訴 |
| Complaint | 對既有服務／訂單提出的客訴或爭議 | 不等於一般改期、取消或退款 |
| Work | 系統承接並負責推進的一項可驗收工作 | 不等於某次工具呼叫 |
| ExecutionTask | Work 中可獨立排程／重試的執行操作 | 不等於外部供應商訂單 |
| ExecutionAttempt | Task 的一次具體執行嘗試；每次重試新增一筆 | 不得覆寫舊 attempt |
| DecisionRequest | 執行前需人類或政策作決定的具體請求 | 不等於模型自行產生的「已同意」 |
| Approval | 對固定決策版本與 payload hash 的批准紀錄 | 不等於永久授權 |
| Quote | 具期限、價格與供應條件快照的正式報價 | 不等於模型估價 |
| Booking | 平台與供應方間的一筆預訂協調紀錄 | 不必然等於付款成功 |
| ExternalReference | 上游系統回傳的訂單／工作參照 | 不可只用顯示文字當唯一鍵 |
| Evidence | 支持狀態或完成條件的可追溯證據 | 不等於聊天文字聲稱成功 |
| ConnectorAccount | 某 tenant／branch 對某外部系統的連接設定 | 不等於該系統授權了每一項能力 |
| ConnectorCapability | 外部系統實際支援的能力及版本 | 不可由產品名稱推定 |

## 2. 關聯規則

- Tenant 1:N Branch、ActorMembership、Conversation、Case、Complaint、Work、ConnectorAccount。
- Conversation 1:N Message；Conversation 可關聯 0..N Case，但每個 Case 必須有 tenant。
- Case 1:N Work；一個 Work 可由多個 ExecutionTask 推進。
- Work 0..1 Case（非案件型的內部工作允許 null）；若有 Case，兩者 tenant 必須一致。
- Work 1:N ExecutionTask；ExecutionTask 1:N ExecutionAttempt。
- ExecutionTask 0..N DecisionRequest；DecisionRequest 1:N Approval history（拒絕／撤回／重新批准皆保留歷史）。
- Case 0..N Quote；Quote 0..1 Booking；Booking 0..N ExternalReference、Evidence。
- Complaint 可關聯 Case 與 Booking，但一般取消、改期或退款不強制建立 Complaint。
- Evidence 可指向 Case、Work、Task、Attempt、Quote、Booking、Complaint；必須同 tenant。
- 每個跨表 tenant 關聯使用複合外鍵或等效 DB 約束，禁止只在應用層檢查。

## 3. ID 與欄位慣例

- 主鍵使用 UUIDv7（若 runtime 不支援，可 UUIDv4，但不可混用自訂遞增 ID 作外部 ID）。
- 所有主資料有 `id`, `tenant_id`, `created_at`, `updated_at`；不可變稽核紀錄只有 `created_at`，不得提供一般 update API。
- 外部 ID 另存 `provider`, `provider_account_id`, `external_id`；不可直接把外部 ID 當本平台 PK。
- 金額欄位：`amount_minor BIGINT`、`currency CHAR(3)`；0 合法與否依欄位定義；禁止負數報價。
- 版本欄位：`revision INT` 從 1 遞增；批准綁定 revision 與 SHA-256 canonical payload hash。
- 所有可被重送的 command 帶 `Idempotency-Key`；資料庫 unique scope 至少為 tenant + operation + key。
- PII 依欄位分類加密／遮罩；log 不記錄完整電話、Email、證件、付款資料或對話原文。

## 4. Work 結構

Work 至少包含：
- `work_type`: BOOKING、CHANGE、CANCELLATION、REFUND、COMPLAINT_RESOLUTION、SERVICE_PUBLICATION、FOLLOW_UP、INTERNAL。
- `title`、`goal`、`acceptance_criteria[]`：可驗收的業務目標。
- `status`：見 state-machines.md。
- `priority`、`due_at`、`owner_actor_id`（可空）、`source_case_id`（可空）。
- `input_snapshot`：建立工作時的必要輸入快照；敏感欄位需引用安全儲存，不可原文塞 JSON。
- `completion_evidence_ids[]`：完成證據參照。
- `blocked_reason`：只在 BLOCKED／WAITING_DECISION 等狀態填入可讀原因。

Work 必須能回答：「要完成什麼、目前卡在哪裡、下一個自動動作是什麼、需要誰做什麼、完成依據是什麼」。

## 5. ExecutionTask 與 Attempt

ExecutionTask 描述「要做的副作用／查詢」，例如查詢可售、建立 hold、建立 booking、查詢 booking、發出通知。欄位：
- `task_type`、`target_system`、`operation_key`、`request_hash`、`status`、`next_run_at`、`deadline_at`。
- `approval_id`：若該操作政策要求批准，必須指向有效批准；否則 null 並記錄 policy decision。
- `connector_account_id` 與 `capability_snapshot`。
- `result_summary`：可讀摘要，不放原始敏感 payload。

ExecutionAttempt 每次呼叫新增一列：
- `attempt_no`、`started_at`、`finished_at`、`request_hash`、`transport_status`、`provider_status`、`provider_reference`、`error_code`、`safe_error_message`、`response_evidence_id`。
- Attempt 不可被重用；網路逾時後新 attempt 前，先查詢同一 operation key 的上游結果。

## 6. Quote、Booking 與資源模型

Quote 必須固定服務版本、旅客人數／組成、服務地日期時間、時區、價格明細、稅費口徑、供應商、取消規則、有效期限及可售查核時間。報價後任何會改變履約或金額的參數變動，建立新 Quote revision 或新 Quote，不得修改已被批准的快照。

住宿使用 room-night／room-type；活動使用 session／capacity unit；交通使用 departure／seat／vehicle；餐飲使用 table／slot／party size。核心 Booking 不把所有資源壓成單一 capacity 欄位，應以 typed `resource_claims` 或 domain-specific adapter 管理，並保留原始供應商確認證據。

## 7. Actor、角色與授權

角色至少分離：
- TENANT_OWNER、TENANT_ADMIN、BRANCH_MANAGER、OPERATOR、FINANCE、SUPPORT、TRAVELER、CHANNEL_CLIENT、SYSTEM。
- 角色只代表可能的操作範圍；仍須檢查 tenant、branch、resource、channel entitlement、政策與有效批准。
- SUPPORT 的跨租戶 break-glass 必須有獨立、限時、記錄原因的授權；不得讓一般工程師預設讀取所有租戶資料。

## 8. 刪除與保留

交易、批准、執行嘗試、外部結果、退款、Credit ledger、稽核紀錄採 append-only／軟刪除策略。一般 API 不提供物理刪除。旅客個資、知識庫文件、音訊素材依資料分類、契約及適用法規設定保留期限；刪除／撤回授權不應破壞法定或履約必要的交易證據。
