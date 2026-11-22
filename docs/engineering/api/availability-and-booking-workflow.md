# Availability、Quote 與 Booking workflow 契約 v0.1.0

## 1. 可售查詢不是報價，也不是預訂

第一垂直切片採下列順序：

1. 取得已核准 ServiceVersion。
2. 由 server 端選擇 ConnectorAccount 與 capability；不能接受模型指定任意 provider URL。
3. 呼叫對應供應商 adapter 查詢 availability。
4. 將查詢結果與供應商、帳號、資源類型、資源 ID、服務時間、party、查詢時間及有效期限保存為 AvailabilitySnapshot。
5. QuoteService 只接受有效 AvailabilitySnapshot，建立不可變 Quote。
6. 旅客確認綁定 Quote revision + canonical payload hash。
7. PolicyEngine 判斷是否需要商家批准；若需要，Approval 綁定同一 hash。
8. BookingOrchestrator 執行前重新驗證所有條件，建立 booking intent 與 ExecutionTask。
9. ConnectorRuntime 以穩定 operation key 呼叫供應商。
10. Reconciliation 取得最終外部狀態，EvidenceService 保存證據。
11. CompletionEvaluator 依 Work acceptance criteria 判定成功。

## 2. AvailabilitySnapshot 最低欄位

- tenant_id、case_id、service_version_id。
- provider、connector_account_id、capability_name、capability_version。
- resource_type、resource_ref、service_at、service_timezone。
- party 與資源需求（依 activity／room-night／seat／table 類型化）。
- available quantity 或 provider availability decision。
- checked_at、expires_at、provider_reference、response_digest。
- raw provider response 只能存安全物件儲存的 reference；不可直接寫敏感資料進一般 log。

過期 Snapshot 不可建立新 Quote。若供應商沒有即時鎖位能力，Quote 必須標示 availability 是查詢時點結果，Booking 建立時仍需重新確認。

## 3. Quote 快照

Quote 建立後不可更新以下內容：
- service version；
- 日期時間與 IANA timezone；
- party／resource claims；
- line items、amount_minor、currency；
- 稅費與取消條款快照；
- supplier 與 availability snapshot；
- expires_at。

任何影響履約、價格、資源或取消條款的變更都建立新 Quote；舊 Quote 與其 customer confirmation、approval 不可沿用。

## 4. Booking 與付款分離

Booking 表示供應商履約資源的協調狀態；Payment 表示收款狀態。兩者各自有狀態機。只有供應商確認證據可令 Booking=CONFIRMED；只有付款服務商的可信 capture evidence 可令 Payment=CAPTURED。

若付款先成功但供應商拒絕，建立退款 Work；若供應商先成功但付款失敗，依商家政策處理，不得隱藏已成立的供應商義務。任何補救均使用原交易關聯與獨立 operation key。

## 5. CompletionEvaluator

CompletionEvaluator 不接受模型輸出的 boolean。它依 Work type 的版本化規則讀取 DB 狀態與 evidence：
- 必要 Quote、確認與批准均有效；
- Booking 已 CONFIRMED 並有 provider reference；
- 所有 required resources 已被確認；
- 任何付款條件依該 Work policy 滿足；
- 不存在 UNKNOWN／RECONCILIATION_REQUIRED 的必要 Task；
- Evidence digest 與 storage object 可驗證。

通知失敗不阻止交易 Work 成功，但會產生獨立 notification Work／Task。若業務完成條件要求通知送達，則該條件須在 Work acceptance criteria 明確列出。

## 6. 容量資源模型

不可用單一「剩餘名額」欄位套用所有商品：
- 活動：session_id + capacity_unit + quantity。
- 住宿：room_type_id + stay_date + room_count（每晚）。
- 交通：departure_id + seat_class + seat_count 或 vehicle capacity。
- 餐飲：service_slot + table_type + party_size。

Adapter 對外轉換，平台保留 domain-specific resource claim；同一講師、車輛、房間或桌位的共用資源必須有一致的資源鎖定與衝突檢查策略。
