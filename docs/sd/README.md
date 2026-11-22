# SD 補充設計索引

版本：2026-11-22。用途：讓 HerdR 與開發團隊在已找回的 SA、UX 與研究報告上實作，補齊命名、狀態、授權、外部結果及金額操作的衝突。本目錄是本次新增的工程設計，不是先前遺失工程附件的還原，也不表示程式或整合測試已完成。

## 閱讀順序

| 文件 | 回答的問題 |
|---|---|
| [原始 SA 與目前缺口](sa-v1-gaps.md) | 哪些已在原文規定、哪些本次補足、哪些工程檔仍未找回？ |
| [Work 與 Execution 契約](work-execution-contract.md) | Case、Work、ExecutionTask、Attempt 如何分工，如何等待與完成？ |
| [授權與批准](authorization-and-approval.md) | 如何把具體內容、角色、同意、政策與實際執行綁定？ |
| [Connector 結果與核對](connector-result-and-reconciliation.md) | 已知 PENDING 與 UNKNOWN 如何區分，何時可重試？ |
| [Credit 與退款](credit-and-refund.md) | 如何防止重發額度、超退、重複沖回及提早結案？ |
| [ADR 索引](../adr/README.md) | 本次如何處理新舊文件衝突？ |

## 來源及優先關係

1. [SA v1.0 原文](../sa/sa-v1.0.md)定義既有產品語意、FR-01–32、UC-01–15、BR、SM、UI 及 SA-AT-001–064。它是開發評審規格，不是已運作軟體。
2. [系統規劃 v1.0](../requirements/product-plan-v1.0.md)及[執行角色 v1.1](../requirements/execution-role-v1.1.md)保留商家工具共融、文字與語音接單、標準售後、商家互動、素材及渠道實際執行的產品範圍。
3. [2026-11-20 重建報告](../research/2026-11-20-rebuilt-sasd.md)提出 Task 作為被系統承接的業務責任；[2026-11-21 第一批工程報告](../research/2026-11-21-engineering-batch1.md)改用 Work 命名，提供部分 SQL／API／SDK／workflow／UX 片段。
4. 本目錄針對上述差異新增一套可落地語意。原始來源完整保留，不回改歷史文件讓它看似從未有衝突。本目錄明列的相容映射適用於後續實作；未涉及的 SA 需求繼續有效。

**Case 是接單或營運案件；Complaint 才是客訴物件。** 不得把所有 Case 改成客訴，也不得用新增 Work 取代 Case 的需求版本、回覆所有權與接續驗證。Work 是案件內可完成的責任，ExecutionTask 是其內可受控執行的操作。

## 工程實作規則

- 用既有 SA 識別碼追溯需求；新增驗收以 `SD-W-*`、`SD-A-*`、`SD-C-*`、`SD-M-*` 識別，不冒稱原 SA 案例已執行。
- 所有業務外鍵包含 `tenant_id`；角色授權、渠道投影與資料列隔離同時成立。模型不簽發客戶同意或商家批准。
- Case、Work、ExecutionTask、Complaint、Booking、Payment、Refund 與 Publication 各自保持狀態；一層成功不自動把其他層關閉。
- 寫入命令先建立穩定業務鍵、授權使用與 outbox，再由 worker 執行。HTTP 202、外部接受、正式完成分開。
- 已發出但結果不明的動作保持 UNKNOWN；已知正在處理是 PENDING。前端顯示進度，不以重送新命令處理等待。
- 完成條件是版本化、具型別的後端判定；保存正式來源證據。LLM 不能以自由文字把條件改成較容易完成。
- 語音、通知、退款、發布各有責任與接續。必要售後不因一般探索用量用完而消失；超自動授權範圍交給指定責任人。
- 不預設費率、退款上限、Credit 額度、渠道分潤、資料保留年限或第三方帳號權限。來源的 NT$500 Credit 只用作 UX 範例。

## 開發完成與驗收

本目錄沒有 migration、OpenAPI 或 Worker 實作，不能把文件存在視為功能完成。HerdR 的每個實作 PR 應列出對應 FR／UC／SD 案例、實際改動、測試方式、測試證據及仍未接通的外部能力。

先實作可獨立驗收的共用核心：同租戶資料關聯、Case/Work/Execution、immutable snapshots、授權使用、outbox/inbox、穩定業務鍵與核對流程。之後連接商家工作台、三種不同能力的 mock connector，再依實際帳號逐項做 sandbox／正式整合。模擬與正式紀錄須使用不同 environment，不得互相當作完成證據。

前端展示狀態轉移、資料庫併發驗收、真實 connector 驗證是不同層級的證據。CI 格式檢查通過只代表文件或契約可解析。
