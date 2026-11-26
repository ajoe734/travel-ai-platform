# ENG-04：供應商中立連接器與三種 mock

版本：v1，2026-11-26 新增。依 [backlog ENG-04](../../docs/collaboration/backlog.md#eng-04供應商中立連接器與三種-mock)
產出，讀取順序見 [AI_COLLABORATION_GUIDE.md §1](../../AI_COLLABORATION_GUIDE.md)：先讀
[SD connector-result-and-reconciliation.md](../../docs/sd/connector-result-and-reconciliation.md)（本目錄把它的
CapabilityDescriptor／OperationResult／核對演算法轉成可執行的 Python 型別與行為）、再讀 [ENG-01 domain 契約](../domain/README.md)
（connector 的 business_key 與本平台 ExecutionTask／ExecutionAttempt 的 business_key／request_hash 使用同一形狀）。

## 這個目錄回答什麼問題

`docs/sd/connector-result-and-reconciliation.md` 已經用表格固定了能力、三態結果、PENDING／UNKNOWN 區分與核對演算法；
本目錄：

1. 用 `connectors/` 把那份設計做成可執行的 Python 型別（`CapabilityDescriptor`、`OperationResult` 的四個變體
   `Succeeded`／`Pending`／`Unknown`／`Failed`）與一個共用的 `Connector` 基底類別，`ensure_capability()` 在任何外部
   呼叫前依 support／authorization_state／side_effect 拒絕不可用的能力。
2. 用三個固定行為的 mock（`connectors/mocks/`）示範 SD §9 要求的三種供應商形狀：
   - `ExperienceReservationMock`：同步、TIMESLOT 資源、同業務鍵回同參考、資源衝突。
   - `PmsNightlyMock`：ROOM_NIGHT 跨晚查詢，且明確宣告不支援 `publication.update`（不是缺少，是宣告為
     `UNSUPPORTED`）。
   - `OtaDelayedPublicationMock`：非同步審核、PENDING／回覆遺失 UNKNOWN／延遲讀回、接受與拒絕兩種終局。
3. 用 `tests/connector_contract_test.py` 以 `unittest`（非自寫斷言框架）逐項驗證 backlog ENG-04 的六項驗收，對照見
   [acceptance-trace.md](acceptance-trace.md)。

這是契約與 mock 行為驗證，不是資料庫、Worker、真實 connector 或前端的驗收；那些證據屬 ENG-02／03／05／07／08 範圍。

## 語言與執行環境的選擇

本次啟動環境保證 Python 3 標準函式庫可用（見 `requirements-validation.txt`）；主機上即使另外裝有 Node.js
（`scripts/validate_repository.py` 本身就用它檢查 `prototypes/` 的 JavaScript 語法），也沒有資料庫或網路存取；
`docs/ops` 的 VM 限制也禁止在這裡啟動正式伺服器或 Docker。SD 文件第 3 節的 `OperationResult`
TypeScript 介面標註為「尚未是可引用的已安裝 SDK」的示意，本身不綁定語言。因此本輪的 typed SDK 用 Python
`dataclasses`／`enum`／`Literal` 實作，延續 ENG-01（JSON Schema + `tests/domain_contract_test.py`）已確立的
「真正可執行、不假裝已有未安裝的 runtime」原則。欄位名稱維持與 SD 文件一致的 snake_case，所以日後補上 HTTP 層不需要
camelCase 轉換。若後續任務決定正式後端語言（ENG-02／05 範圍），`connectors/base.Connector` 的介面形狀可被該語言重新
實作或透過邊界呼叫沿用；本目錄不預先假設該選擇。

## 目錄結構

| 路徑 | 內容 |
|---|---|
| `connectors/types.py` | `SupportLevel`／`AuthorizationState`／`ConnectorMode`／`SideEffect`／`CapabilityDescriptor`；`OperationResult` 的 `Succeeded`／`Pending`／`Unknown`／`Failed` |
| `connectors/errors.py` | `CapabilityUnavailableError`（呼叫前拒絕）、`BusinessKeyConflictError`（同 key 不同 payload） |
| `connectors/idempotency.py` | `IdempotencyStore`：in-memory、以 (tenant_id, account_id, environment, capability_key, business_key) 去重；`request_hash()` 產生與 ENG-01 `request_hash` 相同形狀（64 hex）的雜湊 |
| `connectors/base.py` | `Connector` 基底：`describe_capability()`（唯讀）、`ensure_capability()`（呼叫前拒絕，WRITE/READ 不可混用） |
| `connectors/mocks/experience_reservation.py` | `ExperienceReservationMock` |
| `connectors/mocks/pms_nightly.py` | `PmsNightlyMock` |
| `connectors/mocks/ota_delayed_publication.py` | `OtaDelayedPublicationMock` |
| `connectors/fixtures.py` | 固定租戶／session／room-night／channel 測試資料與故障模式觸發值 |
| `tests/connector_contract_test.py` | 驗收逐項測試，含 import 範圍檢查（mock 不得匯入 `requests`／`socket`／`os` 等） |

## 如何驗證

```bash
python3 -m unittest tests.connector_contract_test -v
```

只驗證型別與三個 mock 的行為契約；不啟動資料庫、瀏覽器或任何真實 connector。`scripts/validate_repository.py` 的既有
檢查（原檔完整性、文件連結、原型 JS 語法）維持不變，不在此重複。

## 與正式 adapter 的邊界（SD §9 延伸）

- 三個 mock 的 `CapabilityDescriptor.verification` 全部維持 `None`（見 `tests/connector_contract_test.py` 的
  `test_capability_verification_defaults_to_production_disabled`）：沒有任何帳號被預設視為已驗證或已上線。
  正式啟用一律是後續任務逐能力記錄 account／environment／API 版本／scope／實測證據後才產生非 `None` 的
  `CapabilityVerification`。
- 三個 mock 檔案與 `connectors/` 其餘模組都不匯入任何網路或環境變數模組；這是本輪的靜態邊界檢查，不是對正式
  adapter 之後也不會呼叫真實 API 的保證（正式 adapter 一定需要網路與憑證，那是它自己的任務範圍）。
