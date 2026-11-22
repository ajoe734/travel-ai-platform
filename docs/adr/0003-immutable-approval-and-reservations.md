# ADR 0003 批准不可變與金額保留

日期：2026-11-22。狀態：本次補充設計，待實作驗收。

## 依據

[SA BR-05–10、BR-16–17](../sa/sa-v1.0.md)要求同意綁版本與內容、授權只消耗到同一父操作、同業務鍵去重及 UNKNOWN 仍保留退款額度。後續[第一批工程報告](../research/2026-11-21-engineering-batch1.md)的 ApprovalRecord 同時含 `revoked_at` 與禁止 UPDATE 的 trigger，須消除語意衝突。

## 決策

ApprovalRecord、ApprovalRevocation、AuthorizationUse 各自只追加。撤回以獨立事件與紀錄表示；讀取時建立有效性 projection，不修改批准時的內容。`revoked_at` 若出現在 API，是 projection，不能回寫 immutable 原表。

批准綁定 canonical payload hash、資源版本、政策版、manifest、用途與期限。一次性的 AuthorizationUse 只綁同一 root ExecutionTask；重試與子項共用它，不能以相同授權另建新業務。事前政策本身可服務多案，每案仍有獨立核對與使用紀錄。

退款上限、商家政策預算與 Credit 餘額是不同約束，各自原子保留。UNKNOWN/PENDING 不釋放；正式成功轉 spent，正式證明無副作用才 release。撤回批准不會讓已送出的外部退款消失。

## 後果

批准／撤回的競態必須在短 DB transaction 建立明確先後；外部 I/O 在 transaction 外。外部可能已收到舊 worker 請求，本地 fence 不能保證外部 exactly-once。實作與驗收詳見[授權](../sd/authorization-and-approval.md)及[金額操作](../sd/credit-and-refund.md)。
