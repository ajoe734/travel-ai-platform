# 既有狀態／名稱對照與不相容理由

backlog ENG-01 驗收要求「為所有既有狀態提供對照或明確不相容理由」。本檔彙整
[SA v1.0](../../docs/sa/sa-v1.0.md)、[2026-11-20 重建報告](../../docs/research/2026-11-20-rebuilt-sasd.md)、
[2026-11-21 第一批工程報告](../../docs/research/2026-11-21-engineering-batch1.md)與
[SD sa-v1-gaps.md §3](../../docs/sd/sa-v1-gaps.md)、[work-execution-contract.md §5](../../docs/sd/work-execution-contract.md)已有的對照，
逐欄位固定成本目錄 schema 使用的值，並補上尚未明列的不相容理由。這不是資料遷移執行紀錄；沒有資料庫實例可供遷移，
舊值對照只在未來真的匯入舊資料時使用（見 `docs/provenance/README.md`）。

## Work／Task（業務責任）

| 舊來源 | 舊值 | 本次 schema 值 | 相容性 | 理由 |
|---|---|---|---|---|
| 重建報告 | `Task`（整個概念） | `Work` | 可對照（改名） | 同一語意，`work.schema.json` 保留 principal/objective/completion_conditions/authority/plan/escalation/evidence 七項契約 |
| 第一批報告 | `Work.IN_PROGRESS` | `Work.status = RUNNING` | 可對照（改名） | — |
| 第一批報告 | `Work.UNKNOWN` | `Work.status = WAITING_EXTERNAL` + `waiting_external.waiting_reason = RESULT_UNKNOWN` | 可對照但需補欄位 | 舊值把「不確定」當成頂層狀態；新 schema 要求同時標註是哪個 task 的何種原因，不能只留一個字串 |
| 重建報告 | `Task.ACCEPTED`／`Task.PLANNING` | 併入 `Work` 的受理事件與 `plan` 陣列（無獨立 Task 表） | 不相容（結構不同） | 本次不另建第二套 Task 表；舊狀態對應的是 Work 受理時的一次事件，不是可查詢的持久狀態欄位 |
| 第一批報告 | `Execution.PENDING` | 視原意分流：尚未送出 → `ExecutionTask.status = READY`；已送出且供應商受理 → `WAITING` | 不可自動批次轉換 | 舊資料若無法判別兩者，依 SD §5 標記 `migration_review_required` 並保留原值，禁止自動重送 |
| 第一批報告 | `Execution.SUCCEEDED` | `ExecutionTask.status = DONE` | 可對照但需補證據 | 新 schema 要求 `postcondition` 與 `CompletionEvidence` 同時成立；僅有舊的 `SUCCEEDED` 旗標不足以回填 |
| SA | `task.ESCALATED` | `Work.escalations[]`（獨立陣列）+ 保留原 `ExecutionTask` 的實際 WAITING/UNKNOWN 狀態 | 可對照（結構拆分） | 舊版把升級當成一個終態值，新 schema 把它變成附加資訊，不覆蓋原本的等待/未知狀態 |

## ExecutionTask 狀態（SA SM-01 → SD §4）

| SA SM-01 | 本次 `execution-task.schema.json` 狀態 | 相容性 | 理由 |
|---|---|---|---|
| `NEW` | `NEW` | 相容 | — |
| `VALIDATING` | `VALIDATING` | 相容 | — |
| `READY`（本次新拆） | `READY` | 新增細分 | SA 原文把驗證後到取得 lease 前視為同一階段；SD 拆出 `READY` 以便在 commit 之後、呼叫外部之前有一個可查詢的中繼狀態 |
| `EXECUTING` | `EXECUTING` | 相容 | — |
| `VERIFYING` | `VERIFYING` | 相容 | — |
| `UNKNOWN` | `UNKNOWN` | 相容 | — |
| `DONE` | `DONE` | 相容 | — |
| `FAILED` | `FAILED` | 相容 | — |
| `CANCELLED` | `CANCELLED` | 相容 | — |
| `ESCALATED`（SA 顯式狀態） | 不是獨立狀態；改為 `Work.escalations[]` 附加資訊 | 不相容（刻意不保留） | SD work-execution-contract.md §4：`ESCALATED` 改以獨立 Escalation 表示，保留實際的 WAITING／UNKNOWN 等狀態，避免「升級」掩蓋了原本該追蹤的真實等待原因 |
| 無 | `PARTIAL`（本次新增，限 `kind=GROUP`） | 新增 | SA 原文沒有聚合多子操作的語意；SD 新增以支援多渠道/多子項部分成功 |

## DecisionRequest／Approval（SA BR-05~10 → SD §1~§6）

| 舊來源 | 舊值／概念 | 本次 schema | 相容性 | 理由 |
|---|---|---|---|---|
| SA | `Authorization`（單一物件，含 actor/kind/target/revision/hash/scope/evidence/expiry/consumed_task） | 拆為 `CustomerConsent` + `ExecutionAuthorization` + `AuthorizationUse` | 不相容（結構拆分，刻意） | SA 原文把「客戶同意」與「執行閘門」與「消耗紀錄」合在一個物件；SD authorization-and-approval.md §1 指出這三者是不同依據、不同生命週期，混一起會讓撤回與重試邏輯無法單獨驗證 |
| SA | `Authorization.consumed_task` | `AuthorizationUse.root_task_id` | 可對照但語意更嚴格 | 舊欄位只是一個參照；新物件是獨立的 append-only 紀錄，且同一 `authorization_id` 只能有一筆，見 `tests/domain_contract_test.py::test_authorization_use_is_not_duplicated_across_roots` |
| 第一批報告 | `ApprovalRecord.revoked_at`（可寫欄位，與「禁止 UPDATE」trigger 並存） | `revoked_at` 不存在於 `approval-record.schema.json`；改以 `ApprovalRevocation` 追加紀錄，讀取時由 read model 投影 | 不相容（刻意移除） | ADR 0003：`revoked_at` 若出現在 API 是 projection，不能回寫 immutable 原表；舊設計的欄位與其自身的禁止 UPDATE trigger互相矛盾，本次不沿用 |
| 無 | `DecisionRequest`（獨立物件，含 revision/hash/expires_at） | 新增 | 新增 | SA 原文沒有獨立的「待決事項」物件，只在 BR-05/09 描述同意與版本比較的規則；SD 補上使其可被追蹤與重放 |

## Order／Booking／Payment／Refund（SA SM-02，本輪未更動語意）

| 狀態域 | 本次 `order.schema.json` | 相容性 | 理由 |
|---|---|---|---|
| `order`：`PENDING → CONFIRMED → COMPLETED`；或 `CHANGE_PENDING／CANCELLED／EXCEPTION` | 原樣沿用 | 完全相容 | SA SM-02 本就要求三個狀態域分開，不合成一個欄位；本次只是把它寫成 schema |
| `booking`：`NOT_REQUESTED → ON_HOLD／PENDING → CONFIRMED`；取消 `CANCEL_REQUESTED → CANCELLED`；可 `EXPIRED`／`UNKNOWN` | 原樣沿用（併入 `Order.supplier_booking.status`） | 完全相容 | — |
| `payment`：`NOT_REQUESTED → PENDING → AUTHORIZED → CAPTURED`；或直接 `CAPTURED`；`VOIDED` | 原樣沿用（併入 `Order.payment.status`） | 完全相容 | — |
| `refund`：`RESERVED → SUBMITTED → PENDING → SUCCEEDED`；`UNKNOWN`／`FAILED` | 不在本輪 `order.schema.json` 範圍 | 延後（非不相容） | Refund 的完整欄位（reservation、原子保留、policy budget）是 ENG-07 scope；本輪只保留 `Complaint.remedy_action_refs` 的參照形狀，不重寫 SD credit-and-refund.md 已固定的狀態機 |

## Complaint（SA SM-04，本輪未更動）

| SA SM-04 | 本次 `complaint.schema.json` | 相容性 | 理由 |
|---|---|---|---|
| `OPEN → CHECKING → WAITING_CUSTOMER／WAITING_MERCHANT／WAITING_CHANNEL → RESOLVING → RESOLVED → CLOSED`；可 `ESCALATED`／`REOPENED` | 原樣沿用（enum 完全一致） | 完全相容 | 本次沒有新研究報告聲稱要改這組狀態；唯一新增的是 `resolution` 欄位的存在性規則（見下） |
| （隱含規則，原文字描述）「退款或改期成功不強迫客訴同步關案」 | `allOf`/`if-then-else`：只有 `status ∈ {RESOLVED, CLOSED}` 才允許/要求 `resolution`，其餘狀態禁止出現 `resolution` | 新增可驗證形式 | SA 原文只用文字描述這條規則，容易被實作忽略；本次把它變成 schema 可以直接拒絕的條件（見 `tests/domain_contract_test.py` 的 `complaint-invalid-*` 兩個負向範例） |

## Capability／OperationResult（ADR 0002，本輪未更動）

| 舊來源 | 舊值 | 本次狀態 | 相容性 | 理由 |
|---|---|---|---|---|
| SA 07.2 | `SUPPORTED`／`PENDING`／`UNKNOWN`／`UNSUPPORTED` 混在同一個 status | 拆為「能力」（`SUPPORTED/UNSUPPORTED/UNVERIFIED`，見 SD connector-result-and-reconciliation.md §2）與「結果」（`SUCCEEDED/PENDING/UNKNOWN/FAILED`，見 `execution-attempt.schema.json` 的 `outcome`） | 不相容（刻意拆分） | ADR 0002：前者混合能力與結果會導致「這次呼叫失敗」與「這個帳號本來就不支援」無法區分；本輪 Attempt/Observation 的 `outcome` 只允許四個結果值，能力資訊固定在 connector 契約（ENG-04 scope），不在本目錄重複定義 |
| 第一批報告 | `SUCCEEDED／UNKNOWN／FAILED`（缺已知 pending） | 加入 `PENDING` | 不相容（新增必要分支） | 舊三態把「供應商已受理但未完成」也壓進 `UNKNOWN`，造成已知等待與真正不確定結果無法分開處理（ADR 0002） |

## 一律標記為「待實際資料核對」的情況

若日後真的匯入舊系統資料，以下情況不得自動批次轉換，必須先標 `migration_review_required` 並保留原始值：

- 舊 `Execution.PENDING` 無法區分「尚未送出」與「已送出待外部處理」。
- 舊 `Authorization` record 無法區分它當時綁定的是 `CustomerConsent` 還是商家政策本身。
- 舊 `ApprovalRecord` 若曾經被直接 UPDATE 過 `revoked_at`，其歷史真實性需先用稽核軌跡核對，不能直接信任該欄位。

這些規則延續 [SD sa-v1-gaps.md §2](../../docs/sd/sa-v1-gaps.md) 的立場：歷史工程附件的取得狀態與本次新設計分開記錄，
不把「本次補寫」說成「原檔已復原」。
