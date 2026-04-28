# crochet-pattern-agent

`crochet-pattern-agent` is a subscriber-driven crochet recommendation system with a Flask web app, scheduler, and personalized report generation pipeline.

It includes:
- a preference form and admin interface
- a SQLite subscriber database
- a multi-step recommendation pipeline
- a weekly competition intelligence pipeline
- email delivery or dry-run email preview

## Competition Intelligence Agent

The repo now includes a `Competition Intelligence Agent` for StitchFlow Labs. It:

- researches crochet competitors across Etsy, Ravelry, YouTube, and blogs
- identifies weekly crochet trends and seasonal demand signals
- generates high-intent keywords and product-buying signals
- writes structured outputs to `intel/latest/`
- stores each weekly snapshot in SQLite for reuse by the recommendation pipeline

Artifacts written on refresh:

- `trends.json`
- `competitors.json`
- `opportunities.json`
- `keywords.json`

Stable handoff path for `affiliate-supervisor`:

- `C:\Users\trenp\crochet-pattern-agent\intel\latest\`

If `COMPETITION_INTEL_DIR` points somewhere else, such as `.tmp\intel`, the agent now still syncs the latest JSON artifacts to `intel\latest` for downstream readers.

The scheduler now attempts a weekly intelligence refresh before subscriber recommendation runs.

## Pilot Go-Live Status

- Admin routes are locked behind `ADMIN_PASSWORD` and fail closed when that secret is missing in production.
- Scheduler runs are protected against overlap and now enforce a per-subscriber 14-day due check.
- `EMAIL_DRY_RUN` remains the default so pilot validation can happen without live sending.
- SQLite is acceptable for a small pilot only.
- Postgres is recommended before a larger public launch or any higher-concurrency rollout.

Quick start guide:
[HOW_TO_RUN.md](/C:/Users/trenp/crochet-pattern-agent/docs/HOW_TO_RUN.md)

Production runbook:
[DEPLOYMENT_RUNBOOK.md](/C:/Users/trenp/crochet-pattern-agent/docs/DEPLOYMENT_RUNBOOK.md)

Controlled live-fire checklist:
[LIVE_FIRE_TEST_CHECKLIST.md](/C:/Users/trenp/crochet-pattern-agent/docs/LIVE_FIRE_TEST_CHECKLIST.md)
