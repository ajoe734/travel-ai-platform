# 旅行平台專案 · Travel AI Platform

服務台灣經營者與國內外旅客的商家接單與營運助理。協作商家既有的客服、電話、預約、PMS、POS、CRM、金流與銷售渠道，完成接單、售後、服務改善與渠道執行。

**目前階段：既有 SA／UX 文件入庫與 SD 工程交接。** 本專案已收錄原始規格、工程契約及可操作的本機 UX 原型；尚未包含正式後端、已連通的 OTA／PMS／電話／金流，或完成的生產環境。

## 先從這裡閱讀

1. [目前有效決策](docs/project/current-decisions.md)：後續對話對產品、架構與商家操作方式的修訂。
2. [完整文件索引](docs/README.md)：原始文件、可讀文字、工程附件、原型與歷史版本。
3. [SA 與下一階段 SD 的差異](docs/sd/sa-v1-gaps.md)：已查核的具體缺口及驗收方向。
4. [herdr 開發交接](docs/collaboration/herdr-handoff.md)：讀取順序、任務切分、交付與驗證規則。
5. [AGENTS.md](AGENTS.md)：進入這個 repository 的開發代理共同遵循的規則。

## 文件與實作狀態

| 內容 | 位置 | 正確用途 |
| --- | --- | --- |
| 產品規劃 v1.0、執行角色增補 v1.1 | [需求文件](docs/requirements/README.md) | 產品背景、責任與功能需求；保留原始 Word、PDF |
| 開發 SA v1.0 | [SA 文件](docs/sa/README.md) | 需求、案例、交易規則與參考設計 |
| OpenAPI、SQL、事件、測試案例 | [工程契約](specs/README.md) | 未改寫的 SA 工程基線；SQL 尚非正式 migration |
| 最新架構整理與缺口 | [SD 入口](docs/sd/README.md) | 進入工程設計前先處理的差異；不冒充已完成實作 |
| UX 2.0 原型與設計說明 | [UX 入口](docs/ux/README.md) | 可操作的模擬流程，仍須接上真實工作狀態 |
| 舊版 UX 1.0 | [歷史檔案](docs/archive/ux-v1/README.md) | 保留設計沿革；不是目前商家介面的開發依據 |
| 原檔對照與校驗 | [匯入紀錄](docs/provenance/README.md) | 原始包內容對應到 repo 的檔案與 SHA-256 |
| 本次與歷史驗證 | [驗證紀錄](docs/verification/README.md) | 區分靜態檢查、模擬原型、資料庫與真實整合 |

## 檢視 UX 原型

原型入口是 [prototypes/merchant-assistant/ux-v2/index.html](prototypes/merchant-assistant/ux-v2/index.html)。下載或 clone 專案後，在專案根目錄執行：

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

開啟 `http://127.0.0.1:8000/prototypes/merchant-assistant/ux-v2/`。畫面中的接單、退款、發布、成本與成功結果都是原型資料，不會觸發實際交易。GitHub 的 HTML 檔案頁只顯示原始碼。

## 驗證文件與工程契約

```bash
python3 -m pip install -r requirements-validation.txt
python3 scripts/validate_repository.py
```

這個命令檢查原始檔案校驗值、文件連結，並在暫存副本執行 SA 契約驗證；不改寫原始驗證報告。實際驗證範圍與未完成項目見[驗證說明](docs/verification/README.md)。

## 下一個開發起點

先完成 `Work`、執行命令、核准版本、連接器能力與結果驗證之間的 SD 契約，再選取一條可驗收的接單流程落地。住宿房晚、活動場次、交通座位與餐飲預約保留各自模型；既有工具的主要資料責任不可由第二份主檔取代。具體缺口見 [SD 差異清單](docs/sd/sa-v1-gaps.md)。

本 repo 未假設任何系統投入估值、股權比例、既有渠道權限或正式第三方串接成果。
