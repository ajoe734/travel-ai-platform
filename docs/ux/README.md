# UX 設計與可操作原型

本目錄保存最新已取回的 UX 2.0 介面修訂與可操作 HTML 原型。原型仍是本機流程展示；頁面顯示的成功、訂單、退款及發布結果，不代表外部服務已執行。

目前檢視入口為 [UX 2.1 修訂原型](../../prototypes/merchant-assistant/ux-v2.1/index.html)。本次依 UX 2.0 修正渠道狀態、自訂描述及容量驗證；保留原版供比對。修改與腳本層驗證見[原型檢查報告](../verification/prototype-audit.md)。後續 Work／Credit 後端仍須依 SD 開發。

- [UX 2.0 原始 PDF](originals/商家接單助理_UX2.0_介面與互動修訂.pdf)
- [PDF 文字抽取](ux-v2.0-extracted.txt)
- [UX 2.0 原始原型 HTML](../../prototypes/merchant-assistant/ux-v2/index.html)
- [舊版 UX v1.0](../archive/ux-v1/README.md)

## 本機開啟

在專案根目錄執行：

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

用瀏覽器開啟 `http://127.0.0.1:8000/prototypes/merchant-assistant/ux-v2.1/`。GitHub 的 HTML 檔案頁顯示原始碼，不直接執行原型。

UX 1.0 與 UX 2.0 的 HTML 均原樣匯入，內容未改寫，校驗值見[來源清單](../provenance/source-manifest.json)。UX 2.1 是本次新增修訂，不列入原始檔 manifest。圖像與版面應以原始 PDF／原型為準，文字抽取僅供檢索。
