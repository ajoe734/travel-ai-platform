# ENG-04 驗收對照表

依 [AI_COLLABORATION_GUIDE.md §0.7](../../AI_COLLABORATION_GUIDE.md) 的交付證據表格式，逐項對照
[backlog ENG-04](../../docs/collaboration/backlog.md#eng-04供應商中立連接器與三種-mock) 的六項驗收。

執行環境：本機 Python 3.12.3 + 標準函式庫（無額外套件安裝）。所有測試皆為單元測試，呼叫
`connectors/` 的正式類別本身，不是另寫一套影子邏輯；不啟動資料庫、瀏覽器或任何真實網路連線。

| 驗收項（backlog 原文） | 原始碼依據與修改位置 | 結果 | 命令、退出碼、證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| PMS 未提供發布能力時在呼叫前拒絕 | `connectors/mocks/pms_nightly.py` `_capabilities()` 將 `publication.update` 宣告為 `UNSUPPORTED`／`MISSING`；`submit_publication()` 呼叫 `Connector.ensure_capability()`（`connectors/base.py`）later than 計數器但 early than 任何狀態變更 | `PmsPublicationCapabilityGateTest` 兩個測試皆通過：`CapabilityUnavailableError` 在狀態變更前擲出，`pms._booked` 保持空字典 | `python3 -m unittest tests.connector_contract_test.PmsPublicationCapabilityGateTest -v`，exit 0，見下方完整執行紀錄 | 僅驗證 mock 的呼叫前拒絕；真實 PMS 帳號是否真的沒有該能力屬正式整合任務範圍 |
| PENDING 與 UNKNOWN 可區分 | `connectors/types.py` 的 `Pending`／`Unknown` 是不同 dataclass，欄位不同（`pending_reason` vs `reason_code`）；`connectors/mocks/ota_delayed_publication.py` `submit_publication()` 依 `simulate_response_lost` 回不同型別 | `PendingVersusUnknownTest.test_normal_submission_is_pending_lost_response_is_unknown` 通過：型別、欄位存在性互斥 | 同上整批命令，exit 0 | 只驗證型別形狀與 mock 的觸發條件；未驗證真實供應商回應的對應規則 |
| 查核回 SUCCEEDED 或 FAILED 均有收尾 | `connectors/mocks/ota_delayed_publication.py` `reconcile()`：終局結果一律 `evidence_refs` 非空，且呼叫 `IdempotencyStore.update_result()` 把儲存結果改成終局值 | `ReconciliationClosureTest` 兩個測試皆通過：SUCCEEDED 有 evidence 且儲存已更新；FAILED 有 evidence、`side_effect_disposition=NOT_APPLIED` 且儲存已更新 | 同上，exit 0 | 「收尾」只驗證本 mock 的 in-memory ledger；ENG-02 持久層的 outbox/inbox 收尾屬其任務範圍 |
| 同 key 不重複建立外部資源 | `connectors/idempotency.py` `IdempotencyStore.record_dispatch()` 對同 key 第二次呼叫擲 `BusinessKeyConflictError`，三個 mock 一律先 `get()`／`reuse()` 才決定是否建立新資源 | `DuplicateDispatchIsRejectedTest` 五個測試皆通過：三種 mock 的重試回同一 `external_reference`／同一 backend 筆數；payload 改變時擲 `BusinessKeyConflictError`；容量不足的 FAILED 重試不重跑容量檢查 | 同上，exit 0 | 僅驗證單進程 in-memory ledger 的互斥；多 worker 併發下的 UNIQUE 約束是 ENG-02 持久層範圍 |
| 外部成功後本地逾時仍可查回同一結果 | `connectors/mocks/ota_delayed_publication.py` `submit_publication(simulate_response_lost=True)`：backend record 在回傳 `Unknown` 之前已建立；`reconcile()` 之後讀回同一 `external_reference` | `ResponseLostThenReconcileSameResourceTest.test_lost_response_reconciles_to_the_resource_already_created` 通過：`reconciled.external_reference == created_reference`，`len(ota._backend) == 1` | 同上，exit 0 | 只模擬「caller 端逾時、provider 端已成功」這一種時序；多次重送造成的競態非本輪範圍 |
| 沒有任何真實服務 API 權限的預設 | `connectors/` 全部模組不匯入網路／環境變數模組；三個 mock 的 `CapabilityDescriptor.verification` 全部維持 `None`（預設值） | `NoRealServiceCredentialsByDefaultTest` 三個測試皆通過：AST 掃描未發現 `requests`／`httpx`／`socket`／`os` 等匯入；三個 mock 全部能力的 `verification` 皆為 `None`；READ 能力不能被當 WRITE 呼叫 | 同上，exit 0 | 靜態掃描只證明本輪程式碼沒有匯入這些模組，不是沙箱層級的網路阻斷證明 |

## 完整執行紀錄

```text
$ python3 -m unittest tests.connector_contract_test tests.domain_contract_test -v
...
Ran 28 tests in 0.150s

OK
$ python3 scripts/validate_repository.py
Repository checks: passed
Original files verified: 12
Local documentation links checked: 186
JavaScript scripts checked: 3
```

`tests.domain_contract_test`（ENG-01，13 個測試）一併跑過，確認本次新增未造成 ENG-01 契約回歸。

## 跨任務邊界

- `ExecutionAttempt`／`ExecutionTask` 的 `request_hash` 與 `business_key` 形狀（`specs/domain/common/identifiers.schema.json`
  的 `BusinessOperationKey`）與本目錄的 `connectors/idempotency.request_hash()`／fixture business key 一致，由
  `tests/connector_contract_test.py` 的 `BusinessKeyFixtureShapeTest` 核對；持久層的實際 UNIQUE 約束仍是 ENG-02 範圍。
- 本目錄的 `Connector.ensure_capability()` 是 ENG-05 第一條接單耐久流程在呼叫 mock 前應該使用的入口；ENG-05 尚未開始，
  本輪不預先建立它的 Worker／Activity 整合。
