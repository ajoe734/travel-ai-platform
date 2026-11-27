# ENG-12 驗收與退修證據

候選 SHA：待 owner closeout commit。相關需求：SA `FR-26`～`FR-28`、`SA-AT-054`、
`SA-AT-063`，及 `docs/sd/credit-and-refund.md` §8。

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| FR-26：重送／平台錯誤重試不得重收業務費 | `business_fee_charge` 的 `(tenant_id, operation, business_key)` 唯一鍵；`billing_repository.record_business_fee()` 比對 contract、request hash、用量與金額 | 舊基線沒有企業費用持久化，故無法防止重送；新 probe 對同 key 同內容回原列、改金額拒絕 | `pytest tests/db/test_billing_settlement_cost.py -v`，待 hosted PostgreSQL；本機 `python3 -m py_compile ...` 通過 | 本 VM 無 PostgreSQL/psycopg，未執行 DB probe；真實商業費率不在本候選設定 |
| FR-27：歸因、GMV/收入分欄與退款沖回 | `order_attribution`、`settlement_entry`、`record_settlement_entry()`、`record_settlement_reversal()` | 舊基線沒有結算子帳；新 probe 將 GMV 1000 與平台收入 100 分列，正式退款後只加 -50 revenue reversal，原 100 不變；超額沖回拒絕 | 同上；migration DDL 與 repository probe：`test_refund_reversal_is_append_only_and_limited_to_original_settlement` | 尚未與真實渠道／支付方對帳；部分退款比例由正式合約 calculation basis 提供，不由本 repository 推算 |
| FR-28：未成交與不完整 usage 也納入期間成本 | `operational_cost_record`、`cost_summary_by_outcome()` | 舊基線沒有成本回流；新 probe 收錄 `UNCONVERTED` QUERY 與 `INCOMPLETE` VOICE，後者金額保留 NULL 不是零 | 同上；`test_cost_reporting_keeps_unconverted_and_incomplete_usage_and_excludes_manual_success` | 供應商最終 usage webhook/查核尚未接入；本模組保存其結果，不模擬真實 provider |
| FR-28：人工補救不得宣稱全自動成功 | `manual_remediation` 與 `cost_summary_by_outcome()` 中按 Case 聚合的 `bool_or` | 舊基線沒有可稽核的自動成功分母；新 probe 有成功但人工補救的 Case 被排除，另一個純自動 Case 才計 1 | 同上 | 「成功」的業務完成條件仍由 Work/Execution 契約判定；這裡只提供成本報表的排除規則 |
| SA-AT-063：貨幣不可混合、無浮點重算 | 所有金額採 `bigint` minor units、currency／scale reference，contract-to-charge 與 settlement self-reference 均綁同幣別 | 舊基線缺計費/結算資料模型；新版 schema 對跨幣別 FK 與整數金額設 constraint | `python3 scripts/validate_repository.py` → exit 0；真正 migration parse/constraint 行為待 hosted PostgreSQL | 未在本 VM 開 DB；未接法定匯率或稅務規則 |
