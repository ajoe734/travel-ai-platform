#!/usr/bin/env python3
"""Narrow formal-result mapping tests for ENG-08 (no connector shadowing)."""
from __future__ import annotations
import unittest
from connectors.types import Pending, Succeeded
from services.publication.service import PublicationService

class _Repo:
    def __init__(self): self.row={"revision":1,"desired_version":2,"status":"NOT_STARTED"}; self.saved=[]

class ResultSafetyTest(unittest.TestCase):
    def test_source_revision_must_match_before_live(self):
        # Exercises the real method with only the repository boundary replaced;
        # the connector result type is the ENG-04 SDK type.
        from unittest.mock import patch
        repo=_Repo(); svc=PublicationService()
        with patch("services.publication.service.publications.get_publication", return_value=repo.row), patch("services.publication.service.publications.observe_publication", side_effect=lambda _conn, **kw: kw) as observe:
            row=svc.record_connector_result(None, tenant_id="t", publication_id="p", expected_revision=1,
                result=Succeeded(external_reference="x", data={}, evidence_refs=("evidence-1",), observed_at="2026-11-27T00:00:00Z", source_revision="1"), now="2026-11-27T00:00:00Z")
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["failure_reason"], "STALE_CHANNEL_READBACK")

    def test_known_pending_is_not_unknown(self):
        from unittest.mock import patch
        svc=PublicationService(); row={"revision":1,"desired_version":2,"status":"NOT_STARTED"}
        with patch("services.publication.service.publications.get_publication", return_value=row), patch("services.publication.service.publications.observe_publication", side_effect=lambda _conn, **kw: kw):
            stored=svc.record_connector_result(None, tenant_id="t", publication_id="p", expected_revision=1,
                result=Pending(external_reference="x", reconciliation_token="r", pending_reason="REVIEW", evidence_refs=("evidence-1",), observed_at="2026-11-27T00:00:00Z"), now="2026-11-27T00:00:00Z")
        self.assertEqual(stored["status"], "PENDING")

if __name__ == "__main__": unittest.main()
