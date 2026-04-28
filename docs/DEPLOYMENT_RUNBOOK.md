# Deployment Runbook

## Scope

This runbook covers a safe go-live path for `crochet-pattern-agent` with:

- locked admin access
- persistent subscriber storage
- dry-run validation before live sends
- a Render cron trigger that tells the web service to run the scheduler

## Required Environment Variables

Set these before production exposure:

- `ADMIN_PASSWORD`
- `FLASK_SECRET_KEY`
- `UNSUBSCRIBE_SECRET`
- `SERVER_BASE_URL`
- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `ANTHROPIC_API_KEY`
- `EMAIL_DRY_RUN`
- `DB_PATH`

Recommended values:

- `EMAIL_DRY_RUN=true` until validation is complete
- `DB_PATH=/app/data/crochet_agent.db` on Docker/Render

## Render Deployment Notes

Web service:

- attach a persistent disk at `/app/data`
- keep `DB_PATH=/app/data/crochet_agent.db`
- do not expose the app publicly until `ADMIN_PASSWORD` is set

Cron service:

- the cron job calls the web service over the Render private network
- it does not need direct database access
- Render cron does not cleanly express an exact every-14-days schedule
- the app enforces a 14-day due check per subscriber, so a weekly cron trigger is safe for pilot use

## Pre-Deploy Checklist

1. Confirm `.env` is not committed and no real secrets are in the repo.
2. Confirm `EMAIL_DRY_RUN=true`.
3. Confirm `ADMIN_PASSWORD` is set in the deployment platform.
4. Confirm the persistent disk is mounted at `/app/data`.
5. Confirm `SERVER_BASE_URL` matches the public HTTPS URL for unsubscribe links.

## Dry-Run Validation

Use these local checks first:

```cmd
cd C:\Users\trenp\crochet-pattern-agent
cmd /c "set EMAIL_DRY_RUN=true && C:\Users\trenp\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe scripts\smoke_test.py"
```

Then validate the web app locally:

```cmd
cd C:\Users\trenp\crochet-pattern-agent
cmd /c "set EMAIL_DRY_RUN=true && C:\Users\trenp\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe server.py"
```

Success criteria:

- `/` loads
- `/admin` returns `401` with valid admin config and no credentials
- `/subscribe` creates or updates a subscriber
- `/unsubscribe` deactivates the subscriber
- dry-run scheduler completes without sending real email

## Live-Fire Test

Run this only after dry-run checks pass:

1. Deploy with real secrets set.
2. Keep the subscriber list limited to a controlled test inbox.
3. Set `EMAIL_DRY_RUN=false` and confirm the platform shows that value before continuing.
4. In `/admin`, confirm the active subscriber is your operator test inbox, not `smoke@example.com`.
5. If needed, use the protected `Mark Due Now` action for that one subscriber.
6. Trigger one manual run from `/admin`.
7. Verify:
   - email delivered
   - content renders correctly
   - unsubscribe link works
   - `last_report_sent` updates
8. Return `EMAIL_DRY_RUN=true` if any delivery, content, or unsubscribe issue appears.

For the exact one-pass operator steps, use:
[LIVE_FIRE_TEST_CHECKLIST.md](/C:/Users/trenp/crochet-pattern-agent/docs/LIVE_FIRE_TEST_CHECKLIST.md)

## Unsubscribe Test

1. Subscribe a test inbox.
2. Send one dry-run or live-fire report as appropriate.
3. Open the unsubscribe link from the message.
4. Confirm the subscriber becomes inactive in `/admin`.
5. Run the scheduler again and confirm the inactive inbox is skipped.

## Rollback Notes

If the deploy misbehaves:

1. Set `EMAIL_DRY_RUN=true` immediately.
2. Disable or pause the Render cron job.
3. Roll back the web service to the previous good deploy in Render.
4. Restore subscriber data from the persistent disk snapshot if data corruption is suspected.
5. Re-run the smoke checks before re-enabling live sends.

## Operational Risks To Review Before Live

- The cron schedule in `render.yaml` is a placeholder, not a guaranteed bi-weekly schedule.
- SQLite is acceptable for a small pilot, but it is not the long-term multi-service datastore.
- The scheduler currently runs inside the web service process, so avoid overlapping runs and watch logs during live-fire testing.
