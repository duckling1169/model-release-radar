# Model Release Radar

[![CI](https://github.com/duckling1169/model-release-radar/actions/workflows/ci.yml/badge.svg)](https://github.com/duckling1169/model-release-radar/actions/workflows/ci.yml)

A daily dashboard of new public Hugging Face models and first-submission AI papers on
arXiv, built on a medallion data pipeline in BigQuery that runs inside Google Cloud's
free tier. Live at **https://model-release-radar.vercel.app**.

The dashboard shows the pipeline's own numbers next to the feed (raw, qualified and
displayed counts per source, plus freshness), so filtering is visible rather than silent.

## Sources

| Source | Included | Excluded |
| --- | --- | --- |
| Hugging Face | Newly created public model repositories | Updates to existing repos; private repos |
| arXiv | Papers first announced in `cs.AI`, `cs.CL`, `cs.LG` (new and cross-listed) | Revisions; every other category |

A Hugging Face model reaches the dashboard only if it declares a task (`pipeline_tag`) or
ships a usable model artifact or config. Excluded records stay in Silver with a reason.

arXiv is read from its daily announcement feed, one request a run, so each day shows
exactly what arXiv announced. Weekends and holidays have no announcement and show none.

## How it works

```
Cloud Scheduler (07:20 UTC) → Workflows → Cloud Run Job: collect yesterday (UTC)
  → Bronze: raw source pages, append-only, kept for 90 days
  → Silver: arXiv normalized in Python; Hugging Face normalized in Dataform
  → Gold: Dataform materializes dashboard items and daily metrics, with assertions
  → Optional Gemini enrichment: tags and a short explanation, stored outside Gold
Vercel: static dashboard + /api/radar, reading the newest complete Gold snapshot
Cloud Scheduler (08:00 UTC) → health check; failures alert by email
```

- **Bronze** keeps every source response exactly as received (JSON or Atom XML) with a
  fetch manifest. **Silver** holds normalized, deduplicated records keyed by
  `(source, source_id)`. **Gold** holds date-partitioned dashboard snapshots. Every
  Silver and Gold row carries its run ID and transform version, so any item traces back
  to its source page.
- A run covers one explicit UTC window. If either source fails, the run is incomplete:
  successful captures are kept, and Gold isn't rebuilt from partial data.
- Enrichment uses the Gemini API's free allowance (20 requests a day). Hitting the quota
  ends the job cleanly with a backlog; it can never rank, filter or delay the feed.
- Each component runs as its own least-privilege service account. The Vercel API holds no
  key: it authenticates with Vercel OIDC through workload identity federation and can only
  read Gold and enrichment results.
- Storage and query guards run before collection to stay inside free-tier limits.

## Layout

| Path | Contents |
| --- | --- |
| `public/` | Dashboard (plain HTML, CSS, JS) |
| `api/radar.js` | Vercel function: cached, read-only snapshot over Gold |
| `pipeline/` | Cloud Run jobs: collection (`run_job.py`) and enrichment (`enrich_job.py`) |
| `definitions/`, `workflow_settings.yaml` | Dataform: Hugging Face Silver, Gold and assertions |
| `workflows/` | Cloud Workflows for daily ingest and health check |
| `infra/` | BigQuery dataset setup and a custom IAM role |
| `tests/` | Python (`unittest`) and Node (`node:test`) tests |

## Develop

```bash
python3 -m http.server 8000 --directory public   # dashboard (no build step)
uv run --with-requirements pipeline/requirements.txt python -m unittest discover -s tests
npm test
```

## License

[MIT](LICENSE)
