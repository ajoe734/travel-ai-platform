# ENG-06：商家工作台接真實工作狀態

版本：v1，2026-11-27 新增。依 [backlog ENG-06](../../docs/collaboration/backlog.md#eng-06商家工作台接真實工作狀態) 產出，
讀取順序見 [AI_COLLABORATION_GUIDE.md §1](../../AI_COLLABORATION_GUIDE.md)：先讀
`docs/sd/work-execution-contract.md`、`docs/sd/authorization-and-approval.md`、
[ENG-01 domain 契約](../domain/README.md)、[UX 2.1 原型核對](../../docs/verification/prototype-audit.md)，
再讀本目錄。

## 這個目錄回答什麼問題

[UX 2.1 原型](../../prototypes/merchant-assistant/ux-v2.1/index.html) 已驗證商家互動的語氣與流程（討論 → 補素材 → 審閱 →
核准 → 查看渠道結果），但其「後端」是瀏覽器 `localStorage` 加 `setTimeout` 模擬（詳見
[prototype-audit.md §6](../../docs/verification/prototype-audit.md)）。本目錄把同一組互動接上
[ENG-01 的 Work／DecisionRequest／ExecutionTask 契約](../domain/README.md) 與
[ENG-04 的 connector mock](../connector/README.md)，產出：

1. `service-revision.schema.json`：商家「新增／調整服務」提案的結構化欄位契約（名稱、內容、價格、時長、容量、
   時段、現場接待、渠道、素材與用途確認），一旦完整即成為一個 `DecisionRequest.display_payload`
   （`specs/domain/decision-request.schema.json`）。
2. `../../services/workbench/`：`WorkbenchService`，實作商家工作清單、補資料、決策卡、執行進度、完成證據，
   詳見 [api-contract.md](api-contract.md)。
3. `../../prototypes/merchant-assistant/workbench/index.html`：取代 UX 2.1 的
   `localStorage`／`setTimeout` 假後端，改為呼叫 `api-contract.md` 定義的端點；沒有伺服器可啟動時，
   以 `tests/workbench_frontend_test.cjs` 的 `fetch` mock 驗證同一組前端邏輯。

## 範圍界線

- **持久化**：`services/workbench/repository.py` 是記憶體內實作，明確標記為 ENG-02 持久層落地前的替代品，
  與 `services/authorization`（`claude/eng-03`）揭露同一個邊界。
- **授權引擎**：`ApprovalRecord`／`ExecutionAuthorization`／`AuthorizationUse`
  （[authorization-and-approval.md](../../docs/sd/authorization-and-approval.md) §1/§5）是 ENG-03 範圍；
  本服務直接操作一個 Work 自己的 `DecisionRequest`，不偽造 ApprovalRecord 頂替那條管線。
- **耐久執行**：`WorkbenchService.advance_execution()` 是一次 worker tick 的直接呼叫，代表 ENG-05
  落地前「有一個 worker 會做這件事」的介面；沒有真正的 outbox／lease／fence 併發控制（ENG-02/05 範圍），
  且把 `ExecutionTask` 的 `NEW→VALIDATING→READY→EXECUTING` 四態收斂成一次呼叫，詳見
  `services/workbench/service.py` 模組註解。
- **內容 hash**：`services/workbench/canonical_json.py` 依
  [authorization-and-approval.md §3.2](../../docs/sd/authorization-and-approval.md) 的大方向實作，但**不是**
  SD-A-09 要求的跨語言、測試向量驗證過的正式 canonical encoder；它的 hash 前綴刻意與 ApprovalRecord
  的 `travel-approval-v1\n` 不同，避免未來 ENG-03 的雜湊被誤認成同一份。
- **整合驗收**：依 backlog 原文「整合驗收待 ENG-05」，本目錄只在 `services/workbench` 與
  `prototypes/merchant-assistant/workbench` 這兩層驗證；沒有啟動資料庫、瀏覽器或真實 HTTP 伺服器
  （VM 限制，見 `AI_COLLABORATION_GUIDE.md`）。

## 目錄結構

| 路徑 | 內容 |
|---|---|
| `service-revision.schema.json` | 商家服務改版提案的機器可讀契約；`$ref` 共用 `specs/domain/common/money.schema.json` |
| `api-contract.md` | `WorkbenchService` 方法對應的假定 REST 端點、請求/回應形狀與錯誤碼 |
| `acceptance-trace.md` | backlog ENG-06 驗收項目、對應程式/測試與結果的交付對照表 |

## 如何驗證

```bash
python3 -m unittest tests.workbench_service_test -v
node tests/workbench_frontend_test.cjs
```

第一個指令驗證 `services/workbench/*` 對 ENG-01 契約的正確性（jsonschema 4.10.3，已安裝）；第二個指令以
Node `vm` 執行 `prototypes/merchant-assistant/workbench/index.html` 的內嵌腳本，驗證前端不再需要
`localStorage`／`setTimeout` 即可正確呈現待決、核對中與完成狀態。兩者皆不啟動資料庫、瀏覽器或外部
connector；`scripts/validate_repository.py` 的既有檢查（原檔完整性、文件連結、原型 JS 語法）維持不變。
