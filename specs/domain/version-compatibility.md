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
| 第一批報告 | `execution_status = 'RUNNING'`（001_init.sql enum） | `ExecutionTask.status = EXECUTING` | 可對照（改名） | 第一批報告的 PostgreSQL `execution_status` enum 用 `RUNNING` 表示「worker 已取得 lease 並對外呼叫中」；本次 schema 沿用 SA SM-01 原文的 `EXECUTING` 名稱，語意相同，純改名 |
| 第一批報告 | `Execution.SUCCEEDED` | `ExecutionTask.status = DONE` | 可對照但需補證據 | 新 schema 要求 `postcondition` 與 `CompletionEvidence` 同時成立；僅有舊的 `SUCCEEDED` 旗標不足以回填 |
| SA | `task.ESCALATED` | `Work.escalations[]`（獨立陣列）+ 保留原 `ExecutionTask` 的實際 WAITING/UNKNOWN 狀態 | 可對照（結構拆分） | 舊版把升級當成一個終態值，新 schema 把它變成附加資訊，不覆蓋原本的等待/未知狀態 |

## ExecutionTask 狀態（SA SM-01 → SD §4）

SA SM-01（`docs/sa/sa-v1.0.md` L216-227）的完整轉移表已包含 `NEW→VALIDATING→READY→EXECUTING→VERIFYING→DONE`、
`EXECUTING→UNKNOWN`、`任務→WAITING`、`WAITING→VALIDATING`、`任務→ESCALATED／PARTIAL`、`未送出任務→CANCELLED`。
下表逐狀態對照；R1 review 指出前一版遺漏 `WAITING` 列、且誤稱 `READY`／`PARTIAL` 為本輪新增，已更正如下。

| SA SM-01 | 本次 `execution-task.schema.json` 狀態 | 相容性 | 理由 |
|---|---|---|---|
| `NEW` | `NEW` | 相容 | — |
| `VALIDATING` | `VALIDATING` | 相容 | — |
| `READY`（SA L219：`VALIDATING → READY`） | `READY` | 相容 | 更正：前一版誤稱此為「本次新拆」；SA 原文本就有 `VALIDATING → READY → EXECUTING` 三段轉移（SA L219-220），本次只是沿用，不是新增分段 |
| `EXECUTING` | `EXECUTING` | 相容 | — |
| `WAITING`（SA L224：`任務 → WAITING`；SA L225：`WAITING → VALIDATING`） | `WAITING` | 相容 | 前一版遺漏此列；SA 原文「等人／素材／第三方處理」寫 `waiting_on`、`due_at`、`next_run_at` 並釋放 lease，對應本次 schema 的 `WAITING`、`next_run_at`、`deadline` 欄位，純列出 |
| `VERIFYING` | `VERIFYING` | 相容 | — |
| `UNKNOWN` | `UNKNOWN` | 相容 | — |
| `DONE` | `DONE` | 相容 | — |
| `FAILED` | `FAILED` | 相容 | — |
| `CANCELLED` | `CANCELLED` | 相容 | — |
| `ESCALATED`（SA 顯式狀態） | 不是獨立狀態；改為 `Work.escalations[]` 附加資訊 | 不相容（刻意不保留） | SD work-execution-contract.md §4：`ESCALATED` 改以獨立 Escalation 表示，保留實際的 WAITING／UNKNOWN 等狀態，避免「升級」掩蓋了原本該追蹤的真實等待原因 |
| `PARTIAL`（SA L226：`任務 → ESCALATED／PARTIAL`；SA L235：「父任務 PARTIAL 不是所有渠道重跑」） | `PARTIAL`（本次限定 `kind=GROUP`） | 相容但限縮範圍 | 更正：前一版誤稱 `PARTIAL` 為「本次新增」；SA 原文已有多子任務部分成功聚合到父任務的語意。本次新增的是限制：只有 `kind=GROUP` 的父任務可為 `PARTIAL`，一般 `ACTION` 任務不可直接進 `PARTIAL`（`execution-task.schema.json` 的 `allOf` 約束），複合業務須先拆出 GROUP 根任務，這是 SD work-execution-contract.md §2「一般 ACTION 不可有 PARTIAL 終態」新加的範圍限縮，不是整個狀態的新增 |

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
| `RemedyAction`：`AUTHORIZED → SUBMITTED → PENDING → SUCCEEDED`；分支 `FAILED／UNKNOWN`（SA L389） | 不在本輪任何 `*.schema.json` 範圍 | 延後（非不相容） | R1 review 指出前一版完全未列出 RemedyAction 的狀態；補列於此以免被誤讀為「遺漏」。`complaint.schema.json` 只固定 `remedy_action_refs` 參照形狀與「不自動改變 Complaint.status」的規則（見 `relationships.md`），RemedyAction 自己的狀態機與退款原子保留是 SD credit-and-refund.md 已固定、ENG-07 scope 實作的範圍，本輪不重寫 |

## 本輪未覆蓋的歷史狀態機（SM-03／05／06／07）

R1 review 指出前一版對照表只處理 SM-01／02／04，未提及 SA 其餘狀態機，可能被誤讀為「這些狀態已被取代或不存在」。
這些狀態機在本輪 `specs/domain/*.schema.json` 中沒有對應實體（VoiceSession/Transfer/VoiceTurn/Playback、Asset、
ServiceVersion proposal、Publication 都不是 backlog ENG-01 列出的 8 個核心實體），逐一列出其 SA 原值與延後理由，
避免靜默省略：

| SA 狀態機 | SA 原值 | 本輪覆蓋 | 延後理由 |
|---|---|---|---|
| SM-03（SA L338，通話與回合） | `VoiceSession`: `CONNECTING → ACTIVE → TRANSFERRING／DISCONNECTED → CLOSED`；`Transfer`: `NONE → REQUESTED → RINGING → CONNECTED／FAILED`；`VoiceTurn`: `PARTIAL → FINAL → CONFIRMED`（可 `SUPERSEDED`）；`Playback`: `QUEUED → PLAYING → PLAYED／INTERRUPTED` | 無 | 語音會話/回合不是 backlog ENG-01 的 Case/Complaint/Work/ExecutionTask/ExecutionAttempt/DecisionRequest/Approval/Order 八個實體之一；`CustomerConsent.evidence_ref` 可引用語音確認紀錄的外部參照，但 VoiceSession 本身的狀態機留待負責語音/會話層的 ENG 任務 |
| SM-05（SA L474，素材） | `RECEIVED／QUARANTINED → CHECKED → CLARIFYING → READY_FOR_REVIEW → APPROVED → AVAILABLE`；可 `REVOKED／EXPIRED／REJECTED` | 無 | Asset 不在本輪 8 個實體內；`ApprovalRecord.scope_manifest` 與 `WorkContext.ref_kind` 都還沒有 `ASSET` 専用欄位細節，素材權利狀態機留待素材模組的 ENG 任務 |
| SM-06（SA L506，服務版本提案） | `DRAFT → DISCUSSING → VALIDATED → AWAITING_APPROVAL → APPROVED → APPLYING → PARTIAL／VERIFIED → MONITORING → CLOSED` | 部分：`WorkContext.ref_kind = SERVICE_VERSION` 只固定「套用」步驟引用的 FK 形狀 | 完整提案狀態機（DISCUSSING/VALIDATED/AWAITING_APPROVAL 等審閱前階段）不是 ExecutionTask/ApprovalRecord 的狀態，是獨立 ServiceVersion 提案物件；本輪未新增該 schema 檔，狀態機留待 catalog/服務版本模組的 ENG 任務 |
| SM-07（SA L528，發布工作） | `DRAFT → APPROVED → QUEUED → SUBMITTED → IN_REVIEW／LIVE_VERIFIED`；例外 `FAILED／MANUAL_REQUIRED／CONFLICT`；暫停完成為 `PAUSED_VERIFIED` | 部分：`WorkContext.ref_kind = PUBLICATION` 只固定「發布是一個 Work 的參照對象」這個事實 | SD connector-result-and-reconciliation.md §8 已把 SA SM-07 調整成 `DRAFT, READY, SUBMITTED, PENDING_REVIEW, VERIFYING, LIVE_VERIFIED, PAUSED_VERIFIED, FAILED, UNKNOWN`（即 `QUEUED→READY`、拆 `IN_REVIEW` 為 `PENDING_REVIEW／VERIFYING`、新增 `UNKNOWN`、移除獨立的 `MANUAL_REQUIRED／CONFLICT` 終態改併入 `FAILED`+人工 escalation）；這是 SD 已決定的調整，但 Publication 本身的完整欄位（desired/submitted/observed version/hash、業務鍵）不是本輪 8 個實體之一，狀態機本身留待渠道發布模組的 ENG 任務；不得把 `ExecutionTask.status` 直接當成 Publication 狀態的同義詞 |

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
