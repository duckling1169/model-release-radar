# Project instructions

See `README.md` for purpose and architecture.

## Commands

- Dashboard: `python3 -m http.server 8000 --directory public`
- Tests: `uv run --with-requirements pipeline/requirements.txt python -m unittest discover -s tests`
  and `npm test`
- Deploy: push to `main` (Vercel deploys the dashboard and API). Pipeline images are built
  with `gcloud builds submit --config pipeline/cloudbuild.yaml` (or `enrich_cloudbuild.yaml`).

## Rules

- GCP project ID: `project-90394262-994e-4667-90d` (it doesn't match the display name).
- Stay within Google Cloud's Always Free quotas. Check before enabling any new API or
  resource.
- Bronze, Silver and Gold are append-only; there is no production reset. Bronze raw pages
  expire after 90 days.
- Dataform reads this repo from GitHub: keep `workflow_settings.yaml`, `definitions/` and
  `package.json` at the root.
