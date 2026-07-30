#!/usr/bin/env python3
"""M6's bounded, append-only Gemini enrichment worker.

It reads only modeled public Gold fields, never blocks source ingestion, and
stops cleanly at its free-tier request cap.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from google.cloud import bigquery, secretmanager


PROJECT_ID = "project-90394262-994e-4667-90d"
LOCATION = "US"
GOLD, ENRICHMENT = "mrr_gold", "mrr_enrichment"
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
PROMPT_VERSION = "m6-v1"
DAILY_REQUEST_CAP = int(os.environ.get("GEMINI_DAILY_REQUEST_CAP", "20"))
MIN_REQUEST_INTERVAL_SECONDS = 7
SECRET_RESOURCE = os.environ.get(
    "GEMINI_SECRET_RESOURCE",
    f"projects/{PROJECT_ID}/secrets/mrr-gemini-api-key/versions/latest",
)
MAXIMUM_BYTES_BILLED = 1_073_741_824
TAXONOMY = (
    "language", "vision", "audio", "multimodal", "code", "embedding", "agents",
    "robotics", "science", "safety", "infrastructure", "other",
)
TERMINAL_STATUSES = ("succeeded", "insufficient_source_detail")


def now_z() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def timestamp_z(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return str(value)


def json_safe(value: object) -> object:
    """Convert BigQuery-native values to JSON values before streaming a row."""
    if isinstance(value, datetime):
        return timestamp_z(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def bounded(value: object, limit: int) -> str:
    """Normalize public source text and bound the request payload."""
    return " ".join(str(value or "").split())[:limit]


def selected_metadata(source: str, source_metadata: object) -> dict[str, object]:
    """Extract only approved metadata; never forward the raw metadata blob."""
    try:
        metadata = json.loads(str(source_metadata or "{}"))
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        return {}
    if source == "huggingface":
        return {"pipeline_tag": bounded(metadata.get("pipeline_tag"), 120)}
    categories = metadata.get("categories") or metadata.get("category") or []
    if isinstance(categories, str):
        categories = [categories]
    return {"arxiv_categories": [bounded(category, 60) for category in categories[:12] if bounded(category, 60)]}


def approved_input(item: dict[str, object]) -> dict[str, object]:
    return {
        "source": bounded(item["source"], 30),
        "source_id": bounded(item["source_id"], 300),
        "title": bounded(item.get("title"), 500),
        "summary_or_abstract": bounded(item.get("summary"), 3000),
        "author_or_org": bounded(item.get("author_or_org"), 500),
        "source_url": bounded(item.get("canonical_url"), 2000),
        "selected_metadata": selected_metadata(str(item["source"]), item.get("source_metadata")),
    }


def input_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def request_body(payload: dict[str, object]) -> dict[str, object]:
    instruction = (
        "Classify this public AI release using only the supplied source fields. "
        f"Choose at most three tags from: {', '.join(TAXONOMY)}. "
        "Write one plain-language, source-grounded sentence of at most 240 characters. "
        "Do not claim performance, safety, capability, or intent not supported by the input. "
        "If the source is too thin, return status insufficient_source_detail with empty tags and null explanation."
    )
    return {
        "systemInstruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, sort_keys=True)}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                    "explanation": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": ["succeeded", "insufficient_source_detail"]},
                },
                "required": ["tags", "explanation", "status"],
            },
        },
    }


def validate_response(value: object) -> tuple[list[str], str | None, str]:
    if not isinstance(value, dict):
        raise ValueError("response is not an object")
    tags, explanation, status = value.get("tags"), value.get("explanation"), value.get("status")
    if status not in TERMINAL_STATUSES or not isinstance(tags, list) or len(tags) > 3:
        raise ValueError("invalid response status or tags")
    if any(tag not in TAXONOMY for tag in tags) or len(set(tags)) != len(tags):
        raise ValueError("response used a tag outside the controlled taxonomy")
    if status == "insufficient_source_detail":
        if tags or explanation not in (None, ""):
            raise ValueError("insufficient detail response must not invent enrichment")
        return [], None, status
    if not isinstance(explanation, str) or not explanation.strip() or len(explanation) > 240:
        raise ValueError("invalid explanation")
    return tags, explanation.strip(), status


class QuotaExhausted(RuntimeError):
    pass


def call_gemini(api_key: str, payload: dict[str, object], *, post=requests.post) -> tuple[list[str], str | None, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent?key={api_key}"
    for attempt in range(3):
        response = post(url, json=request_body(payload), timeout=30)
        # Every 429 is a rate/quota boundary. Never call raise_for_status here:
        # requests includes the full URL (and its API key) in that exception.
        if response.status_code == 429:
            raise QuotaExhausted("Gemini free-tier quota reached")
        if response.status_code == 403 and "quota" in response.text.lower():
            raise QuotaExhausted("Gemini free-tier quota reached")
        if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        if not response.ok:
            raise RuntimeError(f"Gemini HTTP {response.status_code}")
        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return validate_response(json.loads(text))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid structured Gemini response: {error}") from error
    raise RuntimeError("unreachable retry state")


def query(client: bigquery.Client, sql: str, parameters: list[bigquery.ScalarQueryParameter] | None = None) -> list[dict[str, object]]:
    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        query_parameters=parameters or [],
    )
    return [dict(row.items()) for row in client.query(sql, job_config=config, location=LOCATION).result()]


def latest_complete_run(client: bigquery.Client) -> str | None:
    sql = f"""SELECT run_id FROM `{PROJECT_ID}.{GOLD}.daily_source_metrics`
      GROUP BY run_id HAVING COUNT(DISTINCT source) = 2 AND COUNTIF(source_status = 'succeeded') = 2
      ORDER BY MAX(processed_at) DESC LIMIT 1"""
    rows = query(client, sql)
    return str(rows[0]["run_id"]) if rows else None


def candidate_sql(order: str, limit: int, current_only: bool) -> str:
    current_filter = "AND item.bronze_run_id = @gold_run_id" if current_only else "AND item.bronze_run_id != @gold_run_id"
    return f"""
      WITH history AS (
        SELECT source, source_id,
          COUNTIF(status IN UNNEST(@terminal_statuses)) > 0 AS terminal,
          MAX(created_at) AS last_attempt
        FROM `{PROJECT_ID}.{ENRICHMENT}.item_enrichments`
        GROUP BY source, source_id
      )
      SELECT item.source, item.source_id, item.bronze_run_id, item.source_published_at,
        item.title, item.summary, item.canonical_url, item.author_or_org, item.source_metadata,
        COALESCE((SELECT COUNT(*) FROM `{PROJECT_ID}.{ENRICHMENT}.item_enrichments` attempt
          WHERE attempt.source = item.source AND attempt.source_id = item.source_id), 0) + 1 AS attempt_number
      FROM `{PROJECT_ID}.{GOLD}.radar_items` item
      LEFT JOIN history USING (source, source_id)
      WHERE NOT COALESCE(terminal, FALSE)
        AND (last_attempt IS NULL OR last_attempt < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR))
        {current_filter}
      ORDER BY item.source_published_at {order}, item.source, item.source_id
      LIMIT {limit}"""


def candidates(client: bigquery.Client, gold_run_id: str, cap: int) -> tuple[list[dict[str, object]], int, int]:
    newest_cap = (cap * 80 + 99) // 100
    parameters = [
        bigquery.ScalarQueryParameter("gold_run_id", "STRING", gold_run_id),
        bigquery.ArrayQueryParameter("terminal_statuses", "STRING", list(TERMINAL_STATUSES)),
    ]
    newest = query(client, candidate_sql("DESC", newest_cap, True), parameters)
    backlog = query(client, candidate_sql("ASC", cap - len(newest), False), parameters)
    seen = {(row["source"], row["source_id"]) for row in newest}
    combined = newest + [row for row in backlog if (row["source"], row["source_id"]) not in seen]
    if len(combined) < cap:
        fill = query(client, candidate_sql("ASC", cap, True), parameters)
        seen = {(row["source"], row["source_id"]) for row in combined}
        for row in fill:
            identity = (row["source"], row["source_id"])
            if identity not in seen and len(combined) < cap:
                combined.append(row)
                seen.add(identity)
    return combined[:cap], len(newest), len(backlog)


def load_row(client: bigquery.Client, table: str, row: dict[str, object]) -> None:
    # The BigQuery client serializes this payload itself. Candidate rows can
    # contain native datetime values, which must not reach that JSON boundary.
    errors = client.insert_rows_json(f"{PROJECT_ID}.{ENRICHMENT}.{table}", [json_safe(row)])
    if errors:
        raise RuntimeError(f"BigQuery insert into {table} failed: {errors}")


def api_key() -> str:
    response = secretmanager.SecretManagerServiceClient().access_secret_version(name=SECRET_RESOURCE)
    return response.payload.data.decode("utf-8").strip()


def main() -> int:
    if DAILY_REQUEST_CAP < 1 or DAILY_REQUEST_CAP > 20:
        raise ValueError("GEMINI_DAILY_REQUEST_CAP must be between 1 and 20")
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    run_id, started_at = f"enrich_{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}", now_z()
    gold_run_id: str | None = None
    newest_count = backlog_count = attempted = succeeded = insufficient = failed = 0
    quota_exhausted = False
    final_status, final_error = "failed", None
    try:
        gold_run_id = latest_complete_run(client)
        if not gold_run_id:
            final_status = "succeeded"
            return 0
        selected, newest_count, backlog_count = candidates(client, gold_run_id, DAILY_REQUEST_CAP)
        key = api_key() if selected else ""
        for index, item in enumerate(selected):
            if index:
                # The confirmed free quota is 10 RPM. Seven seconds leaves
                # slack for network variation and keeps the Job below it.
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS)
            attempted += 1
            payload = approved_input(item)
            result: dict[str, object] = {
                "enrichment_id": uuid.uuid4().hex,
                "enrichment_run_id": run_id,
                "source": item["source"], "source_id": item["source_id"], "gold_run_id": item["bronze_run_id"],
                "model_id": MODEL_ID, "prompt_version": PROMPT_VERSION, "input_hash": input_hash(payload),
                "tags": [], "explanation": None, "status": "failed", "failure_reason": None,
                "attempt_number": item["attempt_number"], "source_published_at": timestamp_z(item["source_published_at"]), "created_at": now_z(),
            }
            try:
                tags, explanation, status = call_gemini(key, payload)
                result.update(tags=tags, explanation=explanation, status=status)
                if status == "succeeded":
                    succeeded += 1
                else:
                    insufficient += 1
            except QuotaExhausted as error:
                quota_exhausted, final_error = True, str(error)
                attempted -= 1
                break
            except Exception as error:  # Record an immutable failed attempt; continue within the cap.
                result["failure_reason"] = bounded(error, 500)
                failed += 1
            load_row(client, "item_enrichments", result)
        final_status = "succeeded_with_backlog" if quota_exhausted else "succeeded"
        return 0
    except Exception as error:
        final_error = bounded(error, 1000)
        raise
    finally:
        load_row(client, "enrichment_runs", {
            "enrichment_run_id": run_id, "gold_run_id": gold_run_id, "model_id": MODEL_ID,
            "prompt_version": PROMPT_VERSION, "started_at": started_at, "finished_at": now_z(),
            "daily_request_cap": DAILY_REQUEST_CAP, "newest_candidate_count": newest_count,
            "backlog_candidate_count": backlog_count, "attempted_count": attempted,
            "succeeded_count": succeeded, "insufficient_count": insufficient, "failed_count": failed,
            "quota_exhausted": quota_exhausted, "status": final_status, "error": final_error,
        })


if __name__ == "__main__":
    raise SystemExit(main())
