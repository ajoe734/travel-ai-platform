# 旅行平台專案 · Travel AI Platform

商家接單與營運助理：承接經營者交代的工作，使用商家既有客服、電話、預約、PMS、POS、CRM、金流與銷售渠道完成接單、售後、服務改善及發布；同一組授權能力可提供給旅客與合作渠道。

**目前階段：原始規格已匯入，SD 對齊文件與 UX 2.1 已交付，可交給 HerdR 接續工程實作。** 本 repository 尚未包含正式後端、已連通的第三方交易系統或生產部署。

## 先讀這幾份

1. [目前有效基線](docs/project/current-decisions.md)：產品方向、版本關係與本次工作範圍。
2. [完整文件索引](docs/README.md)：原始 Word／PDF、全文、研究、SD、原型與歷史版。
3. [SA 與 SD 差異](docs/sd/sa-v1-gaps.md)：跨版本模型與仍待實作的部分。
4. [HerdR 開發交接](docs/collaboration/herdr-handoff.md)與[開發任務](docs/collaboration/backlog.md)：讀取順序、分工、依賴及驗收。
5. [AGENTS.md](AGENTS.md)：開發代理共同規則。

## 本次實際交付

| 內容 | 位置 | 狀態 |
|---|---|---|
| 產品規劃 v1.0、執行角色 v1.1 | [需求文件](docs/requirements/README.md) | 原始 Word／PDF與全文已匯入 |
| 開發 SA v1.0 | [SA 文件](docs/sa/README.md) | 原始 Word／PDF與包含表格的完整主文已匯入 |
| 原始 UX 2.0 與歷史 UX 1.0 | [UX](docs/ux/README.md)、[歸檔](docs/archive/ux-v1/README.md) | 原檔保留，可追溯 |
| UX 2.1 修訂 | [原型程式](prototypes/merchant-assistant/ux-v2.1/index.html) | 修正渠道狀態、自訂服務描述與容量驗證；仍是本機模擬 |
| Work／執行／授權／查核／Credit | [SD](docs/sd/README.md)、[ADR](docs/adr/) | 本次新增設計與驗收規則，待實作 |
| 既有工程與同業研究 | [研究索引](docs/research/README.md) | 4 份主報告文字轉存，歷史交付主張另行核對 |
| 原檔校驗與抽文紀錄 | [來源對照](docs/provenance/README.md) | 12 個原始檔案，SHA-256 與來源一致 |
| 原歷史 OpenAPI／SQL／事件附件 | [取得狀態](specs/README.md) | 尚未取得原件，未以新同名檔案替代 |

SA 主文列出 32 項需求、58 項 API、28 種事件及 64 項驗收；它們的主文與矩陣已保存。獨立 YAML／SQL／JSON 工程附件與歷史 ZIP 的取得狀態，請看[匯入紀錄](docs/provenance/README.md)。主文包含摘要不代表附件已找回或程式已通過整合測試。

## 檢視可操作原型

下載或 clone repository 後，在根目錄執行：

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

開啟 **http://127.0.0.1:8000/prototypes/merchant-assistant/ux-v2.1/**。

UX 2.0 原版保留在 `/prototypes/merchant-assistant/ux-v2/`，UX 1.0 在 `/prototypes/merchant-assistant/ux-v1/`。GitHub 的 HTML 檔案頁只顯示原始碼；這些原型沒有呼叫真實訂位、退款或發布服務。操作差異與限制見[原型檢查報告](docs/verification/prototype-audit.md)。

## 驗證文件與原型語法

```bash
python3 scripts/validate_repository.py
node tests/prototype-regression.cjs
```

使用 Python 3 標準函式庫檢查原檔大小／雜湊、文件連結與必要入口。系統有 Node.js 時，另檢查三版原型的 JavaScript 語法；第二個命令重跑 18 項 Node VM 原型流程檢查。本次紀錄與未驗證範圍見[驗證說明](docs/verification/README.md)。GitHub Actions 執行相同檢查。

## 下一個工程起點

先依 ENG-01 固定 SA 的 `Case`、`Complaint`、`ExecutionTask` 與新增 `Work` 的關係，再做資料庫、正式授權、mock connector 及第一條可驗收的接單流程。商家正常工作由系統推進，只有缺資訊或需要新決策時介入；完成狀態須由正式結果與證據決定。

原 SA 首輪的語音、售後、洞察／討論、素材取得、兩渠道發布及完整成本回流全部保留在任務清單；第一條接單流程完成不等於全平台完成。
