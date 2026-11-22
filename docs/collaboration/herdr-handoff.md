# HerdR 開發交接

更新：2026-11-22。目標是讓 HerdR 知道每個模組的輸入、輸出、狀態、資料責任、失敗處理與驗收方式。

## 開始工作

~~~
git clone https://github.com/ajoe734/travel-ai-platform.git
cd travel-ai-platform
python3 scripts/validate_repository.py
node tests/prototype-regression.cjs
~~~

先不要索取真實供應商、金流或商家帳號。第一階段只需本機開發環境、PostgreSQL 測試資料庫與 mock connector；任何真實外部副作用均不在目前授權範圍。

## 必讀順序

1. [AGENTS.md](../../AGENTS.md)
2. [目前決策](../project/current-decisions.md)
3. [來源與原檔](../provenance/README.md)
4. [SA 完整主文](../sa/sa-v1.0.md) 與 [執行角色 v1.1](../requirements/execution-role-v1.1.md)
5. [SD 索引](../sd/README.md)、[SA／SD 差異](../sd/sa-v1-gaps.md) 與 [ADR](../adr/)
6. [工程契約](../engineering/README.md)：domain model、state machines、OpenAPI、events、SQL、acceptance matrix、implementation plan
7. [開發任務](backlog.md)
8. [原型檢查](../verification/prototype-audit.md)

## 可直接交給 HerdR 的主指令

> 你是 travel-ai-platform 的主要工程代理。先完整讀取必讀文件，尤其 AGENTS.md 與 docs/engineering/ 全目錄。不可自行重新設計一套與 SA／SD 不同的 Case、Complaint、Work、ExecutionTask、Approval、Booking 或狀態機。
>
> 從 ENG-01A 開始，一個 task 一個 branch／PR。第一個 PR 完成技術決策、repository bootstrap、domain runtime schemas、狀態機純函式、OpenAPI／event contract validation。接著完成 PostgreSQL migration、tenant RLS、inbox/outbox，再做授權、mock connectors 與 durable workflow。
>
> 第一條端到端流程必須使用 mock：建立 Case、建立 Work、查詢可售、產生不可變 Quote、取得可信客戶確認、依政策取得商家批准、建立 mock Booking、處理 PENDING／UNKNOWN、reconciliation、保存 Evidence，最後由 completion evaluator 判定 Work 是否成功。
>
> 不得把 HTTP 200、模型文字、通知送達或 mock 未經查核的回應當成預訂成功。UNKNOWN 先查核，不可盲目重送；相同 Idempotency-Key + 不同 payload 必須拒絕。所有租戶關聯由 DB constraint 與 RLS 保護。
>
> 每個 PR 列出 SA FR／W 對照、改動檔案、migration、API/event 變更、實際執行測試、mock/sandbox/production 層級、未完成依賴及下一個任務。不要只交空 interface、route stub、TODO 或文件摘要。

## 第一個里程碑的使用者流程

1. 旅客從已授權入口提出需求；平台建立 Conversation／Message，建立 Case。
2. 系統辨識必要資訊缺口；只在缺少日期、人數、服務類型等必要條件時向旅客追問。
3. 資訊足夠後建立 Work，列出目標與可驗收條件。
4. 系統依服務版本與 connector capability 查詢可售；沒有 capability 或帳號權限時先 BLOCKED。
5. 建立 Quote 快照：服務版本、日期、時區、人數、資源、價格、幣別、取消條款、供應商、有效期限。
6. 旅客確認必須來自可信入口事件／確認 token，且綁定 quote revision + payload hash；模型說「旅客同意」不算。
7. 授權政策判定是否需要商家批准；需要時建立 DecisionRequest，批准綁定 revision/hash/policy version。
8. 執行前重新檢查 tenant、actor、connector account、capability、quote expiry、customer confirmation、approval scope 與 revoke 狀態。
9. 以穩定 operation key 呼叫 mock provider。PENDING 等待；UNKNOWN 進 reconciliation；不得直接重送。
10. 查核外部結果，保存 provider reference 與 Evidence；由 completion evaluator 檢查所有條件後才能 Work=SUCCEEDED。
11. 通知另行執行；通知失敗不得把已確認的預訂改回失敗。

## 任務分工

| 分工 | 先做 | 依賴 |
|---|---|---|
| Domain／API 契約 | ENG-01A～01C | 無 |
| DB／資料安全 | ENG-02A～02B | ENG-01 |
| 授權／批准 | ENG-03A～03B | ENG-01；持久化依 ENG-02 |
| Connector／mock | ENG-04A～04B | ENG-01 |
| Orchestration／Booking | ENG-05A～05B | ENG-02、03、04 |
| 商家工作台 | ENG-06A | ENG-01；整合依 ENG-05 |
| 退款／Credit／客訴 | ENG-07 | ENG-02～05 |
| 服務版本／發布 | ENG-08 | ENG-03～05 |
| 部署與營運 | ENG-09 | ENG-05、06 |
| 語音與多媒體 | ENG-10 | ENG-01、03、05 |
| 洞察／討論／素材權利 | ENG-11 | ENG-02、03、05、08 |
| 計費／歸因／結算／成本 | ENG-12 | ENG-02、05、07、08、10 |

## 每份 PR 的必要內容

- 解決的營運問題與 SA FR／W 對照。
- 變更的 entity、API、event、state transition、UI、migration。
- 成功與拒絕路徑測試；適用時包括 timeout、duplicate、out-of-order、tenant isolation、approval stale/revoke。
- 真正執行的命令與通過／失敗結果。
- 測試層級：unit、contract、integration、workflow、mock E2E、sandbox、production。
- migration 相容性、forward-fix、備份復原與風險。
- 未完成依賴、下一個可領取 task。

## 明確未完成

目前尚無正式 API server、DB migration 執行結果、RLS policy、worker、connector、真實供應商／金流介接或 production deployment。歷史獨立 OpenAPI／SQL／event schema 附件仍未取得；工程契約 v0.1.0 是新增設計。
