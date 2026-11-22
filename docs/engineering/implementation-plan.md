# HerdR 實作計畫與任務拆分 v0.1.0

## 0. 執行命令與工作規則

1. clone main，執行 `python3 scripts/validate_repository.py` 與 `node tests/prototype-regression.cjs`。
2. 讀取本目錄全部契約、SA、ADR、backlog；若發現衝突先開 ADR，不可自行選擇性忽略。
3. 一個 ENG 任務一個 branch／PR；共用契約先合併，再讓下游任務 rebase。
4. 所有開發預設 mock provider；禁止連接真實金流／供應商寫入。
5. 不可把「介面建立」「mock 回傳成功」當作整體功能完成。

## 1. 建議技術基線（可由 ADR 替換）

- API：TypeScript + Fastify 或 NestJS（二選一，ENG-01 開始前提出 ADR，不可兩種混用）。
- Runtime：Node.js LTS；套件以 lockfile 固定。
- Database：PostgreSQL 17；所有 schema 變更用 migration。
- Queue／durable execution：先以 Postgres outbox + worker lease 實作最小耐久流程；如採 Temporal 等 workflow engine，先提出 ADR，定義 workflow idempotency、activity retry 與資料保存。
- Validation：JSON Schema／Zod 其一作 runtime validation；OpenAPI 從單一 source 產生或以 contract test 防止漂移。
- Tests：Vitest/Jest、Testcontainers（若環境允許）、Playwright 用於真正 browser E2E。
- Observability：structured logs、OpenTelemetry trace、metrics；敏感資料遮罩。
- Frontend：沿用 UX 2.1 資訊架構，使用 TypeScript；不得以 localStorage 作交易狀態來源。

## 2. 任務與產出

### ENG-01A — 技術決策與 repository bootstrap
**產出**：ADR 選定 runtime/framework、資料存取、migration、worker、測試框架；package manifest、lockfile、lint/typecheck/test scripts、CI。
**完成條件**：乾淨 clone 可安裝、lint/typecheck/test；CI 可重跑；無 secrets。

### ENG-01B — Domain contracts
**產出**：Case、Complaint、Work、ExecutionTask、ExecutionAttempt、DecisionRequest、Approval、Quote、Booking、Evidence 的 TypeScript types + runtime schemas；狀態機純函式；error code registry。
**完成條件**：每個 schema 有 valid/invalid fixtures；狀態機測試涵蓋合法與非法轉移；SA FR traceability map。

### ENG-01C — API / event contract
**產出**：OpenAPI lint、生成／驗證 API types；event envelope 與 event schema；consumer idempotency contract。
**完成條件**：OpenAPI lint 0 error；event fixture 可驗證；contract tests 阻止 schema 漂移。

### ENG-02A — DB migration 與 repository
**產出**：將 db/0001_core.sql review 後轉成正式 migration；migration runner、repositories、transaction boundary。
**完成條件**：空 DB up；測試 DB down/up 或 forward-fix 流程；migration checksum；資料約束測試。

### ENG-02B — Tenant RLS / audit / inbox-outbox
**產出**：每張 tenant-owned table RLS；非 owner／非 BYPASSRLS app role；transaction-local tenant context；outbox publisher、inbox dedupe、audit append-only。
**完成條件**：tenant A/B cross-read/write 測試全部拒絕；publisher crash/retry 不丟事件；重複事件只處理一次。

### ENG-03A — Authorization / policy engine
**產出**：actor membership、role/resource scope、connector capability、policy version、decision evaluator。
**完成條件**：模型輸出不能直接呼叫副作用；無效 actor、tenant、scope、policy 全拒絕；decision 有可解釋 reason code。

### ENG-03B — Approval lifecycle
**產出**：decision request revision/hash、approve/reject/expire/revoke append-only records；執行前重新驗證。
**完成條件**：payload 變動、批准過期／撤回、雙人核准規則與競態測試通過。

### ENG-04A — Connector SDK
**產出**：Connector interface：capabilities、health、availability、quote、createBooking、getBooking、cancelBooking；typed result union；provider raw response digest。
**完成條件**：capability 不足在呼叫前拒絕；PENDING/UNKNOWN/FAILED 不混淆；所有副作用都收 operation key。

### ENG-04B — Mock providers
**產出**：activity session mock、hotel PMS room-night mock、channel publication mock；可設定成功、拒絕、PENDING、timeout、亂序 webhook。
**完成條件**：固定 seed；可重現測試；mock 不含真實憑證／網路呼叫。

### ENG-05A — Durable orchestrator
**產出**：worker lease、task scheduler、attempt records、retry policy、deadline、reconciliation queue。
**完成條件**：worker kill/restart、重複 enqueue、timeout UNKNOWN、provider PENDING、webhook reorder 全通過。

### ENG-05B — Booking vertical slice
**產出**：Case → Work → availability → Quote → customer confirmation → Approval if required → Booking → reconciliation → Evidence → Work completion。
**完成條件**：acceptance matrix V01-V08 與 S01-S36 適用案例通過；UI 只能顯示後端狀態。

### ENG-06A — Merchant workbench
**產出**：工作清單、工作詳情、阻塞原因、決策卡、執行紀錄、證據檢視；SSE/WebSocket 或 polling 依 ADR。
**完成條件**：刷新可恢復；不會把 pending 顯示成功；操作權限依 server side enforcement。

### ENG-07 — Refund / Credit / Complaint
先完成原付款路徑退款協調與獨立 Credit ledger；退款／Credit 都用 immutable ledger entry 與 idempotency。Complaint lifecycle 不得與 Booking lifecycle 混為一談。真實支付僅在取得明確授權與沙盒設定後做 sandbox tests。

### ENG-08 — Service version / channel publication
ServiceVersion immutable；publication per channel；publish/read-back/verify/reconcile；部分成功各自呈現。不得把 PMS 有商品資料等同有 publish capability。

### ENG-09 — Deploy / operate
Docker compose local profile、環境設定範例、health/readiness、structured logs、trace、metrics、backup/restore、incident runbooks、SLO load tests。正式部署需另行批准。

### ENG-10 — Voice / telephony / multimedia
先做非同步音訊上傳、transcription job、human handoff；即時 WebRTC 與 SIP 另開 ADR。語音辨識結果需日期／金額／人數覆誦確認；不可把 audio upload 說成即時電話接通。

### ENG-11 — Insights / merchant discussion / asset rights
建立可重現查詢與指標分母；證據、假說、建議分開；討論可轉成 change proposal；素材保存權利、來源、用途、有效期限、撤回及安全掃描。客訴素材不可自動用於行銷。

### ENG-12 — Billing / attribution / settlement / cost
usage ledger、plan version、origin attribution、commission rule、refund reversal、variable cost ledger、未成交成本；GMV、平台收入、供應商應付與渠道佣金分開。

## 3. 依賴圖

```text
ENG-01A -> ENG-01B -> ENG-01C -> ENG-02A -> ENG-02B
                         |          |          |
                         +-> ENG-03A -> ENG-03B |
                         +-> ENG-04A -> ENG-04B |
                                      |         |
                         ENG-02B + ENG-03B + ENG-04B
                                      |
                                  ENG-05A
                                      |
                                  ENG-05B
                                  /     \
                             ENG-06A   ENG-07
                                  \     /
                                   ENG-09
ENG-05B + ENG-03B + ENG-04A -> ENG-08
ENG-02B + ENG-05B -> ENG-10 / ENG-11 / ENG-12 (各自補充依賴)
```

## 4. 每日 HerdR 回報格式

- Current task / branch / commit：
- Read documents：
- Changed files：
- Implemented behaviour：
- Tests executed（完整命令與通過／失敗數）：
- Security / tenant / idempotency review：
- Mock / sandbox / production boundary：
- Open blockers：
- Next task：
- PR URL：

## 5. 不可接受的完成回報

- 「API 已完成」但只有 route stub。
- 「預訂成功」但只看到 HTTP 200 或 mock 未經驗證的固定回應。
- 「RLS 已完成」但只在 service 層加 tenant_id where。
- 「重試安全」但每次 retry 都產生新的 operation key。
- 「測試通過」但沒有列出命令、環境與結果。
- 「已串接 OTA／金流」但只完成 interface 或 sandbox。
- 「AI 自動化完成」但所有狀態都需要人工逐步點按。
