from __future__ import annotations

import unittest

from services.ops.logging import structured_operation_log


class StructuredOperationLogTest(unittest.TestCase):
    def test_keeps_correlation_and_redacts_credentials_and_pii(self):
        record = structured_operation_log(tenant_id="tenant-a", task_id="task-a", correlation_id="corr-a", api_token="token", traveler_name="Ada", unapproved="drop")
        self.assertEqual(record["tenant_id"], "tenant-a")
        self.assertEqual(record["correlation_id"], "corr-a")
        self.assertEqual(record["api_token"], "[REDACTED]")
        self.assertEqual(record["traveler_name"], "[REDACTED]")
        self.assertNotIn("unapproved", record)
