# 旅行平台專案：開發代理共同規則

本 repository 是旅行平台／商家接單與營運助理的工程協作來源。使用繁體中文撰寫說明，程式識別字沿用契約中的英文名稱。

## 必讀順序

1. AGENTS.md
2. docs/project/current-decisions.md
3. docs/provenance/README.md
4. docs/sa/sa-v1.0.md 與 docs/requirements/execution-role-v1.1.md
5. docs/sd/README.md 與 docs/adr/
6. docs/engineering/README.md 及其領域、狀態機、API、事件、DB、測試契約
7. docs/collaboration/herdr-handoff.md、docs/collaboration/backlog.md

原始文件、歷史研究主張、本次新增 SD 與工程契約有不同版本身分。不要把研究報告中曾經聲稱存在的工程檔案，視為已匯入或已執行。遇到衝突，先查明來源、在 ADR 記錄取捨，再同步更新契約與驗收。不得將失落附件換成同名新檔後宣稱找回原版。工程契約 v0.1.0 是新增實作基線，仍需評審、實作及測試。

## 產品與領域邊界

- 商家交代營運目標，系統承接並追蹤工作。日常流程自行完成；缺少必要資訊、需要新的商業決定或既有授權不適用時，才提出具體問題。
- 保留商家既有預約、PMS、POS、CRM、電話、金流與銷售渠道。對方擁有的正式交易資料，以指定的主系統為準。
- Conversation、SA 的 Case、新增的 Work、ExecutionTask／ExecutionAttempt、Order／Booking 分開。SA 的 Case 是接單／營運案件；Complaint 是客訴，不能互換。
- 住宿房晚、活動場次、交通座位、餐飲預約保留各自容量模型；核心不可寫死單一供應商的欄位。
- 平台既可提供自己的助理介面，也能讓合作渠道自己的模型呼叫受控能力。

## 執行不變條件

- 模型產生的計畫或工具參數不構成授權。執行層獨立驗證 tenant、actor、resource、參數、政策版本與有效批准。
- 區分技術能力、帳號授權、商家同意、營運可用性。
- 批准須綁定決策版本與完整執行內容 hash；內容改變須重新判定。批准與撤回須能追溯。
- 有外部副作用的操作使用穩定 business operation key。相同 key + 相同 payload 才可安全重試；相同 key + 不同 payload 必須拒絕。
- PENDING 表示上游明確受理、尚未完成；UNKNOWN 表示無法判定上游是否執行。UNKNOWN 先 reconciliation，不可盲目重送。
- API 接受請求、外部執行完成、結果查核完成、通知送達各自記錄。完成工作必須滿足 acceptance criteria 並有證據。
- 所有跨實體關聯由 API、repository、DB constraints／RLS 共同維持 tenant 一致，不能只靠前端或 RAG 過濾。
- 退款依原訂單與原付款途徑；Credit 是獨立 ledger。補償完成不自動等於客訴結案。
- 外部 I/O 與耐久流程控制分開；保存 inbox/outbox、關聯 ID、事件版本、重試／查核狀態與證據。
- 金額使用 amount_minor 整數 + ISO currency；日期時間使用 UTC timestamptz 並保留服務地 IANA timezone。
- 正式價格、名額、付款與退款結果不能由模型或文件檢索自行推定。

## 實作規範

- 所有 status transition 經 domain service；禁止任意 PATCH status。
- 所有 side-effect command 有 Idempotency-Key 與 canonical request hash；所有 event consumer 可重入。
- 外部副作用前檢查 tenant、actor、connector account、capability、政策、批准與有效期限。
- log 不記錄完整 PII、付款資料、access token、原始語音或對話附件。
- originals/ 與歷史 UX 版本不得改寫；新增修訂另建版本。
- 預設只使用 mock；不自行連接真實供應商寫入、付款、退款、發布或建立真實第三方訂單。沙盒與 production 均需明確授權。
- 不放入密鑰、真實客戶名冊或生產資料；不自行部署公開服務或更改 repository 可見性。

## 協作與交付

- 一項 backlog task 一個 branch／PR；共用契約變更先合併，再由下游任務 rebase。
- 新功能須交付實作、契約、migration（若適用）、正常與失敗測試、操作文件及實際測試輸出；不得只交 route stub 或空 interface。
- PR 必須列出 SA FR／W 對照、資料模型/API/event/UI 變更、執行過的命令與結果、mock/sandbox/production 層級、風險及未完成依賴。
- 一般檢查：python3 scripts/validate_repository.py；原型檢查：node tests/prototype-regression.cjs。後端測試依 docs/engineering/testing/acceptance-matrix.md。

## 目前接手狀態

2026-11-22 已匯入 12 個原始文件與原型，並新增 SD、HerdR backlog、工程契約 v0.1.0。SQL 是 migration 草案，尚未在 PostgreSQL 執行；OpenAPI／event catalog 尚未有實際服務實作；RLS、worker、connector、交易與 production 均未完成。歷史獨立 OpenAPI／SQL／事件附件仍未取得，狀態以 docs/provenance/README.md 與 specs/README.md 為準。
