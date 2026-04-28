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
