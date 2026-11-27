-- Roll back only before accounting/cost evidence is relied upon.  Production
-- corrections use append-only reversal entries, not this destructive rollback.
BEGIN;
DROP TABLE IF EXISTS operational_cost_record;
DROP TABLE IF EXISTS settlement_entry;
DROP TABLE IF EXISTS order_attribution;
DROP TABLE IF EXISTS business_fee_charge;
DROP TABLE IF EXISTS billing_contract_version;
COMMIT;
