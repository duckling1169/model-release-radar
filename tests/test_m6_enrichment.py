from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
JOB = ROOT / "pipeline" / "enrich_job.py"
INGEST = (ROOT / "workflows" / "mrr_daily_ingest.yaml").read_text(encoding="utf-8")
HEALTH = (ROOT / "workflows" / "mrr_daily_health.yaml").read_text(encoding="utf-8")
SCHEMA = (ROOT / "infra" / "setup_official_bigquery.py").read_text(encoding="utf-8")


class M6EnrichmentContractTests(unittest.TestCase):
    def test_enrichment_job_is_bounded_and_uses_only_approved_public_fields(self) -> None:
        source = JOB.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('DAILY_REQUEST_CAP = int(os.environ.get("GEMINI_DAILY_REQUEST_CAP", "100"))', source)
        self.assertIn("summary_or_abstract", source)
        self.assertIn("selected_metadata", source)
        self.assertIn("never forward the raw metadata blob", source)
        self.assertIn("responseJsonSchema", source)
        self.assertIn("succeeded_with_backlog", source)

    def test_enrichment_is_append_only_and_separate_from_gold(self) -> None:
        self.assertIn('ENRICHMENT = "mrr_enrichment"', SCHEMA)
        self.assertIn("item_enrichments", SCHEMA)
        self.assertIn("enrichment_runs", SCHEMA)
        self.assertIn("CREATE TABLE IF NOT EXISTS", SCHEMA)
        self.assertNotIn("DELETE FROM", JOB.read_text(encoding="utf-8"))

    def test_workflow_isolates_enrichment_and_alerts_only_after_three_failures(self) -> None:
        self.assertIn("mrr-production-enrich", INGEST)
        self.assertIn("severity: WARNING", INGEST)
        self.assertIn("mrr_enrichment_job_failed", INGEST)
        self.assertIn("mrr_enrichment.enrichment_runs", HEALTH)
        self.assertIn("COUNT(*) = 3 AND COUNTIF(status = 'failed') = 3", HEALTH)
        self.assertIn("mrr_alert_type=enrichment_consecutive_failure", HEALTH)


if __name__ == "__main__":
    unittest.main()
