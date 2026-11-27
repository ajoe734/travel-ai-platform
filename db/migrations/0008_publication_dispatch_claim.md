# 0008_publication_dispatch_claim

## 內容

新增 `channel_publication.DISPATCHING` 狀態。發布 worker 在短交易中以 revision
CAS 將 `NOT_STARTED` 領取為此狀態並提交；connector 寫入只會發生在交易外。若
worker 在寫入後失敗，該列保留可查核的 business key，而不會被另一個 worker 重送。

## Rollback

尚在 `DISPATCHING` 的列先轉為 `UNKNOWN` 並保留明確查核原因，再移除新狀態。已
發出的渠道寫入不得因 rollback 當作未發生。

## Forward-fix

新增發布狀態時以新 migration 擴充 CHECK；不得重寫已套用的 migration。
