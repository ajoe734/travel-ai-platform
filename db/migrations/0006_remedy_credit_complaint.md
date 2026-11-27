# 0006_remedy_credit_complaint

ENG-07 extends the existing `payment`/`refund` primitive without changing its
original-payment reservation rule. `remedy_preview` is immutable and binds the
order revision, policy and content hash; `remedy_action` is the selected,
authorized operation. Credit is represented by a tenant-scoped account, grant,
append-only ledger, and separately stateful usage reservation. Notification is
intentionally independent from monetary completion, and this migration does
not add any trigger that closes a `complaint`.

The down migration is safe only for an empty ENG-07 deployment. Once a ledger
or remedy record exists, preserve it and add a forward-fix migration instead.
