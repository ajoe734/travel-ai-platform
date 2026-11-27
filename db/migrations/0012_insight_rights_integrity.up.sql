-- ENG-11 migration 0012 forward fix: immutability and tenant/asset integrity for media rights.
BEGIN;

ALTER TABLE asset
  ADD CONSTRAINT asset_tenant_fk FOREIGN KEY (tenant_id) REFERENCES tenant(id),
  ADD CONSTRAINT asset_available_requires_checked
    CHECK (lifecycle_status NOT IN ('APPROVED','AVAILABLE') OR scan_status = 'CHECKED');

ALTER TABLE asset_rights_grant
  ADD CONSTRAINT asset_rights_grant_tenant_id_id_asset_id_unique UNIQUE (tenant_id, id, asset_id);

ALTER TABLE proposal_asset_use
  ADD CONSTRAINT proposal_asset_use_grant_asset_fk
    FOREIGN KEY (tenant_id, rights_grant_id, asset_id)
    REFERENCES asset_rights_grant(tenant_id, id, asset_id);

CREATE TRIGGER operating_insight_immutable
  BEFORE UPDATE OR DELETE ON operating_insight
  FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
CREATE TRIGGER merchant_discussion_message_immutable
  BEFORE UPDATE OR DELETE ON merchant_discussion_message
  FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

COMMIT;
