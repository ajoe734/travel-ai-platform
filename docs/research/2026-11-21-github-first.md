# 旅行平台 GitHub-first 工程交付狀態與立即執行結果

> 來源轉存：本檔為既有研究報告的主文，原報告中的交付與測試描述代表當時說法。2026-11-22 接手時的實際檔案與驗證狀態，請以 [原檔匯入紀錄](../provenance/README.md) 及 [驗證說明](../verification/README.md) 為準。歷史 sandbox 路徑不代表 repository 中已有對應工程檔案。來源引用已由原報告所附網址轉為一般連結。


## 實際執行狀態

我已把「旅行平台專案」的交付方式正式切換成 **GitHub-first 協作模式**，但這次工作階段有一個關鍵限制必須明確揭露：**目前可用工具中沒有可對你的 GitHub 帳號執行建立 repository、commit、push、PR 或 branch-rule 設定的 GitHub 寫入連接器**。因此，我**沒有**建立 `travel-ai-platform` GitHub repository，也沒有 GitHub commit SHA 或 PR URL；任何聲稱已經建立或已經 push 都會是不實陳述。

GitHub 本身支援建立 private repository，也可以透過 Web 或 GitHub CLI 建立；private repo 的分支保護、required reviews、required status checks 等能力則依 GitHub 方案而異。 [Creating a new repository - GitHub Docs](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository?utm_source=chatgpt.com)

我也搜尋了目前對話附件與 File Library，希望直接找回先前聲稱已產出的 PostgreSQL migrations、OpenAPI／AsyncAPI、Connector SDK、mock adapters、Temporal workflows、tests 與 React UX prototype。**沒有找到那批旅行平台工程檔案的可取用版本**。目前最接近的工程類文件是一份其他專案的 System Design Alignment 文件，而且該文件自己明確標示其任務「不是 implementation code」，不能拿來冒充這個旅行平台的 initial import。 （原報告引用文件：貼上的 Markdown (1).md；未以此推定本次取得）

因此，依你指定的規則，我沒有重新生成一套看似完整但與先前版本可能不一致的 migrations、API contract、workflow 或 UX prototype，也沒有假稱它們已上傳。

## 已實際建立的 GitHub 協作骨架

在不能直接寫入 GitHub 的前提下，我先建立了一份**可直接作為新 private repo bootstrap 的真實 Git repository 骨架**。這不是原工程包的替代品，而是新的協作治理層；它刻意沒有偽造缺失的 migrations、OpenAPI、AsyncAPI、SDK 或 prototype。

目前實際建立的內容包括：

```text
travel-ai-platform/
├── README.md
├── AGENTS.md
├── .env.example
├── .gitignore
├── apps/
├── packages/
├── db/
│   └── migrations/
├── openapi/
├── asyncapi/
├── tests/
├── scripts/
├── docs/
│   ├── architecture/
│   │   ├── invariants.md
│   │   └── import-status.md
│   ├── adr/
│   ├── domain/
│   └── ux/
└── .github/
    ├── workflows/
    │   └── ci.yml
    ├── ISSUE_TEMPLATE/
    │   └── engineering-change.md
    └── pull_request_template.md
```

`AGENTS.md` 已寫入給 **herdr** 與人類工程師共同遵守的架構不變條件，包括：供應商中立核心、Work／DecisionRequest／ApprovalRecord／AuthorizationDecision／CompletionEvidence、`UNKNOWN → reconciliation`、不得盲目 retry 外部 side effect、idempotency、多租戶隔離、AI planning 不等於交易授權、契約與測試必須跟 implementation 同一個 PR 更新。

我也建立了一個本地 Git commit，SHA 為：

```text
29486f01ae73167e4a3c0a3750f1eb16f2ea267d
```

**這是本地 bootstrap repository 的 commit SHA，不是 GitHub commit SHA。**

可直接取得這份實際檔案：

travel-ai-platform-bootstrap.zip（歷史路徑：`sandbox:/mnt/data/travel-ai-platform-bootstrap.zip`）

ZIP 的 SHA-256 為：

```text
b48b76f5d7819c78d286e3ac4243e7fe978e3ba0f18ff8ef44036f3885a7e753
```

## Repository 治理方式

`main` 應作為穩定整合分支；實作工作全部走 `feature/*` branch → PR → CI → review gate。GitHub 可以要求 PR review、required status checks、conversation resolution、signed commits、linear history，以及禁止直接 push 等規則。 [About protected branches - GitHub Docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches?apiVersion=2022-11-28&utm_source=chatgpt.com)

建議正式 repo 啟用的最小 gate 是：

```text
main
 ├─ 禁止直接 feature 開發
 ├─ Require pull request
 ├─ 至少 1 位 reviewer
 ├─ Require status checks
 │   ├─ lint
 │   ├─ typecheck
 │   ├─ test
 │   └─ build
 ├─ Require conversation resolution
 └─ 禁止 force push / delete
```

如果團隊之後增加 CODEOWNERS，可以讓特定目錄的變更自動要求對應 owner review；GitHub 也支援把 CODEOWNERS review 與 protected branch 搭配。 [About code owners - GitHub Docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners?azure-portal=true&utm_source=chatgpt.com)

這些目前都只是**repo 應啟用的治理規則**。我沒有聲稱它們已經在你的 GitHub 帳號啟用，也沒有聲稱 CI 已通過。

## Monorepo 與架構邊界

repo 結構會遵守「完整架構先設計、分階段實作」原則，而不是「第一版只接一個系統，所以核心直接綁那個系統」。

預定責任邊界如下：

```text
apps/
  merchant-console/
  traveler-web/
  operations-console/

packages/
  domain/
  application/
  authorization/
  workflows/
  connector-sdk/
  connectors/
  observability/

db/migrations/

openapi/
asyncapi/

docs/
  architecture/
  adr/
  domain/
  ux/
```

未來 OTA、PMS、POS、CRM、電話、LINE、支付與其他渠道都透過 `connector-sdk` 與 capability contract 擴充，不能把某一家供應商的字段或交易邏輯滲進核心 domain。

核心必須一直保留以下分離：

```text
Technical Capability
        ≠
Account Authorization
        ≠
Merchant Consent
        ≠
Operational Availability
```

同樣地：

```text
API accepted
≠
business operation completed
≠
verified
≠
customer notified
```

這些條件已寫進 `AGENTS.md`，讓 herdr 未來在產生程式碼時不是只讀 README，而是有一份明確的 AI coding agent contract。

## Initial Import 的缺口與禁止事項

目前不能誠實完成的 initial import 是以下八類既有工程產物：

```text
PostgreSQL migrations
OpenAPI contracts
AsyncAPI contracts
TypeScript Connector SDK
three mock adapters
Temporal workflows
tests
React UX prototype
```

這些檔案目前不在可檢索來源中，因此**沒有被放進 bootstrap repo**。

我已在：

```text
docs/architecture/import-status.md
```

明確記錄這個缺口，並要求 herdr：

> 不得為了把目錄填滿，而自行重新產生一套名稱相同但內容不同的工程產物。

這一點很重要。否則後面會發生最危險的情況：文件看起來都有，實際上 SA、SD、API contract、DB schema、UX prototype 是不同時間重新生成的幾套版本，最後反而形成你最不希望看到的「疊床架屋」。

## herdr 接手方式

herdr 應把 GitHub repository 視為唯一工程 source of truth，而不是 Deep Research 對話。

正式接手流程應是：

```text
SA / SD 決策
       ↓
ADR / Domain Contract
       ↓
DB / OpenAPI / AsyncAPI
       ↓
Implementation
       ↓
Tests
       ↓
UX contract / prototype
       ↓
Feature branch
       ↓
Pull Request
       ↓
CI + Review
       ↓
main
```

任何 UX 修改如果改變實際業務狀態、權限、API、事件或資料欄位，不能只改 React；同一個 PR 必須同步修改 contract、test 與必要 ADR。

任何 Connector 新增或修改，都不能只「接得動 API」，必須至少通過：

```text
capability contract
authorization
tenant scope
idempotency
UNKNOWN handling
reconciliation
audit
completion evidence
contract tests
```

GitHub 的 PR 與 ruleset／branch protection 本身正適合把這些驗證變成 merge gate，而不是靠人記得。 [Managing and standardizing pull requests - GitHub Docs](https://docs.github.com/en/pull-requests/reference/managing-and-standardizing-pull-requests?utm_source=chatgpt.com)

## 現在真正阻塞的唯一一步

**GitHub repository 尚未實際建立。**

因為本工作階段沒有 GitHub 寫入能力，所以目前最正確的下一個動作是：

> 在你的 GitHub 帳號建立一個新的、空的 **private repository：`travel-ai-platform`**，不要 Initialize README、不要放現有專案內容；建立完成後把 repository URL 提供到這個對話。

GitHub 官方建立 repository 流程支援直接指定 private visibility。 [Creating a new repository - GitHub Docs](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository?utm_source=chatgpt.com)

拿到該 repository 後，工程交付的正確順序就是：

```text
1. 匯入這次已建立的 GitHub-first scaffold
2. 找回並逐檔核對既有工程包
3. 原樣 initial import，不重新生成
4. 建立 initial-import PR
5. 驗證檔案 provenance / hash / tests
6. merge main
7. herdr 從 feature branch 接手
```

目前可確認的交付狀態是：

| 項目 | 狀態 |
|---|---|
| 新 GitHub private repo | **未建立：本工作階段無 GitHub 寫入 connector** |
| GitHub commit SHA | **無** |
| GitHub PR URL | **無** |
| GitHub branch protection | **未啟用／未驗證** |
| GitHub CI | **未執行／未驗證** |
| GitHub-first repo scaffold | **已實際建立** |
| 本地 scaffold commit | `29486f01ae73167e4a3c0a3750f1eb16f2ea267d` |
| AGENTS.md | **已建立** |
| CI workflow | **已建立，但未執行** |
| PR / Issue templates | **已建立** |
| Architecture invariants | **已建立** |
| 舊 migrations / APIs / SDK / workflow / UX | **目前無法取得，因此未偽造匯入** |
| herdr handoff contract | **已寫入 AGENTS.md / README** |