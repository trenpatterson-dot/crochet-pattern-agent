"""
Batch runner for all active subscribers.
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pathlib
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / ".env")

import database
import mailer
import orchestrator
from agents import competition_intelligence_agent

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOCK_PATH = database.DB_PATH.parent / "scheduler.lock"
CADENCE_DAYS = 14


def log(msg: str, f=None):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    if f:
        f.write(line + "\n")
        f.flush()


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _is_due(user: dict, now: datetime) -> tuple[bool, str]:
    last_sent = _parse_dt(user.get("last_report_sent"))
    if last_sent is None:
        return True, "never_sent"

    next_due = last_sent + timedelta(days=CADENCE_DAYS)
    if now >= next_due:
        return True, "due"

    return False, f"next_due={next_due.isoformat(timespec='seconds')}"


def get_due_users(now: datetime | None = None) -> list[dict]:
    database.init_db()
    now = now or datetime.now()
    due_users = []
    for user in database.get_active_users():
        due, reason = _is_due(user, now)
        if due:
            due_users.append({"user": user, "reason": reason})
    return due_users


def send_selected_subscriber(email: str, *, dry_run_override: bool | None = None) -> dict:
    database.init_db()
    started_at = datetime.now()
    user = database.get_user_by_email(email.strip().lower())
    if not user:
        return {
            "ok": False,
            "status": "missing_user",
            "email": email,
            "dry_run": mailer.EMAIL_DRY_RUN if dry_run_override is None else dry_run_override,
        }

    if not user.get("active"):
        return {
            "ok": False,
            "status": "inactive_user",
            "email": user["email"],
            "dry_run": mailer.EMAIL_DRY_RUN if dry_run_override is None else dry_run_override,
        }

    result = orchestrator.run(user)
    if not result or not result.get("patterns"):
        return {
            "ok": False,
            "status": "no_patterns",
            "email": user["email"],
            "dry_run": mailer.EMAIL_DRY_RUN if dry_run_override is None else dry_run_override,
        }

    patterns = result["patterns"]
    ok = mailer.send_report(user, patterns, dry_run_override=dry_run_override)
    effective_dry_run = mailer.EMAIL_DRY_RUN if dry_run_override is None else dry_run_override
    if ok and not effective_dry_run:
        database.save_report(user["id"], result)

    return {
        "ok": ok,
        "status": "sent" if ok and not effective_dry_run else ("dry_run" if ok else "send_failed"),
        "email": user["email"],
        "user_id": user["id"],
        "patterns_count": len(patterns),
        "dry_run": effective_dry_run,
        "duration_seconds": round((datetime.now() - started_at).total_seconds(), 2),
    }


def _acquire_lock() -> int | None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


def _release_lock(lock_fd: int | None) -> None:
    if lock_fd is not None:
        os.close(lock_fd)
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def run() -> dict:
    database.init_db()
    started_at = datetime.now()
    dry_run = mailer.EMAIL_DRY_RUN
    log_path = LOG_DIR / f"run_{started_at.strftime('%Y-%m-%d_%H-%M-%S_%f')}.log"
    users = database.get_active_users()
    error_summary = []
    sent = failed = skipped = 0
    lock_fd = _acquire_lock()
    intel_summary = None

    with open(log_path, "w", encoding="utf-8") as f:
        if lock_fd is None:
            log("SKIP - scheduler run already active. New run will not start.", f)
            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            summary = {
                "started_at": started_at.isoformat(timespec="seconds"),
                "finished_at": finished_at.isoformat(timespec="seconds"),
                "duration_seconds": round(duration, 2),
                "sent_count": 0,
                "failed_count": 0,
                "skipped_count": 1,
                "dry_run": dry_run,
                "error_summary": ["scheduler_locked"],
                "log_path": str(log_path),
            }
            log(f"started_at={summary['started_at']}", f)
            log(f"finished_at={summary['finished_at']}", f)
            log(f"duration_seconds={summary['duration_seconds']}", f)
            log(f"sent_count=0 failed_count=0 skipped_count=1 dry_run={dry_run}", f)
            log("error_summary=scheduler_locked", f)
            return summary

        try:
            log(f"Batch run started - {len(users)} active subscriber(s)", f)
            log(f"started_at={started_at.isoformat(timespec='seconds')}", f)
            log(f"dry_run={dry_run}", f)
            log("=" * 55, f)

            try:
                intel_summary = competition_intelligence_agent.run(force=False)
                log(
                    f"Competition intel status={intel_summary.get('status', 'unknown')}",
                    f,
                )
            except Exception as exc:
                error_summary.append(f"competition_intel:{exc}")
                log(f"Competition intel refresh failed: {exc}", f)

            if not users:
                skipped += 1
                log("No active subscribers. Share the form at http://localhost:5050 to get sign-ups.", f)
            else:
                for user in users:
                    due, reason = _is_due(user, started_at)
                    if not due:
                        skipped += 1
                        log(
                            f"SKIP - {user['name']} <{user['email']}> is not due for a send ({reason})",
                            f,
                        )
                        continue

                    log(f"\nProcessing: {user['name']} <{user['email']}>", f)

                    try:
                        result = orchestrator.run(user)

                        if not result or not result.get("patterns"):
                            skipped += 1
                            log("  SKIP - orchestrator returned no patterns", f)
                            continue

                        patterns = result["patterns"]
                        ok = mailer.send_report(user, patterns)

                        if ok:
                            database.save_report(user["id"], result)
                            sent += 1
                            log(f"  OK - report sent and saved ({len(patterns)} patterns)", f)
                        else:
                            failed += 1
                            error_summary.append(f"email_not_sent:{user['email']}")
                            log("  FAIL - email not sent", f)
                    except Exception as exc:
                        failed += 1
                        error_summary.append(f"{user['email']}:{exc}")
                        log(f"  FAIL - unhandled error: {exc}", f)

                    if len(users) > 1:
                        time.sleep(3)
        finally:
            _release_lock(lock_fd)

        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        compact_errors = "; ".join(error_summary[:5]) if error_summary else "none"
        summary = {
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 2),
            "sent_count": sent,
            "failed_count": failed,
            "skipped_count": skipped,
            "dry_run": dry_run,
            "competition_intel": intel_summary,
            "error_summary": error_summary,
            "log_path": str(log_path),
        }

        log("=" * 55, f)
        log(f"finished_at={summary['finished_at']}", f)
        log(f"duration_seconds={summary['duration_seconds']}", f)
        log(
            f"sent_count={sent} failed_count={failed} skipped_count={skipped} dry_run={dry_run}",
            f,
        )
        log(f"error_summary={compact_errors}", f)
        log(f"Log: {log_path}", f)
        return summary


if __name__ == "__main__":
    run()
