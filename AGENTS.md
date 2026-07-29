# Project instructions

## Commands

- Run locally: `python3 -m http.server 8000` (no build step)
- Deploy: push to `main` (Vercel auto-deploys via the connected GitHub repo), or `vercel deploy --prod` for a manual deploy

## Non-inferable rules

- GCP project ID: `project-90394262-994e-4667-90d` (display name "Model Release Radar", org `adamrbehrman-org`). The project ID does not match the display name — don't assume it does when writing `gcloud` commands.
- Everything on GCP must stay within Always Free tier quotas. Check before enabling any API or resource type that isn't already covered in `ARCHITECTURE.md`.

## Completion requirements

- Report observable behavior changed and any unresolved risks.
- Update `ARCHITECTURE.md` only when a change makes it materially false — don't log routine progress there; Git history is the record.

## Read on demand

- `README.md`: purpose, setup, and normal use.
- `ARCHITECTURE.md`: before changing boundaries, contracts, or cross-component behavior (e.g. touching GCP resources).
