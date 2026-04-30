# crochet-pattern-agent

`crochet-pattern-agent` is a subscriber-driven crochet recommendation system with a Flask web app, scheduler, and personalized report generation pipeline.

It includes:
- a preference form and admin interface
- a SQLite subscriber database
- a multi-step recommendation pipeline
- a weekly competition intelligence pipeline
- email delivery or dry-run email preview

## LLM Provider Selection

The recommendation pipeline supports multiple providers through environment variables:

- `LLM_PROVIDER=anthropic`
  - requires `ANTHROPIC_API_KEY`
  - optional `ANTHROPIC_MODEL` (default: `claude-sonnet-4-6`)
- `LLM_PROVIDER=openai`
  - requires `OPENAI_API_KEY`
  - optional `OPENAI_MODEL` (default: `gpt-5-mini`)
- `LLM_PROVIDER=ollama`
  - uses `OLLAMA_BASE_URL` and `OLLAMA_MODEL`

The Render blueprint is now set up to prefer OpenAI by default.

## Email Provider Selection

Email delivery supports two providers:

- `EMAIL_PROVIDER=smtp`
  - keeps the existing SMTP/Gmail path available as a fallback
  - uses `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `SMTP_HOST`, `SMTP_PORT`, and `SMTP_USE_SSL`
  - not recommended for Render Free because outbound SMTP ports 25, 465, and 587 are blocked
- `EMAIL_PROVIDER=resend`
  - uses Resend over HTTPS
  - requires `RESEND_API_KEY`
  - requires `RESEND_FROM`, for example `StitchFlow Labs <patterns@stitchflowlabs.com>`

`EMAIL_DRY_RUN=true` means the app logs that it would send the report and does not call SMTP or Resend. Dry-run output is not a real email send.

### Resend Setup For Render

1. Create or log in to a Resend account.
2. Add `stitchflowlabs.com` as a sending domain in Resend.
3. Add the Resend DNS records in Porkbun.
4. Wait until Resend shows the domain as verified.
5. Create a Resend API key.
6. In Render, set these environment variables:

```text
EMAIL_PROVIDER=resend
RESEND_API_KEY=<your Render secret>
RESEND_FROM=StitchFlow Labs <patterns@stitchflowlabs.com>
EMAIL_DRY_RUN=true
```

Keep `EMAIL_DRY_RUN=true` for the first Render test. Use the admin dashboard's `Send Test (Dry Run)` button to verify report generation without sending email.

When the Resend domain is verified and the dry-run looks good, switch `EMAIL_DRY_RUN=false` only for a controlled selected-subscriber live test. Use `Send Test (Selected Only)` for Stephanie's subscriber row. Do not use `Run Now (All Users)` for the first live email test.

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
