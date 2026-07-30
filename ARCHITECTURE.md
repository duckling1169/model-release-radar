# Architecture

## System boundary

A dashboard showing daily AI model releases and first-submission AI papers. Currently: a Vercel browser UI and read-only API over official BigQuery Gold, plus a scheduled production medallion pipeline. No end users besides the maintainer and anyone viewing the public dashboard.

## Components

| Component | Responsibility | Depends on |
|---|---|---|
| `index.html` / `styles.css` / `script.js` | Dashboard UI, live snapshot rendering, unavailable state, light/dark theme | Same-origin `/api/radar` |
| `api/radar.js` | Cached, bounded dashboard snapshot adapter | Vercel OIDC, official BigQuery Gold |
| `pipeline/` | Production source capture, arXiv normalization, and Dataform hand-off | Cloud Run Job, BigQuery, Dataform |
| Cloud Run Job `mrr-production-ingest` | Explicit-window production capture, official Bronze load, arXiv Silver normalization, and Dataform invocation | `mrr-pipeline-runner`, BigQuery, Dataform |
| Cloud Scheduler + Workflows | Daily UTC scheduling, explicit-window Job invocation, Gold-health verification, and structured failure logging | `mrr-scheduler-invoker`, `mrr-workflow-runner`, Cloud Run, BigQuery |
| Dataform repository `mrr-production` | Hugging Face Silver transform, quality assertions, and Gold materialization | `mrr-dataform-runner`, Developer Connect GitHub repository connection |
| GitHub (`duckling1169/model-release-radar`) | Source of truth | — |
| Vercel (`adam-behrmans-projects/model-release-radar`) | Hosts the dashboard and same-origin read API, auto-deploys on push to `main` | GitHub repo, GCP federation |
| GCP project `Model Release Radar` (`project-90394262-994e-4667-90d`) | Hosts disposable validation data, official BigQuery medallion datasets, manual ingestion, and keyless reader/pipeline identities | GCP billing account `My Billing Account` |

## Data and control flow

The scheduled production flow is `Cloud Scheduler → Workflows → Cloud Run Job (explicit UTC window) → official Bronze + arXiv Silver → Dataform (Hugging Face Silver, assertions, Gold)`. Scheduler runs ingestion at 00:20 UTC for the preceding completed UTC day and runs an independent Gold health check at 01:00 UTC. The Job retains successful Bronze captures when either source fails and does not invoke Dataform for a partial source run. The two sources are new public Hugging Face model repositories and first arXiv submissions in `cs.AI`, `cs.CL`, and `cs.LG`. GitHub is out of scope as a data source.

Bronze holds immutable, page-level source responses and fetch manifests. Silver holds source-specific normalized, validated, deduplicated records and filter outcomes. Gold holds materialized, date-partitioned dashboard items and daily source metrics. All three layers are official append-only datasets in the BigQuery `US` multi-region.

## Contracts and invariants

- Everything on the GCP side must stay within Always Free tier quotas — no paid tier usage expected at this project's scale.
- Official Bronze records are append-only and source-faithful; every downstream record retains run/source lineage and a transform version.
- Official `mrr_bronze`, `mrr_silver`, and `mrr_gold` are append-only and have no expiry; no production reset command exists.
- The production job uses temporary local NDJSON and BigQuery batch loads—there is no pipeline Cloud Storage staging bucket or streaming insert. Its 5 GiB BigQuery-storage and 900 GiB calendar-month query guards run before collection.
- Dataform executes as `mrr-dataform-runner`; the Cloud Run Job executes as `mrr-pipeline-runner`; Workflows executes as `mrr-workflow-runner`; Scheduler can only start Workflows as `mrr-scheduler-invoker`. Neither pipeline identity has Vercel-reader permissions. Gemini classification and a Cloud Run dashboard API remain deferred.
- No control-plane component retries a whole Job execution. Workflow failure and missing valid Gold snapshots emit log-based email alerts.
- The Vercel API uses a dedicated service account, `mrr-vercel-radar-reader`, with project-level BigQuery job creation and read-only access to `mrr_gold` only. It receives no long-lived key: the `mrr-vercel` workload identity pool accepts only the `adam-behrmans-projects/model-release-radar` production Vercel OIDC subject.

## Decisions

- 2026-07-29 — Reused the auto-provisioned "My First Project" (renamed to `Model Release Radar`) instead of a freshly created project, since it already had billing linked. Project ID stays the generic `project-90394262-994e-4667-90d`; only the display name changed.
- 2026-07-29 — Deleted 9 unrelated old GCP projects (chroma, ChromaEarTrainer, DrawingChatApp, FatefulChatApp, FinanceTool, FIRE, MedievalKingdomsIdle, SaaSIdea1, Theseus) to reduce clutter. Recoverable via `gcloud projects undelete` for ~30 days if needed.
- 2026-07-29 — Left the auto-provisioned Cloud Identity org (`adamrbehrman-org`) in place rather than attempting to delete it — it holds the project, costs nothing, and deleting it requires an unrelated offboarding process through admin.google.com.
- 2026-07-29 — Built the dashboard as a standalone static site first (no backend), deployed to Vercel, so it's demoable before any GCP pipeline exists.
- 2026-07-29 — Defined a two-source medallion design: immutable Bronze source pages, source-specific Silver normalization, and materialized Gold dashboard snapshots. This replaces the earlier GitHub/flat raw-to-modeled plan; scheduling, Dataform orchestration, and classification remain deferred.
- 2026-07-29 — Implemented and validated the manual M2 path in disposable `US` BigQuery datasets only. Silver XML parsing is local Python for this milestone; a later native-GCP/Dataform strategy remains an explicit future decision.
- 2026-07-29 — Added M3's cached Vercel read adapter over dev Gold. It uses workload identity federation rather than a service-account key and intentionally serves no partial run; a later Cloud Run service can replace the adapter without changing the browser's `/api/radar` contract.
- 2026-07-29 — Added M4's official append-only datasets, private explicit-window Cloud Run Job, Dataform action graph, and isolated pipeline/Dataform identities. After a manually inspected successful two-source run, the dashboard now reads official Gold.
- 2026-07-30 — Added M5's Scheduler-to-Workflows control plane, separate least-privilege Scheduler and Workflow identities, daily Gold health verification, and log-based email alerts. After successful end-to-end and safe failure-path validation, retired the disposable dev datasets, scripts, and fixtures.
