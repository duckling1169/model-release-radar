#!/usr/bin/env python3
"""M4's manually invoked production collector and Dataform hand-off."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime

from google.cloud import bigquery
from google.auth import default
from google.auth.transport.requests import AuthorizedSession

import arxiv_normalize
import sources

PROJECT_ID = "project-90394262-994e-4667-90d"
LOCATION = "US"
BRONZE, SILVER = "mrr_bronze", "mrr_silver"
MAX_STORAGE_BYTES = 5 * 1024**3
MAX_MONTHLY_QUERY_BYTES = 900 * 1024**3
TRANSFORM_VERSION = "m4-v1"


def now_z() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_window(start: str, end: str) -> tuple[datetime, datetime]:
    parsed_start, parsed_end = sources.parse_utc(start), sources.parse_utc(end)
    if parsed_start >= parsed_end:
        raise ValueError("--start must be earlier than --end")
    sources.ensure_recent_window(sources.RunWindow(parsed_start, parsed_end), sources.utc_now())
    return parsed_start, parsed_end


def storage_guard(client: bigquery.Client) -> None:
    # TABLE_STORAGE metadata requires a project setting whose history can take
    # a day to initialize. The API exposes current logical table size now,
    # without granting the collector any table-data read permission.
    used = 0
    for dataset in client.list_datasets(project=PROJECT_ID):
        for table in client.list_tables(dataset.reference):
            used += client.get_table(table.reference).num_bytes or 0
    if used >= MAX_STORAGE_BYTES:
        raise RuntimeError(f"storage guard: {used} bytes already meets 5 GiB limit")


def monthly_query_guard(client: bigquery.Client) -> None:
    """Keep the project below its chosen 900 GiB calendar-month query budget."""
    sql = """SELECT COALESCE(SUM(total_bytes_billed), 0) AS bytes
      FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
      WHERE DATE(creation_time, 'UTC') >= DATE_TRUNC(CURRENT_DATE('UTC'), MONTH)
        AND job_type = 'QUERY' AND state = 'DONE'"""
    used = int(next(iter(client.query(sql, location=LOCATION).result())).bytes)
    if used >= MAX_MONTHLY_QUERY_BYTES:
        raise RuntimeError(f"query guard: {used} billed bytes already meets 900 GiB monthly limit")


def load_rows(client: bigquery.Client, table: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    job = client.load_table_from_json(rows, f"{PROJECT_ID}.{table}", location=LOCATION)
    job.result()


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def bronze_rows(run_dir: Path, run_id: str, source: str, loaded_at: str) -> list[dict[str, object]]:
    run_manifest = read_json(run_dir / "run_manifest.json")
    source_manifest = read_json(run_dir / source / "manifest.json")
    window = dict(run_manifest["window"])
    rows = []
    for page in source_manifest.get("pages", []):
        page = dict(page)
        body = (run_dir / source / str(page["filename"])).read_text(encoding="utf-8")
        rows.append({"run_id": run_id, "page_number": page["page_number"], "window_start": window["start"], "window_end": window["end"], "fetched_at": page["fetched_at"], "request_url": page["request_url"], "request_parameters": json.dumps(page["request_parameters"], sort_keys=True), "http_status": page["http_status"], "content_type": page["content_type"], "response_bytes": page["response_bytes"], "sha256": page["sha256"], "response_record_count": page["response_record_count"], "window_record_count": page["window_record_count"], "raw_body": body, "loaded_at": loaded_at})
    return rows


def load_bronze(client: bigquery.Client, run_dir: Path) -> dict[str, object]:
    manifest = read_json(run_dir / "run_manifest.json")
    run_id, loaded_at, window = str(manifest["run_id"]), now_z(), dict(manifest["window"])
    for source, table in (("huggingface", "huggingface_responses_raw"), ("arxiv", "arxiv_responses_raw")):
        load_rows(client, f"{BRONZE}.{table}", bronze_rows(run_dir, run_id, source, loaded_at))
    fetches = []
    for source, details in dict(manifest["sources"]).items():
        details = dict(details)
        fetches.append({"run_id": run_id, "source": source, "overall_status": manifest["status"], "source_status": details["status"], "window_start": window["start"], "window_end": window["end"], "run_started_at": manifest["started_at"], "run_finished_at": manifest["finished_at"], "page_count": len(details.get("pages", [])), "response_record_count": details.get("response_record_count"), "window_record_count": details.get("window_record_count"), "error": details.get("error"), "manifest_json": json.dumps(details, sort_keys=True), "loaded_at": loaded_at})
    load_rows(client, f"{BRONZE}.fetch_runs", fetches)
    return manifest


def normalize_arxiv(client: bigquery.Client, manifest: dict[str, object], run_dir: Path) -> None:
    run_id, processed_at = str(manifest["run_id"]), now_z()
    pages = bronze_rows(run_dir, run_id, "arxiv", processed_at)
    rows = arxiv_normalize.arxiv_rows(pages, processed_at)
    existing_sql = f"SELECT source_id FROM `{PROJECT_ID}.{SILVER}.arxiv_paper_submissions` WHERE source_id IN UNNEST(@ids)"
    ids = [str(row["source_id"]) for row in rows]
    existing = {row.source_id for row in client.query(existing_sql, job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", ids)]), location=LOCATION).result()} if ids else set()
    inserted = [row for row in rows if row["source_id"] not in existing]
    load_rows(client, f"{SILVER}.arxiv_paper_submissions", inserted)
    load_rows(client, f"{SILVER}.transform_runs", [{"run_id": run_id, "source": "arxiv", "parsed_count": len(rows), "inserted_count": len(inserted), "duplicate_count": len(rows) - len(inserted), "qualified_count": len(rows), "status": "succeeded", "processed_at": processed_at, "transform_version": TRANSFORM_VERSION}])


def invoke_dataform(run_id: str) -> None:
    repository = os.environ["DATAFORM_REPOSITORY"]
    credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    base = f"https://dataform.googleapis.com/v1/projects/{PROJECT_ID}/locations/us-east5/repositories/{repository}"
    compilation = session.post(f"{base}/compilationResults", json={"gitCommitish": "main", "codeCompilationConfig": {"vars": {"run_id": run_id}}}, timeout=30)
    compilation.raise_for_status()
    invocation = session.post(f"{base}/workflowInvocations", json={"compilationResult": compilation.json()["name"]}, timeout=30)
    invocation.raise_for_status()
    name = invocation.json()["name"]
    while True:
        current = session.get(f"https://dataform.googleapis.com/v1/{name}", timeout=30)
        current.raise_for_status()
        state = current.json().get("state")
        if state == "SUCCEEDED":
            return
        if state in {"FAILED", "CANCELLED"}:
            raise RuntimeError(f"Dataform workflow {state}: {name}")
        import time
        time.sleep(5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args(argv)
    parse_window(args.start, args.end)
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    storage_guard(client)
    monthly_query_guard(client)
    with tempfile.TemporaryDirectory(prefix="mrr-") as directory:
        run_root = Path(directory) / "raw"
        exit_code = sources.main(["--start", args.start, "--end", args.end, "--output-dir", str(run_root)])
        run_dirs = list(run_root.iterdir())
        if len(run_dirs) != 1:
            raise RuntimeError("collector did not create exactly one run directory")
        manifest = load_bronze(client, run_dirs[0])
        if exit_code != 0 or manifest["status"] != "succeeded":
            raise RuntimeError(f"incomplete source capture retained in Bronze: {manifest['run_id']}")
        normalize_arxiv(client, manifest, run_dirs[0])
        invoke_dataform(str(manifest["run_id"]))
        print(f"completed official run: {manifest['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
