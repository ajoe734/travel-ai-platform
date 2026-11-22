# 旅行平台專案 · Travel AI Platform

商家接單與營運助理：承接經營者交代的工作，使用商家既有客服、電話、預約、PMS、POS、CRM、金流與銷售渠道完成接單、售後、服務改善及發布。

**目前階段：原始規格、SA／SD 對齊、UX 2.1 與第一版工程實作契約已交付。** 本 repository 尚未包含正式後端、已連通的第三方交易系統或生產部署。新增工程契約 v0.1.0 是實作基線，不是已執行 migration 或已上線 API。

## HerdR 從這裡開始

1. [AGENTS.md](AGENTS.md)：所有代理不可違反的規則。
2. [工程實作契約索引](docs/engineering/README.md)：領域模型、狀態機、OpenAPI、事件、SQL、驗收矩陣與實作計畫。
3. [HerdR 開發交接](docs/collaboration/herdr-handoff.md)：直接任務指令、啟動方式與回報格式。
4. [開發任務清單](docs/collaboration/backlog.md)：ENG-01～12 的範圍、依賴與驗收。
5. [目前有效基線](docs/project/current-decisions.md)：產品方向、版本關係與範圍。

## 原始規格與設計交付

| 內容 | 位置 | 狀態 |
|---|---|---|
| 產品規劃 v1.0、執行角色 v1.1 | [需求文件](docs/requirements/README.md) | 原始 Word／PDF與全文已匯入 |
| 開發 SA v1.0 | [SA 文件](docs/sa/README.md) | 原始 Word／PDF與完整主文已匯入 |
| UX 1.0／2.0 原稿 | [UX](docs/ux/README.md) | 原檔保留 |
| UX 2.1 修訂 | [原型程式](prototypes/merchant-assistant/ux-v2.1/index.html) | 本機模擬 |
| Work／執行／授權／查核 | [SD](docs/sd/README.md)、[ADR](docs/adr/) | 新增設計，待實作 |
| 工程契約 v0.1.0 | [工程索引](docs/engineering/README.md) | 本次新增；待工程評審與實作 |
| 原檔校驗 | [來源對照](docs/provenance/README.md) | 12 個原始檔案已校驗 |
| 原歷史 OpenAPI／SQL／事件附件 | [取得狀態](specs/README.md) | 尚未取得原件 |

SA 主文列出 32 項需求、58 項 API、28 種事件及 64 項驗收；獨立歷史 YAML／SQL／JSON 附件與 ZIP 尚未取得。此次新增的 OpenAPI、事件目錄與 SQL 草案是新版本工程契約，不是原始附件。

## 本地檢查

~~~
python3 scripts/validate_repository.py
node tests/prototype-regression.cjs
~~~

後端建立後，另依工程契約加入 typecheck、OpenAPI lint、migration、RLS、contract、workflow 及 browser E2E。原型 Node VM 測試不是正式瀏覽器或後端整合測試。

## 第一個工程里程碑

完成 ENG-01～05 後，應能以 mock 完成「建立接單案件 → 建立 Work → 查詢可售 → 形成報價快照 → 取得必要客戶確認／商家批准 → 建立 mock 預訂 → reconciliation → 保存證據 → Work 完成」。必須通過跨租戶拒絕、舊批准失效、重複請求、PENDING／UNKNOWN 分流、Worker 重啟與重複 webhook 測試。

原 SA 首輪的語音、售後、洞察／討論、素材權利、兩渠道發布及完整成本回流全部保留；第一條接單流程完成不等於全平台完成。
