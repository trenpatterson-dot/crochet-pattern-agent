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

- researches crochet competitors across websites, blogs, YouTube tutorials, Pinterest-style discovery, pattern platforms, beginner crochet tools, Etsy, and Ravelry
- evaluates competitors by beginner friction, not just pattern quantity or generic popularity
- identifies weekly crochet trends and seasonal demand signals
- generates high-intent keywords and product-buying signals
- writes structured outputs to `intel/latest/`
- stores each weekly snapshot in SQLite for reuse by the recommendation pipeline

Crochet Pattern Agent should compete by helping beginners who are tired of "easy" crochet patterns that are not actually easy. Competitor research must use these beginner pain points as the required rubric:

1. Splitting Yarn
2. The Magic Ring
3. Losing Stitches
4. Tension Issues
5. Pattern Language
6. Hand Pain
7. Yarn Selection Confusion
8. Left-Handed Frustration
9. The Finishing Gap
10. Project Overwhelm

Each competitor entry should include the competitor name/link, what they do well, beginner pain points addressed, beginner pain points missed, confusing parts of the beginner experience, opportunities for Crochet Pattern Agent, recommended feature/content ideas, and an overall beginner-friendliness score from 1-10. Do not make unsupported marketing claims; use visible public evidence and cautious wording.

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

## Pattern Trust Layer

The recommendation pipeline now adds lightweight pattern trust metadata before a report is returned. This layer is rules-based and does not claim that a pattern is verified, human-tested, or safe unless that evidence already exists in the pattern data.

Added metadata fields:

- `verified`
- `human_tested`
- `creator_attribution`
- `tutorial_available`
- `likely_ai_generated`
- `ai_risk_score`
- `ai_risk_label`
- `ai_risk_reasons`
- `difficulty_confidence`
- `review_status`
- `last_verified_date`
- `reality_check_summary`

AI-risk scoring checks for missing creator/source attribution, missing tutorial or source URLs, vague generic wording, suspicious infographic-style wording, unrealistic beginner claims, thin materials or assembly support, and suspicious stitch-count wording when pattern text exists.

Risk labels:

- `likely_legitimate`
- `questionable`
- `likely_ai_generated`

Questionable or likely AI-generated patterns are marked `review_status: needs_review` and appended to the local JSONL review queue at `logs/pattern_review_queue.jsonl`. The queue is local/ignored and should be reviewed manually before any pattern is marked `verified`, `human_tested`, or `community_reviewed`.

Manual review steps:

1. Open `logs/pattern_review_queue.jsonl`.
2. Check the source URL, creator attribution, materials list, tutorial availability, stitch counts, and assembly steps.
3. If the pattern is trustworthy, update the source pattern data with a real `review_status` such as `verified` or `community_reviewed`.
4. Only set `human_tested: true` when someone has actually made or tested the pattern.

What still needs human validation:

- Whether creator attribution is real and complete.
- Whether stitch counts work across all sizes or rounds.
- Whether photos are from the actual creator/pattern.
- Whether instructions are beginner-friendly in practice.
- Whether a pattern has been made by a human tester or reviewed by the community.

Quick start guide:
[HOW_TO_RUN.md](/C:/Users/trenp/crochet-pattern-agent/docs/HOW_TO_RUN.md)

Production runbook:
[DEPLOYMENT_RUNBOOK.md](/C:/Users/trenp/crochet-pattern-agent/docs/DEPLOYMENT_RUNBOOK.md)

Controlled live-fire checklist:
[LIVE_FIRE_TEST_CHECKLIST.md](/C:/Users/trenp/crochet-pattern-agent/docs/LIVE_FIRE_TEST_CHECKLIST.md)
