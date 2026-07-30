# Data Contract

This document is the implementation contract for the first real-data milestones. It defines what enters the radar, how source evidence is retained, and how raw data becomes a user-facing item.

## Scope

The radar has two sources:

| Source | Included records | Excluded records |
|---|---|---|
| Hugging Face | Newly created, public model repositories | Updates to existing repositories; private repositories |
| arXiv | First submissions in `cs.AI`, `cs.CL`, and `cs.LG` | Revisions of existing papers; `cs.CV` and all other categories |

GitHub is out of scope. The initial radar has no AI-generated notability score, rank, tag, or explanation.

## Collection window and identity

- Every collection run uses explicit UTC `start` and `end` timestamps. Convenience windows must resolve to those exact timestamps before collection begins.
- Source records are permanently deduplicated by `(source, source_id)`.
- Each record carries its source publication time when available, the time it was observed, and the collection `run_id`.
- A failed source makes a run incomplete. Successful source captures from that run are retained with their own status and manifest.

## Source-faithful capture

Raw capture is append-only and immutable. It preserves the response body exactly as received:

- Hugging Face responses are retained as JSON text.
- arXiv responses are retained as Atom XML text.

Each captured response page has its source, `run_id`, page number, request URL and parameters, response content type, HTTP status, fetch timestamp, requested window, record/page count, and response body. Local raw snapshots are Git-ignored; only small curated fixtures belong in version control.

## Medallion layers

All future BigQuery datasets use the `US` multi-region. Validation uses disposable `_dev` datasets; official data uses the equivalent names without `_dev`.

| Layer | Dataset | Contract |
|---|---|---|
| Bronze | `mrr_bronze` | Untouched, page-level source responses and fetch-run manifests. Never mutate or delete official records. |
| Silver | `mrr_silver` | Source-specific normalized records: `huggingface_model_releases` and `arxiv_paper_submissions`. Parse, validate, deduplicate, and record quality/filter outcomes here. |
| Gold | `mrr_gold` | Materialized, date-partitioned product snapshots: `radar_items` and `daily_source_metrics`. |

Silver and Gold records must retain the Bronze record/run identity, `processed_at`, and `transform_version` so every displayed item can be traced to its source evidence and rule set.

## Hugging Face qualification

Every newly created public Hugging Face model repository enters Bronze and is normalized in Silver. A record qualifies for Gold only when it has at least one of:

- a declared Hugging Face task (`pipeline_tag`); or
- a usable model artifact or configuration.

Records that do not qualify remain in Silver with an explicit exclusion reason. Gold metrics report raw, normalized, qualified, excluded, and displayed counts so filtering is visible rather than silent.

## Gold item contract

`radar_items` contains only the fields shared by the product across sources: source, source ID, publication time, title, summary, canonical URL, author or organization, observed time, source/run lineage, and source-specific metadata required for display. It is ordered deterministically by newest publication time; product-level ranking and AI judgments are deferred.

## Operating boundaries

The initial workflow is explicit: fetch, inspect, load Bronze, then transform Silver and Gold. There is no scheduler, Cloud Run workload, Cloud Storage staging bucket, Dataform orchestration, Gemini classification, or automated production load in these milestones.

After validation, only `mrr_bronze_dev`, `mrr_silver_dev`, and `mrr_gold_dev` may be removed through a confirmation-protected reset. The official datasets start empty at approved cutover and Bronze remains append-only thereafter.
