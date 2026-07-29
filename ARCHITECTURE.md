# Architecture

## System boundary

A dashboard showing daily AI model/paper releases. Currently: a static front end only. Planned: a GCP-hosted ingest → transform → classify pipeline feeding it live data. No end users besides the maintainer and anyone viewing the public dashboard.

## Components

| Component | Responsibility | Depends on |
|---|---|---|
| `index.html` / `styles.css` / `script.js` | Dashboard UI, currently placeholder data, light/dark theme | — |
| GitHub (`duckling1169/model-release-radar`) | Source of truth | — |
| Vercel (`adam-behrmans-projects/model-release-radar`) | Hosts the static dashboard, auto-deploys on push to `main` | GitHub repo |
| GCP project `Model Release Radar` (`project-90394262-994e-4667-90d`) | Will host ingest (Cloud Run), raw/modeled storage (BigQuery + Dataform), classification (Gemini API), and scheduling (Cloud Scheduler) | GCP billing account `My Billing Account` |

## Data and control flow

Not yet built. Planned: `Cloud Scheduler → Cloud Run (ingest from HuggingFace/arXiv/GitHub) → BigQuery (raw) → Dataform (transform) → BigQuery (modeled) → Gemini API (classify/tag) → dashboard reads modeled+classified data`.

## Contracts and invariants

- Everything on the GCP side must stay within Always Free tier quotas — no paid tier usage expected at this project's scale.

## Decisions

- 2026-07-29 — Reused the auto-provisioned "My First Project" (renamed to `Model Release Radar`) instead of a freshly created project, since it already had billing linked. Project ID stays the generic `project-90394262-994e-4667-90d`; only the display name changed.
- 2026-07-29 — Deleted 9 unrelated old GCP projects (chroma, ChromaEarTrainer, DrawingChatApp, FatefulChatApp, FinanceTool, FIRE, MedievalKingdomsIdle, SaaSIdea1, Theseus) to reduce clutter. Recoverable via `gcloud projects undelete` for ~30 days if needed.
- 2026-07-29 — Left the auto-provisioned Cloud Identity org (`adamrbehrman-org`) in place rather than attempting to delete it — it holds the project, costs nothing, and deleting it requires an unrelated offboarding process through admin.google.com.
- 2026-07-29 — Built the dashboard as a standalone static site first (no backend), deployed to Vercel, so it's demoable before any GCP pipeline exists.
