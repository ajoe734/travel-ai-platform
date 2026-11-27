# ENG-12 企業計費、渠道結算與成本回流

實作位於 migration `0010` 與 `db/repository/billing_repository.py`。所有金額均是整數最小
單位，並保存幣別與 scale reference；本模組不從原型、模型輸出或 usage kind 推定費率。

`billing_contract_version` 是不可變合約快照。建立 `business_fee_charge` 時必須同時給出該
版本、穩定 business key 與 request hash；同一 key 同內容只回傳原列，內容不同則拒絕。這讓
平台錯誤重試與 API key 改變不會重收同一筆企業業務費。

`order_attribution` 一次固定為 `ORIGINAL_CUSTOMER`、`CHANNEL_CUSTOMER` 或
`DIRECT_CUSTOMER`。`settlement_entry` 將 `GMV`、`PLATFORM_REVENUE`、
`CHANNEL_COMMISSION` 及 `SUPPLIER_PAYABLE` 分列，故 GMV 不能被查詢端當作平台收入。
退款正式成功後，`record_settlement_reversal()` 只會新增引用原 entry 的負數列；它會限制累計
沖回不超過原項目，從不更新原佣金。

`operational_cost_record` 在同一期間保存成功、未成交、失敗及取消案件的
`VOICE`、`MODEL`、`MESSAGE`、`QUERY`、`HUMAN` 成本。供應商最終 usage 未到時用
`INCOMPLETE` 且金額為 NULL，而非零；`cost_summary_by_outcome()` 保留這個狀態。
`manual_remediation=true` 的 Case 不會進入 `automatic_success_case_count`。

這是營運／合作對帳所需的子帳，不是法定總帳、發票、稅務或實際渠道付款結算。真實費率、
稅務與供應商對帳窗口仍須由相應的版本化契約與 connector evidence 接通。

驗收證據見 [acceptance-trace.md](acceptance-trace.md)。需真實 PostgreSQL 的測試指令為：

```bash
pytest tests/db/test_billing_settlement_cost.py -v
```
