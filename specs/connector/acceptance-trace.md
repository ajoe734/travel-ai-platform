# ENG-04 驗收對照表

依 [AI_COLLABORATION_GUIDE.md §0.7](../../AI_COLLABORATION_GUIDE.md) 的交付證據表格式，逐項對照
[backlog ENG-04](../../docs/collaboration/backlog.md#eng-04供應商中立連接器與三種-mock) 的六項驗收。

執行環境：本機 Python 3.12.3 + 標準函式庫（無額外套件安裝）。所有測試皆為單元測試，呼叫
`connectors/` 的正式類別本身，不是另寫一套影子邏輯；不啟動資料庫、瀏覽器或任何真實網路連線。

## 六項驗收對照

| 驗收項（backlog 原文） | 原始碼依據與修改位置 | 結果 | 命令、退出碼、證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| PMS 未提供發布能力時在呼叫前拒絕 | `connectors/mocks/pms_nightly.py` `_capabilities()` 將 `publication.update` 宣告為 `UNSUPPORTED`／`MISSING`／`merchant_consent=MISSING`／`operational_availability=UNAVAILABLE`；`submit_publication()` 的 `ensure_capability()` 呼叫現在是方法內第一個會執行到底的陳述，`publication_call_count` 只在 `except CapabilityUnavailableError` 裡遞增（R1 F3b 修正） | `PmsPublicationCapabilityGateTest` 兩個測試皆通過：`CapabilityUnavailableError` 在狀態變更前擲出，`pms._booked` 保持空字典 | `python3 -m unittest tests.connector_contract_test.PmsPublicationCapabilityGateTest -v`，exit 0，見下方完整執行紀錄 | 僅驗證 mock 的呼叫前拒絕；真實 PMS 帳號是否真的沒有該能力屬正式整合任務範圍 |
| PENDING 與 UNKNOWN 可區分 | `connectors/types.py` 的 `Pending`／`Unknown` 是不同 dataclass，欄位不同（`pending_reason` vs `reason_code`）；`connectors/mocks/ota_delayed_publication.py` `submit_publication()` 依 `simulate_response_lost` 回不同型別 | `PendingVersusUnknownTest.test_normal_submission_is_pending_lost_response_is_unknown` 通過：型別、欄位存在性互斥 | 同上整批命令，exit 0 | 只驗證型別形狀與 mock 的觸發條件；未驗證真實供應商回應的對應規則 |
| 查核回 SUCCEEDED 或 FAILED 均有收尾 | `connectors/mocks/ota_delayed_publication.py` `reconcile()`：終局結果一律 `evidence_refs` 非空，且呼叫 `IdempotencyStore.update_result()` 把儲存結果改成終局值；`reconcile()` 現在要求呼叫端帶入與 tenant/business_key 綁定的 `reconciliation_token`，且查無紀錄時回 `Unknown(reason_code="NOT_FOUND_RETRY")` 而不是擲 `KeyError`（R1 F2b 修正，對應 SD-C-03） | `ReconciliationClosureTest` 四個測試皆通過：SUCCEEDED／FAILED 有 evidence 且儲存已更新；token 不符擲 `ValueError`；查無紀錄回 `Unknown` 而非崩潰 | 同上，exit 0 | 「收尾」只驗證本 mock 的 in-memory ledger；ENG-02 持久層的 outbox/inbox 收尾屬其任務範圍 |
| 同 key 不重複建立外部資源 | `connectors/idempotency.py` `IdempotencyStore.record_dispatch()` 對同 key 第二次呼叫擲 `BusinessKeyConflictError`，三個 mock 一律先 `get()`／`reuse()` 才決定是否建立新資源 | `DuplicateDispatchIsRejectedTest` 五個測試皆通過：三種 mock 的重試回同一 `external_reference`／同一 backend 筆數；payload 改變時擲 `BusinessKeyConflictError`；容量不足的 FAILED 重試不重跑容量檢查 | 同上，exit 0 | 僅驗證單進程 in-memory ledger 的互斥；多 worker 併發下的 UNIQUE 約束是 ENG-02 持久層範圍 |
| 外部成功後本地逾時仍可查回同一結果 | `connectors/mocks/ota_delayed_publication.py` `submit_publication(simulate_response_lost=True)`：backend record 在回傳 `Unknown` 之前已建立；`reconcile()` 之後讀回同一 `external_reference` | `ResponseLostThenReconcileSameResourceTest.test_lost_response_reconciles_to_the_resource_already_created` 通過：`reconciled.external_reference == created_reference`，`len(ota._backend) == 1` | 同上，exit 0 | 只模擬「caller 端逾時、provider 端已成功」這一種時序；多次重送造成的競態非本輪範圍 |
| 沒有任何真實服務 API 權限的預設 | `connectors/` 全部模組不匯入網路／環境變數模組；三個 mock 的 `CapabilityDescriptor.verification` 全部維持 `None` | `NoRealServiceCredentialsByDefaultTest` 三個測試皆通過：AST 掃描未發現 `requests`／`httpx`／`socket`／`os` 等匯入；三個 mock 全部能力的 `verification` 皆為 `None`；READ 能力不能被當 WRITE 呼叫 | 同上，exit 0 | 靜態掃描只證明本輪程式碼沒有匯入這些模組，不是沙箱層級的網路阻斷證明 |

## R1 退修逐項驗證表（候選 `17a11b2613e9e87c3c7913b8f9dfb578c5cc490b` → 本候選）

Reviewer: Antigravity；審查記錄見 `ai-status.json` 的 `ENG-04.worker_outcomes` 中
`antigravity-20261126T145442Z-448aa179`（`candidate_generation: 2945bb09d2f94362b5eb394d721504a7`）。

| Finding | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| F1 跨租戶資料覆蓋與隔離失效 | `connectors/mocks/ota_delayed_publication.py`：`_backend` 改為以 `(tenant_id, business_key)` 為鍵（原僅 `business_key`）；`advance_review()`／`reconcile()` 加上 `tenant_id` 綁定；`external_reference`／`reconciliation_token` 全部改為 `f"...-{tenant_id}:{business_key}"`；`experience_reservation.py`／`pms_nightly.py` 的 `external_reference` 同步補 tenant 前綴 | 舊版：`TENANT_ID` 送出 `publication.update:repro-01`（channel=`ota-channel-a`/version=`3`）後，`OTHER_TENANT_ID` 送出同 business_key（channel=`ota-channel-b`/version=`9`）會覆蓋 `_backend["repro-01"]`；`reconcile(TENANT_ID, "repro-01")` 讀回 OTHER_TENANT_ID 的 channel/version。新版：同一組輸入下 `len(ota._backend) == 2`，`ota._backend[(TENANT_ID, bk)].channel == "ota-channel-a"`／`service_version == "3"` 不受 `OTHER_TENANT_ID` 影響；`reconcile(TENANT_ID, bk, a.reconciliation_token, ...)` 回 `Pending`（自己的 SUBMITTED 狀態），不是對方的資料 | `python3 -m unittest tests.connector_contract_test.CrossTenantIsolationTest -v`，exit 0（4 tests ok）；手動重現腳本輸出見下方「F1 重現紀錄」 | 僅驗證單一 mock instance 內的記憶體隔離；ENG-02 持久層的 `(tenant_id, connector_account_id, environment, capability_key, business_key)` UNIQUE 約束仍是其任務範圍 |
| F2(a) 缺帳號／商家同意／營運可用性狀態 | `connectors/types.py`：新增 `MerchantConsentState`（GRANTED/MISSING/WITHDRAWN）、`OperationalAvailability`（AVAILABLE/UNAVAILABLE/DEGRADED）；`CapabilityDescriptor` 新增 `merchant_consent`／`operational_availability` 必填欄位；`is_callable()` 四個維度全部納入檢核；三個 mock 的 `_capabilities()` 與 `connectors/base.py` 的預設 descriptor 全部補上這兩個欄位 | 舊版：`CapabilityDescriptor` 只有 `support`／`authorization_state` 兩維，`EXPIRED`/`REVOKED`/`UNVERIFIED` 以外沒有商家同意或營運可用性可表達，也無對應拒絕測試。新版：`CapabilityGateDimensionsTest` 針對 `UNVERIFIED`／`EXPIRED`／`REVOKED`／`MISSING` 同意／`WITHDRAWN` 同意／`UNAVAILABLE`／`DEGRADED` 七種情境逐一證明 `is_callable()` 為 `False` 且 `ensure_capability()` 擲 `CapabilityUnavailableError` | `python3 -m unittest tests.connector_contract_test.CapabilityGateDimensionsTest -v`，exit 0（9 tests ok） | 本輪只在 SDK 型別層加入這兩維；ENG-02 持久層如何把商家同意／營運可用性寫入與查詢，以及正式 UI 上的同意流程，不在本任務範圍 |
| F2(b) reconciliation_token 未使用／驗證；reconcile() 查無紀錄直接拋錯 | `connectors/mocks/ota_delayed_publication.py`：新增 `_reconciliation_token(tenant_id, business_key)`；`reconcile()` 現在要求傳入 `reconciliation_token` 參數，與持久 context 算出的期望值不符時擲 `ValueError`；查無 `_backend` 紀錄時回 `Unknown(reason_code="NOT_FOUND_RETRY", ...)`，不再擲 `KeyError`（SD-C-03） | 舊版：`reconcile()` 忽略 token，查無 `_backend[business_key]` 直接 `raise KeyError(business_key)`，呼叫端會收到未處理例外而非可退避的 `UNKNOWN`。新版：`reconcile(TENANT_ID, "從未送出的 business_key", 對應 token, now)` 回 `Unknown`，`result.reason_code == "NOT_FOUND_RETRY"`，`len(ota._backend) == 0`（沒有被誤建或釋放）；帶錯 token 則擲 `ValueError` 而非讀到別人的資料 | `python3 -m unittest tests.connector_contract_test.ReconciliationClosureTest.test_reconcile_lookup_miss_returns_unknown_not_a_crash tests.connector_contract_test.ReconciliationClosureTest.test_reconcile_with_mismatched_token_is_rejected -v`，exit 0 | 本 mock 的 backend 寫入是同步的，無法在單進程記憶體模型內模擬「真正跨 process 的可見延遲」；SD-C-03 的 lease／退避排程器屬 ENG-02／05 範圍 |
| F3(a) Mock 邊界漏洞：負數／零名額、check_in>=check_out 仍回 Succeeded | `connectors/mocks/experience_reservation.py` `create_booking()` 新增 `party_size <= 0` 時擲 `ValueError`；`connectors/mocks/pms_nightly.py` `create_booking()` 新增 `check_out <= check_in` 時擲 `ValueError` | 舊版：`exp.create_booking(..., party_size=-5, ...)` 回 `Succeeded` 且 `exp._booked[session] == -5`；不存在 session 配 `party_size=0` 也回 `Succeeded`；`pms.create_booking(..., check_in=date(2026,12,24), check_out=date(2026,12,24), ...)`（同日即滿房日）因 `_nights()` 回空列表而回 `Succeeded`。新版：以上三個輸入全部擲 `ValueError`，不建立任何 dispatch 記錄 | `python3 -m unittest tests.connector_contract_test.MockInputValidationTest -v`，exit 0（4 tests ok） | 僅驗證這兩個 mock 的本地請求形狀檢查；正式供應商對無效請求的實際回應（HTTP 400 等）屬各自 adapter 任務範圍 |
| F3(b) 宣告能力缺方法；publication_call_count 遞增順序 | `connectors/mocks/experience_reservation.py` 新增 `query_availability()`；`connectors/mocks/pms_nightly.py` 新增 `lookup_booking()`；`pms_nightly.py` `submit_publication()` 改為 `try: ensure_capability() except CapabilityUnavailableError: publication_call_count += 1; raise`，計數器只在能力閘門已經決定要拒絕之後才遞增 | 舊版：`ExperienceReservationMock` 宣告 `availability.read=SUPPORTED` 但沒有對應方法；`PmsNightlyMock` 宣告 `booking.lookup=SUPPORTED` 但沒有對應方法；`publication_call_count += 1` 在 `ensure_capability()` 之前執行。新版：兩個方法都存在且有測試覆蓋；計數器遞增搬進 `except` 區塊，`ensure_capability()` 是方法內第一個會執行完的陳述 | `python3 -m unittest tests.connector_contract_test.DeclaredReadCapabilitiesHaveMethodsTest tests.connector_contract_test.PmsPublicationCapabilityGateTest -v`，exit 0（8 tests ok） | 僅驗證這兩個新方法回傳固定 fixture 資料；不是對應正式供應商 API 形狀的一致性保證 |
| F3(c) 缺測：PMS query_availability／ROOM_NIGHT_SOLD_OUT／lookup_booking；OTA 多渠道部分結果 | 測試新增：`tests/connector_contract_test.py` 的 `DeclaredReadCapabilitiesHaveMethodsTest`（PMS `query_availability()`／`ROOM_NIGHT_SOLD_OUT`／`lookup_booking()` 含未知 key）與 `MultiChannelPartialPublicationResultsTest`（SD-C-08：A 成功／B 審核中／C 拒絕，重試 C 不影響 A/B） | 舊版：這些路徑在 `connectors/mocks/pms_nightly.py`／`ota_delayed_publication.py` 中已存在（或本輪新增），但測試檔案完全沒有對應案例，行為未被驗證即交審。新版：六個新測試逐一覆蓋，並斷言重試 C 之後 `ota._backend[(TENANT_ID, key_a)].status`／`key_b` 的狀態不變 | `python3 -m unittest tests.connector_contract_test -v`，exit 0（見下方完整執行紀錄） | 只驗證單一 connector instance 內三個獨立 business_key 的狀態機；跨渠道的 `desired_version`／`observed_version` 比對（SD §8 VERSION_CONFLICT）屬 ENG-08 範圍 |
| F4 文件細節：舊連結數 186、`specs/connector/README.md` 錯字與失準描述 | `specs/connector/acceptance-trace.md`（本檔案）連結數改為 196；`specs/connector/README.md` 修正「沒有安裡 Node.js」為「保證 Python 3 標準函式庫可用；主機上即使另外裝有 Node.js…」 | 舊版：`acceptance-trace.md` 記錄 186 links，`validate_repository.py` 實測已是 196；`README.md` 聲稱環境「沒有」Node.js，但本機 `node --version` 回 `v24.22.3`，且 `validate_repository.py` 本身就用 Node 檢查 `prototypes/` 的 JS 語法。新版：兩處皆改為與實測一致的敘述 | `python3 scripts/validate_repository.py`，exit 0，`Local documentation links checked: 196`；`node --version` 回 `v24.22.3`（見下方紀錄） | 純文件修正；不涉及程式行為，沿用既有文件類靜態檢查 |

### F1 重現紀錄

```text
$ python3 -c "
import connectors.fixtures as fixtures
from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock
ota = OtaDelayedPublicationMock()
a = ota.submit_publication(fixtures.TENANT_ID, 'publication.update:repro-01', 'ota-channel-a', '3', fixtures.FIXED_NOW)
b = ota.submit_publication(fixtures.OTHER_TENANT_ID, 'publication.update:repro-01', 'ota-channel-b', '9', fixtures.FIXED_NOW)
print('backend rows:', len(ota._backend))
rec = ota._backend[(fixtures.TENANT_ID, 'publication.update:repro-01')]
print('tenant record channel/version:', rec.channel, rec.service_version)
reconciled = ota.reconcile(fixtures.TENANT_ID, 'publication.update:repro-01', a.reconciliation_token, fixtures.FIXED_NOW)
print('reconcile(TENANT_ID) result type:', type(reconciled).__name__)
"
backend rows: 2
tenant record channel/version: ota-channel-a 3
reconcile(TENANT_ID) result type: Pending
```

On the pre-fix candidate (`17a11b2613e9e87c3c7913b8f9dfb578c5cc490b`), the same script prints
`backend rows: 1` and `tenant record channel/version: ota-channel-b 9` -- `OTHER_TENANT_ID`'s
submission overwrote `TENANT_ID`'s, matching the reviewer's reopen report.

## 完整執行紀錄

```text
$ python3 -m unittest tests.connector_contract_test tests.domain_contract_test -v
...
Ran 54 tests in 0.154s

OK
$ python3 scripts/validate_repository.py
Repository checks: passed
Original files verified: 12
Local documentation links checked: 196
JavaScript scripts checked: 3
```

`tests.domain_contract_test`（ENG-01，13 個測試）一併跑過，確認本次修正未造成 ENG-01 契約回歸。
`tests.connector_contract_test` 從 R1 reopen 前的 15 個測試增加到 41 個（新增 `CrossTenantIsolationTest`
4、`CapabilityGateDimensionsTest` 9、`MockInputValidationTest` 4、`DeclaredReadCapabilitiesHaveMethodsTest` 6、
`MultiChannelPartialPublicationResultsTest` 1、`ReconciliationClosureTest` 新增 2），對應上表逐項 finding。

## 跨任務邊界

- `ExecutionAttempt`／`ExecutionTask` 的 `request_hash` 與 `business_key` 形狀（`specs/domain/common/identifiers.schema.json`
  的 `BusinessOperationKey`）與本目錄的 `connectors/idempotency.request_hash()`／fixture business key 一致，由
  `tests/connector_contract_test.py` 的 `BusinessKeyFixtureShapeTest` 核對；持久層的實際 UNIQUE 約束仍是 ENG-02 範圍。
- 本目錄的 `Connector.ensure_capability()` 是 ENG-05 第一條接單耐久流程在呼叫 mock 前應該使用的入口；ENG-05 尚未開始，
  本輪不預先建立它的 Worker／Activity 整合。
- `MerchantConsentState`／`OperationalAvailability` 目前只在本 SDK 的記憶體型別層存在；ENG-02 持久層如何儲存、
  誰能寫入這兩個狀態（商家本人同意流程、營運公告來源）不在本任務範圍，留給後續設計。
