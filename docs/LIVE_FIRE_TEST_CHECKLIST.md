# Live Fire Test Checklist

## Purpose

Use this checklist for one controlled live-fire test only.

Constraints:

- use one test subscriber inbox only
- do not add any other live subscribers
- return `EMAIL_DRY_RUN=true` immediately after the test

## Required Environment Variables

Confirm these are already set in the deployment platform before the test:

- `ADMIN_PASSWORD`
- `FLASK_SECRET_KEY`
- `UNSUBSCRIBE_SECRET`
- `SERVER_BASE_URL`
- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `ANTHROPIC_API_KEY`
- `EMAIL_DRY_RUN`
- `DB_PATH`

Expected baseline:

- `EMAIL_DRY_RUN=true`
- `DB_PATH=/app/data/crochet_agent.db`

Before the one live-fire pass:

- set `EMAIL_DRY_RUN=false`
- confirm that change in the deployment platform before clicking `Run Now`

## Test Subscriber Only

Before the live-fire test:

1. Open the public signup form.
2. Subscribe exactly one controlled test inbox.
3. Confirm no other active subscribers are present in `/admin`.
4. Confirm the active subscriber email in `/admin` is your operator test inbox, not `smoke@example.com`.

If any non-test subscriber is active, stop and deactivate them before continuing.

## Temporary Change To Enable One Live Send

In the deployment platform, change:

- `EMAIL_DRY_RUN` from `true` to `false`

Do not change any secrets.
Do not change the cron schedule for this test.
Do not continue until you have confirmed the value is now `false`.

## Run One Scheduler Pass

Use the manual admin path for this one test:

1. Open `/admin`.
2. Authenticate with the configured admin password.
3. Confirm the row you want to test shows your real test inbox.
4. If the subscriber was used before, click `Mark Due Now` on that exact subscriber row.
5. Click `Run Now (All Users)` once.
6. Do not click it again.
7. Watch the latest file in `logs/` and confirm the run shows:
   - `started_at`
   - `finished_at`
   - `sent_count=1`
   - `failed_count=0`
   - `dry_run=False`
   - no `SKIP - ... is not due for a send` line for your selected test inbox

## Verify Email Received

In the test inbox, confirm:

1. The email arrives from the expected sender.
2. Subject line looks correct.
3. HTML content renders correctly.
4. Pattern links open.
5. The unsubscribe link is present.

## Verify Unsubscribe Works

1. Open the unsubscribe link from the delivered email.
2. Confirm the unsubscribe page loads successfully.
3. Return to `/admin`.
4. Confirm the test subscriber is now inactive or off.

## Return To Safe State

Immediately after verification:

1. Set `EMAIL_DRY_RUN=true` in the deployment platform.
2. Save and redeploy if the platform requires it.
3. Confirm the environment now shows `EMAIL_DRY_RUN=true`.

## Rollback Steps

If anything looks wrong:

1. Set `EMAIL_DRY_RUN=true` immediately.
2. Do not run the scheduler again.
3. Disable or pause the Render cron job if needed.
4. Review the latest `logs/` file.
5. Roll back the service in Render if the deployed build is the issue.

## Success Criteria

The live-fire test is successful if all of the following are true:

- exactly one controlled test inbox received the email
- the email content rendered correctly
- unsubscribe worked
- the subscriber became inactive after unsubscribe
- `EMAIL_DRY_RUN` was returned to `true`
