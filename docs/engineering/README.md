# 工程實作契約 v0.1.0

本目錄是 HerdR 實作時的機器可讀與人工可讀契約。它補足 SA v1.0、執行角色 v1.1 與 SD 文件之間的落地細節；不是宣稱原始遺失的 OpenAPI／SQL／事件附件已找回。

## 契約狀態

- 版本：0.1.0（2026-11-22）
- 性質：新增工程基線，待工程實作與評審。
- 第一個垂直切片：商家接單案件 → Work → 報價快照 → 必要批准 → mock 預訂 → 外部結果查核 → 完成證據。
- 資料庫：PostgreSQL 17 語法基線；正式採用前須實際執行 migration、RLS、forward-fix 與整合測試。
- API：OpenAPI 3.1，定義第一垂直切片與共用控制面，不等於 SA 全部 58 API 已實作。
- 事件：CloudEvents 1.0 風格封套；目錄列出第一垂直切片必要事件，不等於原始 28 事件附件。
- Connector：預設僅 mock；不允許建立真實供應商訂單、付款、退款或發布。

## 必讀順序

1. [領域模型](domain-model.md)
2. [狀態機](state-machines.md)
3. [API 契約](api/openapi.yaml)
4. [Availability 與 Booking 流程](api/availability-and-booking-workflow.md)
5. [可信入口與客戶確認](api/trusted-ingress-and-confirmation.md)
6. [事件目錄](events/event-catalog.yaml)
7. [DB 初始 migration 草案](db/0001_core.sql)、[補充 migration](db/0002_connector_and_confirmation.sql)、[單次確認約束](db/0003_confirmation_single_use.sql)
8. [驗收案例](testing/acceptance-matrix.md)
9. [實作分解](implementation-plan.md)

## 不可違反的工程原則

1. tenant 隔離由 API、repository 與 DB 約束共同執行。
2. 模型只提出建議與參數；授權服務獨立驗證 actor、tenant、資源、決策版本、payload hash、政策與批准。
3. 外部副作用使用固定 operation key；相同 key + 相同 payload 可安全重試，相同 key + 不同 payload 必須拒絕。
4. PENDING（上游已受理、仍在處理）與 UNKNOWN（本地不知道上游結果）是不同狀態。
5. UNKNOWN 先 reconciliation，不可盲目重送。
6. 訂單、付款、預訂、通知、客訴結案是不同生命週期。
7. 每個狀態變更須有 actor、時間、來源、correlation_id 及可追溯紀錄。
8. 金額以最小貨幣單位整數儲存，並強制帶 ISO 4217 currency。
9. 日期時間以 UTC timestamptz 儲存；服務地時區另存 IANA timezone。
10. 不允許把 mock 成功、HTTP 200、模型回答或通知送達當成交易完成證據。

## 版本與相容性

- API 路徑採 /v1；改變語意、移除欄位或改變狀態轉移需升 major。
- event type 帶版本，例如 travel.booking.requested.v1；schema 版本與 API 版本分開。
- DB migration 只能向前；正式資料庫不允許自動 destructive rollback。
- 所有規格變更須更新 OpenAPI、event catalog、DB migration、測試矩陣與 ADR。

## 本版尚未涵蓋

完整付款服務商適配、真實 PMS／OTA、SIP／WebRTC、語音轉錄、素材權利工作流、完整 Credit ledger、企業計費與渠道佣金。這些仍依 backlog ENG-07～12 排序，不得假設本版已完成。
