# 0004_quote_order_refund_baseline

## 內容

`quote_snapshot`（不可變報價／成交快照）、`order_record`（`specs/domain/order.schema.json`
投影，不合併 booking/payment/refund 三狀態）、`payment`（含 `refunded_amount_minor_units`／
`reserved_amount_minor_units` 兩個計數器與 `payment_balance_not_overdrawn` CHECK）、`refund`
（`UNIQUE(tenant_id, operation, business_key)` 防換 key 重複退款；
`refund_provider_dedupe` 部分唯一索引防重複匯入外部退款）。

## 範圍決策：Refund／RefundReservation 合併

`docs/sd/credit-and-refund.md` §3 把 `Refund` 與 `RefundReservation` 列為兩個實體，各自
有獨立歷史（`RefundReservation.state(HELD/CONSUMED/RELEASED)` 另留不可變 event）。backlog
ENG-02 的驗收只要求「原子退款額度不因併發超退」；完整雙實體分離、`CreditAccount`／
`CreditGrant`／`CreditLedgerEntry`／`PolicyBudgetReservation`／`SettlementEntry` 是
backlog 明列的 ENG-07 範圍。本 migration 把 Refund 本身的 `state` 欄位直接沿用 SD §4
的退款生命週期（`RESERVED,SUBMITTED,PENDING,UNKNOWN,SUCCEEDED,FAILED,CANCELLED`）當
reservation 狀態使用，保留同一筆紀錄；ENG-07 若需要把 reservation 拆成獨立 append-only
event，是在此基礎上新增表，不是修改本次的欄位語意。

## Rollback

反向刪除；先移除 `complaint.order_id` 的延後 FK。

## Forward-fix

`payment_balance_not_overdrawn` 若需要改成允許短暫透支後對帳沖正（不建議），用後續
migration 的 `NOT VALID` CHECK 取代，不 rollback 已有 payment/refund 資料。
