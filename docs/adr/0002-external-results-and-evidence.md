# ADR 0002 外部能力與結果分開

日期：2026-11-22。狀態：本次補充設計，待實作驗收。

## 依據

[SA 07.2](../sa/sa-v1.0.md)範例把 SUPPORTED、PENDING、UNKNOWN、UNSUPPORTED 放在同一 status；[第一批報告](../research/2026-11-21-engineering-batch1.md)用 SUCCEEDED、UNKNOWN、FAILED，但將渠道審核中也壓成 UNKNOWN。前者混合能力與結果，後者缺少已知非終態。

## 決策

能力登錄獨立回答是否支援、已取得權限、執行方式、可讀回欄位與核對限制。實際寫入結果只使用 `SUCCEEDED | PENDING | UNKNOWN | FAILED`，其完整契約見[Connector 文件](../sd/connector-result-and-reconciliation.md)。

PENDING 代表提供者已確認受理且可識別該操作，但尚未完成；UNKNOWN 代表無法確定已送出的副作用是否生效。兩者都不能因等太久自動宣告失敗或重做。只有正式終態證據或可證明未執行的失敗，才允許釋放金額保留。

成功結果還需由 domain verifier 判定完成條件。商品存在不代表已上架；送出退款不代表退款完成；通知被接受不一定代表送達，取決於該通知工作的已定完成契約。

Publication 每渠道保存 desired／submitted／observed。父 Work 的 PARTIAL 保留每個子結果，不重新執行已成功渠道。已知 pending 與未知結果的 UX 文案分別為「等待渠道審核／處理」與「結果核對中」。

## 後果

SDK 需加 PENDING variant；不能只解析 YAML 就宣稱契約測試完成。mock 必須覆蓋同步成功、已受理等待、成功後連線中斷、正式失敗與不支援能力。舊三態資料的 UNKNOWN 不可在無證據下批次轉成 PENDING。
