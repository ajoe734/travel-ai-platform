-- Travel AI Platform migration 0003 v0.1.0
-- Enforce one booking per customer confirmation at the database boundary.
-- This is required even if application code also marks confirmation as consumed.
BEGIN;

CREATE UNIQUE INDEX bookings_customer_confirmation_single_use
  ON travel.bookings(tenant_id, customer_confirmation_id)
  WHERE customer_confirmation_id IS NOT NULL;

COMMIT;
