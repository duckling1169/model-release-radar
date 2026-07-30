# Model Release Radar

A daily-updated dashboard tracking new public Hugging Face model releases and first-submission AI papers from arXiv. It will show the pipeline's own numbers alongside the feed: raw, qualified, and displayed counts, plus reconciliation and freshness information.

This repo contains the Vercel-hosted dashboard and its same-origin read API. The UI fetches the newest fully successful snapshot from official BigQuery Gold data; it never receives Google Cloud credentials or queries BigQuery directly. It retains the working light/dark theme toggle.

## Data architecture

- **Sources:** Hugging Face (new public model repositories) and arXiv (first submissions in `cs.AI`, `cs.CL`, and `cs.LG`)
- **Storage/transform:** BigQuery Bronze (verbatim source capture) → Silver (source-specific normalization) → Gold (materialized dashboard data and metrics)
- **Production operation:** Cloud Scheduler starts a Workflow daily at 00:20 UTC; it invokes Cloud Run with the preceding completed UTC day, then Dataform makes Hugging Face Silver and Gold. A second Workflow verifies the complete two-source Gold snapshot at 01:00 UTC.
- **Optional context:** a separate, bounded Gemini job adds controlled tags and a short source-grounded explanation after a complete Gold snapshot; it never ranks, filters, or delays the feed
- **Dashboard:** Vercel serves the browser UI plus a short-lived-credential, read-only `/api/radar` adapter over Gold; Cloud Run remains a later production replacement behind the same browser contract

Everything on GCP is designed to remain within Always Free tier quotas. The full source, lineage, filtering, and layer contracts are in [DATA_CONTRACT.md](DATA_CONTRACT.md).

## Running locally

No build step — plain HTML/CSS/JS.

```
python3 -m http.server 8000
```

Then open `http://localhost:8000`.

The static server does not run `/api/radar`; the page deliberately shows its unavailable state locally. Deploy through Vercel to exercise the live API.

## Live dashboard API

`GET /api/radar` returns up to 50 newest Gold items and source metrics for the newest run that completed successfully for both sources. Each item may additionally contain nullable `enrichment: { tags, explanation }`; missing enrichment does not affect availability or ordering. It caches at Vercel for five minutes, permits one hour of stale-while-revalidate, and returns `503 {"status":"unavailable"}` rather than a mixed or partial run.

The function exchanges Vercel's production OIDC token for a short-lived identity. Its production environment needs `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_SERVICE_ACCOUNT_EMAIL`, `GCP_WORKLOAD_IDENTITY_POOL_ID`, and `GCP_WORKLOAD_IDENTITY_POOL_PROVIDER_ID`; no service-account key is used. Vercel project Security must use the team issuer mode for `adam-behrmans-projects`.

## Production operation (M5)

Official `mrr_bronze`, `mrr_silver`, and `mrr_gold` have no expiration. The private Job accepts no implicit "now" window; Workflows supplies explicit UTC bounds. The normal schedule is fully automated, but an authenticated maintainer can still manually invoke the Job when needed:

```
gcloud run jobs execute mrr-production-ingest --region=us-east5 --wait \
  --args=--start,2026-07-29T20:00:00Z,--end,2026-07-29T21:00:00Z
```

It first checks a 5 GiB BigQuery storage guard and a 900 GiB calendar-month query guard. Successful source capture is append-only in Bronze even if the later run fails. Dataform repository `mrr-production` is connected to this GitHub repository through Developer Connect. Scheduler and Workflows never retry a whole Job; Cloud Monitoring emails the maintainer for a Workflow failure or a missing valid two-source Gold snapshot.

## Optional Gemini enrichment (M6)

`mrr-production-enrich` is a separate Cloud Run Job started only after core ingestion has made Gold. It reads bounded, public Gold fields, writes immutable attempts and run records to `mrr_enrichment`, and leaves Bronze, Silver, Gold, and dashboard availability untouched on error or quota exhaustion. It uses Gemini Developer API free tier only, without grounding, with the verified free-tier cap of 20 requests per day and seven-second pacing below its 10 RPM limit. The dedicated API key lives only in Secret Manager and is readable only by the enrichment identity; do not place it in Git, Vercel, the browser, or logs. Free-tier submitted content may be used by Google to improve products, so only the documented public fields are sent. Model or prompt changes apply to future releases only; existing enrichment is not rewritten.

## Files

- `index.html` — page structure and content
- `styles.css` — theme variables (light/dark) and layout
- `script.js` — theme toggle, persisted via `localStorage`
