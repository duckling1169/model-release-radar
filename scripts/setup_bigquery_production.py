#!/usr/bin/env python3
"""Create the official append-only M4 BigQuery datasets and typed tables.

This command is intentionally idempotent and has no reset counterpart.  It
never alters an existing table and never assigns a default expiration.
"""

from __future__ import annotations

from m2_common import PROJECT_ID, bq_base, query, require_project, run


BRONZE = "mrr_bronze"
SILVER = "mrr_silver"
GOLD = "mrr_gold"
ASSERTIONS = "mrr_dataform_assertions"


def create_dataset(dataset: str) -> None:
    try:
        run(bq_base() + ["show", "--dataset", dataset], capture_output=True)
    except Exception:
        run(bq_base() + ["mk", "--dataset", dataset])


def main() -> int:
    require_project()
    for dataset in (BRONZE, SILVER, GOLD, ASSERTIONS):
        create_dataset(dataset)
    schema = {
        f"{BRONZE}.fetch_runs": "run_id STRING NOT NULL, source STRING NOT NULL, overall_status STRING NOT NULL, source_status STRING NOT NULL, window_start TIMESTAMP NOT NULL, window_end TIMESTAMP NOT NULL, run_started_at TIMESTAMP NOT NULL, run_finished_at TIMESTAMP NOT NULL, page_count INT64 NOT NULL, response_record_count INT64, window_record_count INT64, error STRING, manifest_json STRING NOT NULL, loaded_at TIMESTAMP NOT NULL",
        f"{BRONZE}.huggingface_responses_raw": "run_id STRING NOT NULL, page_number INT64 NOT NULL, window_start TIMESTAMP NOT NULL, window_end TIMESTAMP NOT NULL, fetched_at TIMESTAMP NOT NULL, request_url STRING NOT NULL, request_parameters STRING NOT NULL, http_status INT64 NOT NULL, content_type STRING NOT NULL, response_bytes INT64 NOT NULL, sha256 STRING NOT NULL, response_record_count INT64 NOT NULL, window_record_count INT64 NOT NULL, raw_body STRING NOT NULL, loaded_at TIMESTAMP NOT NULL",
        f"{BRONZE}.arxiv_responses_raw": "run_id STRING NOT NULL, page_number INT64 NOT NULL, window_start TIMESTAMP NOT NULL, window_end TIMESTAMP NOT NULL, fetched_at TIMESTAMP NOT NULL, request_url STRING NOT NULL, request_parameters STRING NOT NULL, http_status INT64 NOT NULL, content_type STRING NOT NULL, response_bytes INT64 NOT NULL, sha256 STRING NOT NULL, response_record_count INT64 NOT NULL, window_record_count INT64 NOT NULL, raw_body STRING NOT NULL, loaded_at TIMESTAMP NOT NULL",
        f"{SILVER}.huggingface_model_releases": "source_id STRING NOT NULL, source_published_at TIMESTAMP NOT NULL, observed_at TIMESTAMP NOT NULL, author STRING, canonical_url STRING NOT NULL, pipeline_tag STRING, has_usable_artifact BOOL NOT NULL, has_usable_config BOOL NOT NULL, qualifies BOOL NOT NULL, exclusion_reason STRING, source_metadata STRING NOT NULL, bronze_run_id STRING NOT NULL, bronze_page_number INT64 NOT NULL, source_record_index INT64 NOT NULL, processed_at TIMESTAMP NOT NULL, transform_version STRING NOT NULL",
        f"{SILVER}.arxiv_paper_submissions": "source_id STRING NOT NULL, arxiv_version STRING NOT NULL, source_published_at TIMESTAMP NOT NULL, source_updated_at TIMESTAMP NOT NULL, observed_at TIMESTAMP NOT NULL, title STRING NOT NULL, summary STRING NOT NULL, authors_json STRING NOT NULL, categories_json STRING NOT NULL, canonical_url STRING NOT NULL, source_metadata STRING NOT NULL, bronze_run_id STRING NOT NULL, bronze_page_number INT64 NOT NULL, source_record_index INT64 NOT NULL, processed_at TIMESTAMP NOT NULL, transform_version STRING NOT NULL",
        f"{SILVER}.transform_runs": "run_id STRING NOT NULL, source STRING NOT NULL, parsed_count INT64 NOT NULL, inserted_count INT64 NOT NULL, duplicate_count INT64 NOT NULL, qualified_count INT64 NOT NULL, status STRING NOT NULL, processed_at TIMESTAMP NOT NULL, transform_version STRING NOT NULL",
        f"{GOLD}.radar_items": "source STRING NOT NULL, source_id STRING NOT NULL, radar_date DATE NOT NULL, source_published_at TIMESTAMP NOT NULL, title STRING NOT NULL, summary STRING, canonical_url STRING NOT NULL, author_or_org STRING, source_metadata STRING NOT NULL, observed_at TIMESTAMP NOT NULL, bronze_run_id STRING NOT NULL, bronze_page_number INT64 NOT NULL, source_record_index INT64 NOT NULL, processed_at TIMESTAMP NOT NULL, transform_version STRING NOT NULL",
        f"{GOLD}.daily_source_metrics": "metric_date DATE NOT NULL, run_id STRING NOT NULL, source STRING NOT NULL, window_start TIMESTAMP NOT NULL, window_end TIMESTAMP NOT NULL, source_status STRING NOT NULL, raw_page_count INT64 NOT NULL, raw_response_record_count INT64, raw_window_record_count INT64, silver_parsed_count INT64 NOT NULL, silver_inserted_count INT64 NOT NULL, silver_duplicate_count INT64 NOT NULL, silver_qualified_count INT64 NOT NULL, gold_item_count INT64 NOT NULL, processed_at TIMESTAMP NOT NULL, transform_version STRING NOT NULL",
    }
    for table, fields in schema.items():
        partition = "run_started_at" if table.endswith("fetch_runs") else "fetched_at" if table.endswith("_raw") else "processed_at" if table.endswith("transform_runs") else "source_published_at" if ".mrr_silver" in f".{table}" else "radar_date" if table.endswith("radar_items") else "metric_date" if table.endswith("daily_source_metrics") else "processed_at"
        expression = partition if partition in {"radar_date", "metric_date"} else f"DATE({partition})"
        query(f"CREATE TABLE IF NOT EXISTS `{PROJECT_ID}.{table}` ({fields}) PARTITION BY {expression}")
    print(f"ready: {BRONZE}, {SILVER}, {GOLD}, {ASSERTIONS} in US")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
