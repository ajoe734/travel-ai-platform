# ENG-01：固定跨版本領域與契約

版本：v1，2026-11-26 新增。依 [backlog ENG-01](../../docs/collaboration/backlog.md#eng-01固定跨版本領域與契約) 產出，讀取順序見
[AI_COLLABORATION_GUIDE.md §1](../../AI_COLLABORATION_GUIDE.md)：先讀 `docs/sa/sa-v1.0.md`、`docs/sd/*`、`docs/adr/*`，本目錄是把那些文件裡的表格與 Given/When/Then
轉成可執行驗證的機器可讀 schema，不是另立一套新規則。本目錄不還原 `docs/provenance/README.md` 列出未取得的
`openapi.yaml`／`01_schema.sql`／`資料字典.md` 等原附件；凡此處與原附件同名的概念，都是本輪新增版本，不冒稱已找回原檔。

## 這個目錄回答什麼問題

`docs/sd/*.md` 已經用表格與 Given/When/Then 固定了 Case／Complaint／Work／ExecutionTask／ExecutionAttempt／
DecisionRequest／Approval／Order 的關聯與狀態機；本目錄把它們寫成可被 `jsonschema` 實際驗證的 JSON Schema
（Draft 2020-12），並用 `tests/domain_contract_test.py` 以 `jsonschema` 套件（非自寫解析器）驗證：

1. 每個 schema 檔本身是合法的 JSON Schema。
2. 每個實體至少一組「應該通過」與一組「應該被拒絕」的範例（`examples/`），對應 backlog ENG-01 的驗收情境。
3. 單一 instance 驗證無法表達的跨實例不變量（同 Case 多個 Work、同 Work 多個 ExecutionTask、重試只加 Attempt、
   同一 AuthorizationUse 不可綁兩個 root task、跨租戶 parent 參照形狀）在測試腳本以 Python 斷言核對，標記為
   ENG-02 持久層（UNIQUE／FK／RLS）要落實的不變量，本輪只確保契約形狀足以支撐它們。

這是契約與範例驗證，不是資料庫、Worker 或外部 connector 的驗收；那些證據屬 ENG-02～05、07、08 的任務範圍。

## 目錄結構

| 路徑 | 內容 |
|---|---|
| `common/identifiers.schema.json` | `(tenant_id, id)`、revision、owner_revision、fence_token、business_key、idempotency key、ActorRef |
| `common/money.schema.json` | 金額最小單位字串、幣別、版本化精度參照（不固定兩位小數）、NamedRatio |
| `common/error-envelope.schema.json` | `application/problem+json` 錯誤信封；`code` 為開放字串，實際登記在 `error-codes.json` |
| `error-codes.json` | 本輪固定的錯誤碼登記表，附 SA/SD 來源；新碼只在此追加，不必改 error-envelope schema |
| `case.schema.json` | Case：只保留容器生命週期（OPEN/ARCHIVED）與回覆所有權；詳細流程狀態在 Work（見 ADR 0001） |
| `complaint.schema.json` | Complaint：SA SM-04 狀態不變；`resolution` 只能在 RESOLVED/CLOSED 出現，且只能由顯式 resolveComplaint 填入 |
| `work.schema.json` | Work：SD work-execution-contract.md §3 業務狀態機，含 WorkPlan／WorkContext／CompletionEvidence／Escalation |
| `execution-task.schema.json` | ExecutionTask：SD §4 執行狀態機、ACTION/GROUP、lease/fence |
| `execution-attempt.schema.json` | ExecutionAttempt：append-only 嘗試與核對紀錄 |
| `decision-request.schema.json` | DecisionRequest：SD authorization-and-approval.md §4 |
| `approval-record.schema.json` | Approval 家族：ApprovalRecord（root）+ CustomerConsent／ApprovalRevocation／ExecutionAuthorization／AuthorizationUse（`$defs`） |
| `order.schema.json` | Order：SA SM-02 客戶投影，不合併 booking／payment／refund 三個來源狀態 |
| `examples/` | 每個 schema 的正向／負向範例，供 `tests/domain_contract_test.py` 使用 |
| `relationships.md` | 關聯圖與 cardinality（取代純文字描述，逐項對照 SD ERD） |
| `version-compatibility.md` | 既有狀態／名稱對照表，含不相容理由；backlog 要求的「為所有既有狀態提供對照或明確不相容理由」 |
| `acceptance-trace.md` | backlog ENG-01 驗收項目、SA 追溯編號、對應檔案與測試結果的交付對照表（§0.7 要求的交付證據表） |

## 版本與來源揭露規則

- 每個 schema 檔的 `x_origin` 固定 `status: "new_sd_contract"`、`version: "v1"`、`introduced: "ENG-01"`，並列
  `sa_trace`／`sd_trace`。新增欄位或改變既有欄位意義一律視為新 `version`，不就地覆寫語意（呼應 SD §3.2 canonical
  payload 的 major/minor 規則）。
- `$id` 使用 `https://contracts.travel-ai-platform.invalid/...` 占位網域，延續 SA 08.3 `example.invalid` 的慣例：
  這不是可連線的服務，只是穩定的 schema 識別字。
- 若未來找回原始 `openapi.yaml`／`01_schema.sql`，依 `docs/provenance/README.md` 的規則先核對來源與 checksum，
  再決定與本目錄的相容方式；不得直接覆蓋本目錄視為「還原」。

## 如何驗證

```bash
python3 -m unittest tests.domain_contract_test -v
```

需要 `jsonschema` 套件（本機已安裝 4.10.3）。這個指令只驗證契約與範例，不啟動資料庫、瀏覽器或外部 connector；
`scripts/validate_repository.py` 的既有檢查（原檔完整性、文件連結、原型 JS 語法）維持不變，不在此重複。
