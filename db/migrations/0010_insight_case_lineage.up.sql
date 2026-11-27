-- ENG-11 forward fix: proposal, Work and insight must remain in the same Case.
BEGIN;
ALTER TABLE work ADD CONSTRAINT work_tenant_id_case_id_unique UNIQUE (tenant_id, id, case_id);
ALTER TABLE operating_insight ADD CONSTRAINT operating_insight_tenant_id_case_id_unique UNIQUE (tenant_id, id, case_id);
ALTER TABLE change_proposal ADD CONSTRAINT change_proposal_work_case_fk
  FOREIGN KEY (tenant_id, work_id, case_id) REFERENCES work(tenant_id, id, case_id);
ALTER TABLE change_proposal ADD CONSTRAINT change_proposal_insight_case_fk
  FOREIGN KEY (tenant_id, insight_id, case_id) REFERENCES operating_insight(tenant_id, id, case_id);
COMMIT;
