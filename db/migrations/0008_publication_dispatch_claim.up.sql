-- ENG-08 forward-fix: persist an I/O claim between short transactions.
BEGIN;
ALTER TABLE channel_publication DROP CONSTRAINT channel_publication_status_check;
ALTER TABLE channel_publication ADD CONSTRAINT channel_publication_status_check
  CHECK (status IN ('NOT_STARTED','DISPATCHING','PENDING','UNKNOWN','LIVE','FAILED','BLOCKED'));
COMMIT;
