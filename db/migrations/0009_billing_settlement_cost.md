# ENG-12 計費、結算與成本回流

`0009` 新增可執行的記錄層，而不是預設任何商業費率。`billing_contract_version` 保留
合約條款 hash、幣別與版本；`business_fee_charge` 以穩定業務鍵與 request hash 使同一
用量重送不重收，且不同內容不能靜默重用。

`order_attribution` 固定訂單的原客、渠道客或自有直客身分。`settlement_entry` 是不可變
子帳：GMV、平台收入、渠道佣金與供應應付分列；退款後只能由引用原 entry 的負向
reversal 處理，不能覆寫原佣金。`operational_cost_record` 收錄成功、未成交、失敗或取消
案件的語音、模型、訊息、查詢與人工成本；`manual_remediation` 讓報表排除有人補救的
案例，不把它誤算全自動成功。`INCOMPLETE` 用於尚未收到供應商最終用量，並且不冒充零成本。

所有表均有 tenant composite FK、RLS 與 append-only trigger。此 migration 不包含法定總帳、
發票、稅務或真實供應商費率；這些要由已簽訂的合約及外部對帳另行接通。
