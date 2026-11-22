# 架構決策紀錄

這些 ADR 是 2026-11-22 為銜接已找回 SA 與後續研究新增的工程設計。狀態為「本次補充設計，待實作驗收」，不是對既有系統已完成遷移的聲明，也不替商家核准金額或外部操作權。

| ADR | 決策 |
|---|---|
| [0001 領域命名與相容](0001-case-work-execution.md) | 保留 Case 與 Complaint，新增 Work，ExecutionTask 沿用穩定操作語意 |
| [0002 外部結果與證據](0002-external-results-and-evidence.md) | 能力、執行結果與業務狀態分開；PENDING 不壓成 UNKNOWN；完成需正式證據 |
| [0003 不可變授權與金額保留](0003-immutable-approval-and-reservations.md) | 批准內容不可改、撤回追加、授權只綁同一根操作；UNKNOWN 不釋放保留 |

變更 ADR 時，應列影響的欄位、命令、事件、驗收與相容策略；同一 PR 同步 SD，不以新名字另外建立第二套相同 domain。
