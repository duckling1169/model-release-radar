from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
INGEST = (ROOT / "workflows" / "mrr_daily_ingest.yaml").read_text(encoding="utf-8")
HEALTH = (ROOT / "workflows" / "mrr_daily_health.yaml").read_text(encoding="utf-8")


class M5WorkflowContractTests(unittest.TestCase):
    def test_ingest_derives_previous_utc_day_and_waits_twenty_minutes(self) -> None:
        self.assertIn("sys.now() - 86400", INGEST)
        self.assertIn("--start=", INGEST)
        self.assertIn("--end=", INGEST)
        self.assertIn("timeout: 1200", INGEST)
        self.assertIn("run.jobs.runWithOverrides", (ROOT / "infra" / "m5_workflow_runner_role.yaml").read_text())

    def test_ingest_has_a_safe_manual_alert_test(self) -> None:
        self.assertIn('test_failure: true', INGEST)
        self.assertIn("Manual alert-path verification", INGEST)
        self.assertIn("mrr_alert_type=workflow_failed", INGEST)

    def test_health_checks_the_official_two_source_gold_contract(self) -> None:
        self.assertIn("mrr_gold.daily_source_metrics", HEALTH)
        self.assertIn("COUNT(DISTINCT source) = 2", HEALTH)
        self.assertIn("COUNTIF(source_status = 'succeeded') = 2", HEALTH)
        self.assertIn("mrr_alert_type=missing_gold", HEALTH)


if __name__ == "__main__":
    unittest.main()
