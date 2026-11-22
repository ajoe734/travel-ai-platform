# HerdR 開發交接

更新：2026-11-22。目標是讓開發代理依同一份可追溯基線工作，不再從零產生另一套同名規格。

## 開始工作

在已具備 repository 存取權限的開發環境執行：

```bash
git clone https://github.com/ajoe734/travel-ai-platform.git
cd travel-ai-platform
python3 scripts/validate_repository.py
```

此階段是文件與靜態原型，不需要金鑰、資料庫或支付帳號。檢查腳本使用 Python 標準函式庫；有 Node.js 時會加做原型 JavaScript 語法檢查。後端建立後，再由對應任務引入依賴與鎖定檔。

## 必讀順序

1. [AGENTS.md](../../AGENTS.md)：開發約束。
2. [目前決策](../project/current-decisions.md)：有效基線及實作界線。
3. [來源與原檔](../provenance/README.md)：已取得／未取得的文件。
4. [SA 完整主文](../sa/sa-v1.0.md)：尤其需求、Case／Complaint、執行、退款與驗收。
5. [SD 差異清單](../sd/sa-v1-gaps.md)與 [SD 索引](../sd/README.md)：新增 Work 設計及跨版本修正。
6. [開發任務](backlog.md)：先後依賴及完成條件。
7. [原型檢查](../verification/prototype-audit.md)：已有互動及仍待實作部分。

## 可直接交給開發代理的任務敘述

> 請在 travel-ai-platform 專案接續工作。先完整閱讀 AGENTS.md、docs/project/current-decisions.md、docs/provenance/README.md、docs/sd/README.md 與 docs/collaboration/backlog.md。從 ENG-01 開始，沿用 SA 的 Case、Complaint、ExecutionTask 語意，與新增 Work 對齊；不要把未取得的舊工程附件當成已存在，也不要重建同名檔案後宣稱是原版。每項工作建立分支，交付可執行內容、對應契約、必要測試與實際執行結果。先使用 mock adapter，對外帳號、供應商寫入或支付不在這項任務的授權範圍。完成第一個驗收流程後提交 PR，說明變更、測試、未實作事項與下一項依賴。

## 工作分配

| 分工 | 可獨立處理 | 依賴 |
|---|---|---|
| 領域與資料模型 | ENG-01，接續 ENG-02 | 先讀原始 SA 與本次 ADR |
| 授權與流程 | ENG-03，接續 ENG-05 | 領域 ID、狀態、執行邊界固定 |
| 連接器 | ENG-04 | 共用結果／冪等／證據契約固定 |
| 商家 UX | ENG-06 | 工作與決策 API 契約固定；可先讀原型，不得自訂另一套狀態 |
| 業務擴展 | ENG-07、ENG-08 | 接單流程及共用執行能力通過驗收 |
| 整合與運維 | ENG-09 | 前述流程可在本地啟動 |
| 語音與多媒體 | ENG-10 | 共用案件與交易流程成立 |
| 洞察、討論與素材 | ENG-11 | 可追溯數據、版本與渠道發布能力 |
| 計費與渠道結算 | ENG-12 | 交易、成本、退款與渠道歸因可核對 |

同時開發時，每個代理使用自己的 branch／worktree。共用契約由一個變更負責，其餘代理依該 commit 接續；不要在分支各自新增不相容的 Work／Approval／Result 型別。

## 每份 PR 的交付內容

- 說明解決哪個營運問題、相關 SA 需求／SD 條文與 backlog 編號。
- 列出資料模型、API、事件、狀態及畫面的變更，必要時更新 ADR。
- 提供真正執行的命令與結果；未連真實供應商就寫 mock，未啟動資料庫就不寫 migration 通過。
- 驗證成功路徑及本項風險，例如重複送出、舊批准、跨租戶資源、外部成功但本地逾時。
- 說明 migration／相容性與回復方式；不要直接破壞既有 SA 的識別字與欄位。
- 原檔校驗及文件索引檢查維持通過。

## 原型開啟

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

在瀏覽器開啟 `http://127.0.0.1:8000/prototypes/merchant-assistant/ux-v2.1/`。UX 2.0 原版保留在 `ux-v2/`；UX 1.0 保留在 `ux-v1/`。所有資料與執行均為原型模擬，沒有連接正式交易系統。

## 第一個工程里程碑

完成 ENG-01 至 ENG-05 後，應可在本地啟動一條「建立接單案件與工作 → 取得資料 → 形成正式報價 → 判定授權 → mock 預訂 → 外部結果查核 → 保存完成證據」流程。還須通過逾時後不重複訂位、跨租戶拒絕、授權過期與重複 webhook 的反例。這是第一個可運行里程碑，不以文件數量或模型回答完整度判定完成。

原 SA 首輪完整經營循環仍包括語音接單、數據洞察、商家討論、素材權利、兩入口發布及成本／結算回流；ENG-10～12 不能被省略，首個里程碑不代表全部 SA 驗收結束。
