-- Rollback is safe only before voice records are relied upon.  Once data has
-- been exported or a provider has delivered a transfer result, use a
-- forward-fix migration instead of deleting the evidence.
BEGIN;
DROP TABLE IF EXISTS voice_payment_handoff;
DROP TABLE IF EXISTS asynchronous_media_intake;
DROP TABLE IF EXISTS voice_transfer;
DROP TABLE IF EXISTS voice_playback;
DROP TABLE IF EXISTS voice_turn;
DROP TABLE IF EXISTS voice_session;
COMMIT;
