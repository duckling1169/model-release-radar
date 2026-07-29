# Model Release Radar

A daily-updated dashboard tracking new AI model releases and papers from HuggingFace, arXiv, and GitHub trending — with the pipeline's own numbers shown alongside it (raw vs. modeled row counts, reconciliation match rate, and the reasoning behind each notability tag).

This repo currently contains the static front end: a pixel-close, standalone implementation of the [Claude Design](https://claude.ai/design) mockup for the project, with a working light/dark theme toggle. It has no backend yet — all data shown is placeholder content matching the design.

## Stack (planned)

- **Ingest:** Cloud Run job pulling from the HuggingFace, arXiv, and GitHub APIs
- **Storage/transform:** BigQuery (raw) → Dataform (modeled)
- **Classification:** Gemini API, tagging releases as notable and explaining why
- **Scheduling:** Cloud Scheduler
- **Dashboard:** this site, eventually served from Cloud Run and reading live data

Everything is designed to run on GCP free-tier services.

## Running locally

No build step — plain HTML/CSS/JS.

```
python3 -m http.server 8000
```

Then open `http://localhost:8000`.

## Files

- `index.html` — page structure and content
- `styles.css` — theme variables (light/dark) and layout
- `script.js` — theme toggle, persisted via `localStorage`
