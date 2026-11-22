# 原始文件來源與匯入紀錄

本次實際取回並原樣匯入 **12 個檔案**：4 個 Word、6 個 PDF、2 個 HTML。Word／PDF 保留原始檔名；HTML 改以各版本資料夾的 `index.html` 放置，位元組內容不變。每一個目的檔都已與來源計算 SHA-256 比對。

## 清單

- [機器可讀來源清單](source-manifest.json)
- [CSV 來源清單](source-manifest.csv)
- [全文抽取檢查](extraction-report.json)

來源清單只記錄原始檔名、repo 相對路徑、位元組數與 SHA-256。Word 可讀版是轉存衍生物，沒有代替原始檔；4 個 Word 的所有正文可編輯文字節點皆已涵蓋，表格依出現順序保留。圖像與自動編號保留於原始文件，轉存版提供對照提示。

| 類別 | 原始檔數 | 位置 |
| --- | ---: | --- |
| 系統規劃 v1.0、執行角色 v1.1 | 4 | [需求文件](../requirements/README.md) |
| SA v1.0 | 2 | [SA 文件](../sa/README.md) |
| UX v1.0 設計、原型與 SA 合訂版 | 4 | [歷史 UX](../archive/ux-v1/README.md) |
| UX 2.0 修訂與原型 | 2 | [目前 UX](../ux/README.md) |

## 尚未取回的原工程附件

SA 主文列出以下獨立附件，但本次未取得它們的原始檔案：

- `openapi.yaml`、`openapi.json`
- `01_schema.sql`、`02_atomic_refund.sql`
- `資料字典.md`、`tables.metadata.json`
- `events/*.schema.json`
- `requirements_traceability.json`
- `use_cases.md`、`use_cases.json`、`state_transitions.json`
- `acceptance.feature`、`acceptance_cases.md`
- `validate_package.py`、`validation_report.json`

較後的工程交付報告另曾引用 `travel-platform-engineering.zip`、`travel-ai-platform-bootstrap.zip`，以及 migrations、Connector SDK、mock adapters、Temporal workflows、tests、React prototype 的歷史路徑；本次未取得那些壓縮包本體。過往對話中的「三個壓縮包、237 檔」亦未在本次原檔範圍得到驗證。

本目錄不把歷史交付聲明當成已匯入證據，也不以重新生成的同名檔替代未取得的原件。SA 主文中的 API／事件／驗收摘要可以閱讀與追溯；獨立工程附件仍須找到本體，或另立明確的新版本補完。

## 驗證範圍

已驗證原始來源與目的檔的 SHA-256 一致，以及 Word 正文的文字節點涵蓋。這不是 PostgreSQL migration、外部 connector、金流、Temporal Worker 或完整業務驗收的執行結果。
