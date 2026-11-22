# 第一垂直切片驗收矩陣 v0.1.0

## 驗收邊界

測試環境使用固定 mock connector、假資料與測試租戶。任何案例不得呼叫真實支付、退款、供應商訂位或渠道發布 API。每個測試記錄 build SHA、migration version、fixture version、command、結果與 trace/correlation ID。

## 核心成功路徑

| ID | Given | When | Then |
|---|---|---|---|
| V01 | tenant A 有有效 Case | 建立 BOOKING Work | Work tenant_id 與 Case 相同，status=DRAFT，criteria 非空 |
| V02 | Work 有完整輸入、可售 mock 與有效 policy | 排程 Work | Work=RUNNING，建立 Task 與 outbox event |
| V03 | mock 可售並回傳價格 | 建立 Quote | Quote 固定 service version、日期、時區、人數、幣別、條款、供應快照及 expiry |
| V04 | 報價政策要求客戶確認 | 客戶確認該 Quote | confirmation ref 綁定 quote id + revision + hash；不得由 LLM 自行填入 |
| V05 | 政策要求商家批准 | 指定角色批准當前 revision/hash | Approval immutable 且 ACTIVE；其他 actor／tenant 不可用 |
| V06 | Quote 未過期、批准有效 | 送出 booking request | 只回 202/CONFIRM_PENDING，不顯示 CONFIRMED |
| V07 | mock provider 明確回 CONFIRMED 並給 reference | reconciliation 成功 | 保存 external reference + evidence；Booking=CONFIRMED |
| V08 | 所有 acceptance criteria 與必要 evidence 齊全 | Work completion evaluator 執行 | Work=SUCCEEDED；Case 可轉 RESOLVED |

## 必須失敗／拒絕的情境

| ID | 情境 | 預期 |
|---|---|---|
| S01 | tenant A 讀取 tenant B 的 Case／Work／Quote | 回 404 或一致的授權拒絕；不可洩漏存在性 |
| S02 | Work.case_id 指向其他 tenant | DB constraint 拒絕 |
| S03 | Idempotency-Key 相同但 request hash 不同 | 409 IDEMPOTENCY_KEY_REUSED |
| S04 | 相同 key + 相同 payload 重送 | 回傳同一資源／結果，不建立第二副作用 |
| S05 | Quote 已過期 | 422 QUOTE_EXPIRED；需重新查價 |
| S06 | 人數、日期、供應商或金額改變後沿用舊批准 | 409 APPROVAL_STALE |
| S07 | 批准已撤回／過期／scope 不含該操作 | 執行前拒絕，不呼叫 connector |
| S08 | actor 沒有 branch／resource 權限 | 403/404，記錄 audit |
| S09 | Connector 不支援預訂能力 | 呼叫前 BLOCKED CAPABILITY_NOT_SUPPORTED |
| S10 | provider 明確回拒絕 | Booking=REJECTED；Work依補救條件 BLOCKED/FAILED |
| S11 | provider 回 PENDING | Task=PENDING，Work=WAITING_EXTERNAL；排程查核 |
| S12 | 網路 timeout，無法知道是否已建立 | Task=UNKNOWN → RECONCILIATION_REQUIRED；不得換 key 重送 |
| S13 | reconciliation 查到已成功 | 使用原 booking reference 收斂為 CONFIRMED |
| S14 | reconciliation 查到不存在且 provider 保證無副作用 | 才允許以相同 operation key 按 adapter 規則安全重試 |
| S15 | webhook 重送 | inbox unique 去重；不重複轉移／建立 booking |
| S16 | webhook 亂序 | aggregate version／provider sequence 防止狀態倒退 |
| S17 | 外部成功但本地 DB 寫入失敗 | outbox／reconciliation 找回；不可再次建立外部 booking |
| S18 | 通知寄送失敗 | Booking/Work 不回退；建立獨立通知 retry |
| S19 | Work 已 SUCCEEDED 再要求 run | 409 TERMINAL_STATE；另建 follow-up Work |
| S20 | 同一 Task 建立兩個並行副作用 | DB operation key unique + worker lease 防止 |
| S21 | 同一付款成功回呼兩次 | 不重複 capture／記帳；付款狀態單調且可對帳 |
| S22 | Case 是標準取消而非客訴 | 不強制建立 Complaint |
| S23 | 退款完成 | 不自動將 Complaint 設為 CLOSED |
| S24 | 以 HTTP 200 但缺少 provider confirmation | 不可將 Booking 設 CONFIRMED |
| S25 | 模型輸出「客戶已同意」但無可信 confirmation ref | 不建立 booking |
| S26 | 使用者輸入惡意 prompt 指示讀其他商家 | 工具層仍依 tenant 授權拒絕 |
| S27 | 0 人、負數人數、無資源項目 | 前後端 schema 都拒絕 |
| S28 | currency 缺漏／小數 float 金額 | 拒絕；只接受 amount_minor + ISO currency |
| S29 | 本地 Worker 重啟 | 從持久狀態恢復，不遺失排程 |
| S30 | outbox publish 重複 | consumer 去重，不重複處理 |
| S31 | Approval revoke 與 execute 競態 | 以交易鎖／版本檢查確保撤回後不得開始新副作用 |
| S32 | Connector account 被停用 | 新副作用拒絕；已在途項目先 reconciliation |
| S33 | provider reference 不唯一或 mapping 衝突 | MANUAL_REVIEW；不得覆蓋其他 booking |
| S34 | 成功證據 storage_ref 不存在／digest 不符 | 不得 Work=SUCCEEDED，告警 |
| S35 | DST 夏令時間不存在／重複的當地時間 | 明確要求 offset/fold 選擇或拒絕；不可默默偏移 |
| S36 | 客戶通知送達但供應未確認 | 仍不可顯示預訂成功 |

## Definition of Done（每項 ENG 任務）

- [ ] 有需求追溯：SA FR／W 編號、SD 文件、backlog ID。
- [ ] 有實作及版本化契約；沒有僅新增空介面／TODO。
- [ ] 有 migration 與資料回復策略（若涉及 DB）。
- [ ] 有正常、拒絕、逾時、重試、亂序及租戶隔離測試（依適用範圍）。
- [ ] 測試命令可在乾淨環境重跑；PR 列出實際輸出。
- [ ] 有 log/metric/trace，不含秘密與不必要 PII。
- [ ] 文件與 ADR 同步更新。
- [ ] 明確列出 mock、sandbox、production 的真實驗證層級。
- [ ] 未授權時沒有真實外部副作用。
- [ ] HerdR 回報下一個可獨立領取的任務與阻塞項目。

## 測試層級不可混稱

1. Unit：純函式、狀態轉移、政策判斷。
2. Contract：OpenAPI/event schema/adapter contract。
3. Integration：真實 Postgres、transaction、RLS、outbox/inbox。
4. Workflow：worker restart、retry、timeout、reconciliation。
5. E2E mock：完整旅客需求到 booking evidence。
6. Sandbox：供應商／金流沙盒；必須列出帳號、能力與測試範圍。
7. Production pilot：需另行授權、風險評估、限額與回復方案；本契約不授權執行。
