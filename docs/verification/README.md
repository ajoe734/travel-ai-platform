# 驗證範圍與執行方式

## 本次可重跑的檢查

```bash
python3 scripts/validate_repository.py
python3 scripts/validate_repository.py --json
node tests/prototype-regression.cjs
```

腳本檢查：

- 12 個原始 Word／PDF／HTML 的檔案大小及 SHA-256。
- 文件中的本地連結與必要入口檔案。
- 三版原型內嵌 JavaScript 的語法，需系統提供 Node.js；未安裝時明確記錄未執行。

[本次靜態結果](repository-validation.json)是本次提交前的紀錄。日後以重新執行腳本的結果為準。

## 原型互動

[原型檢查報告](prototype-audit.md)列出 UX 2.0 問題、UX 2.1 修正、Node VM／最小 DOM 的實際測試與限制。這是腳本層驗證，不能替代瀏覽器視覺、鍵盤操作、行動裝置或無障礙測試。

[18 項原型回歸檢查](../../tests/prototype-regression.cjs)可用 Node 標準函式庫重跑，驗證渠道狀態組合、原有核准／授權流程、描述保存及容量邊界；已知原型限制另列，不計入通過項目。

## 尚未驗證的系統

本次未啟動正式資料庫、API server 或耐久流程 Worker，未與真實 OTA、PMS、電話、LINE、支付商串接，未建立生產部署。歷史研究報告提及的 YAML／SQL／TypeScript 檔案，如果未取得其本體，不能把該報告的驗證說法算成本次測試。

CI 執行 repository 檢查與 Node VM 原型回歸檢查；不能據此宣稱整個平台通過整合測試。GitHub Actions 的實際執行結果應在對應 commit／PR 檢視，不以 workflow 檔案存在作為執行成功的證據。
