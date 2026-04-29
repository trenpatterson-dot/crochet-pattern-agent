"""
Batch runner for all active subscribers.
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pathlib
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent / ".env")

import database
from agents import llm as shared_llm
import mailer
import orchestrator
from agents import competition_intelligence_agent

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOCK_PATH = database.DB_PATH.parent / "scheduler.lock"
SELECTED_TEST_STATUS_PATH = LOG_DIR / "selected_test_status.json"
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


def _mask_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return email[:1] + "***" if email else ""
    local, domain = email.split("@", 1)
    masked_local = (local[:1] + "***") if local else "***"
    return f"{masked_local}@{domain}"


def _friendly_selected_status(result: dict) -> tuple[str, str]:
    if result.get("ok"):
        if result.get("dry_run"):
            return "succeeded", "Selected subscriber dry-run completed. No live email was sent."
        return "succeeded", "Selected subscriber send completed."

    status = result.get("status")
    if status == "search_zero_candidates":
        return "failed", "Search returned 0 candidates."
    if status == "search_parse_failed":
        return "failed", "Search agent returned output that could not be parsed into candidates."
    if status == "filter_zero_candidates":
        return "failed", "All candidates were filtered out."
    if status == "filter_parse_failed":
        return "failed", "Filter agent returned output that could not be parsed into ranked patterns."
    if status == "creator_parse_failed":
        return "failed", "Pattern creator returned invalid output."
    if status == "compliance_and_creator_zero_patterns":
        return "failed", "Compliance and creator stages both returned 0 usable patterns."
    if status == "final_zero_patterns":
        return "failed", "The report pipeline completed, but 0 usable patterns remained after enrichment and validation."
    if status == "llm_timeout":
        return "failed", "OpenAI timed out while generating the report. Try again or increase the selected-test timeout."
    if status == "llm_network_error":
        return "failed", "OpenAI network connection failed while generating the report. Try again and check outbound connectivity."
    if status == "llm_api_key_error":
        return "failed", "OpenAI authentication failed. Check the API key and provider settings."
    if status == "llm_credit_error":
        return "failed", "OpenAI credits or rate limits blocked the request. Check quota and retry."
    if status == "llm_provider_rejected":
        return (
            "failed",
            "The LLM provider rejected the request. Check provider settings and request parameters.",
        )
    if status == "no_patterns":
        return "failed", "Report generation finished without usable patterns for that subscriber."
    if status == "send_failed":
        return "failed", "Report generation finished, but the mailer step failed."
    if status == "inactive_user":
        return "failed", "Selected subscriber is inactive and was not processed."
    if status == "missing_user":
        return "failed", "Selected subscriber was not found."
    return "failed", "Selected subscriber test failed. Check the logs for details."


def _write_selected_test_status(payload: dict) -> None:
    SELECTED_TEST_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = SELECTED_TEST_STATUS_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(SELECTED_TEST_STATUS_PATH)


def get_selected_test_status() -> dict | None:
    if not SELECTED_TEST_STATUS_PATH.exists():
        return None
    try:
        return json.loads(SELECTED_TEST_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "state": "failed",
            "message": "Selected test status file could not be read.",
        }


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
    effective_dry_run = mailer.EMAIL_DRY_RUN if dry_run_override is None else dry_run_override
    if not user:
        return {
            "ok": False,
            "status": "missing_user",
            "email": email,
            "dry_run": effective_dry_run,
        }

    if not user.get("active"):
        return {
            "ok": False,
            "status": "inactive_user",
            "email": user["email"],
            "dry_run": effective_dry_run,
        }

    job_user = dict(user)
    job_user["_selected_test_mode"] = True
    job_user["_selected_test_dry_run"] = effective_dry_run

    try:
        with shared_llm.selected_test_context():
            result = orchestrator.run(job_user)
    except shared_llm.LLMServiceError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "email": user["email"],
            "user_id": user["id"],
            "dry_run": effective_dry_run,
            "provider": exc.provider,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "llm_provider_rejected",
            "email": user["email"],
            "user_id": user["id"],
            "dry_run": effective_dry_run,
            "provider": shared_llm.provider_debug_summary().get("llm_provider"),
            "error": str(exc),
        }

    diagnostics = (result or {}).get("diagnostics", {})
    print(
        "[Selected Test] search_candidates=%s filtered_candidates=%s created_originals=%s final_patterns=%s reason=%s"
        % (
            diagnostics.get("search_candidates_count"),
            diagnostics.get("filtered_candidates_count"),
            diagnostics.get("original_created_count"),
            diagnostics.get("final_usable_pattern_count"),
            diagnostics.get("failure_reason"),
        )
    )

    creator_reason = diagnostics.get("creator_meta", {}).get("reason")
    if creator_reason in {"invalid_json", "parsed_zero_items"} and not diagnostics.get("final_usable_pattern_count"):
        return {
            "ok": False,
            "status": "creator_parse_failed",
            "email": user["email"],
            "user_id": user["id"],
            "dry_run": effective_dry_run,
            "provider": shared_llm.provider_debug_summary().get("llm_provider"),
            "diagnostics": diagnostics,
        }

    if not result or not result.get("patterns"):
        return {
            "ok": False,
            "status": diagnostics.get("failure_reason") or "no_patterns",
            "email": user["email"],
            "dry_run": effective_dry_run,
            "diagnostics": diagnostics,
        }

    patterns = result["patterns"]
    ok = mailer.send_report(user, patterns, dry_run_override=dry_run_override)
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
        "diagnostics": diagnostics,
    }


def run_selected_subscriber_job(email: str, *, dry_run_override: bool | None = None) -> dict:
    started_at = datetime.now()
    effective_dry_run = mailer.EMAIL_DRY_RUN if dry_run_override is None else dry_run_override
    provider = shared_llm.provider_debug_summary().get("llm_provider")
    status_payload = {
        "state": "started",
        "message": "Selected subscriber test started.",
        "email_masked": _mask_email(email),
        "dry_run": effective_dry_run,
        "provider": provider,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": None,
        "error": None,
    }
    _write_selected_test_status(status_payload)

    try:
        result = send_selected_subscriber(email, dry_run_override=dry_run_override)
    except Exception as exc:
        result = {
            "ok": False,
            "status": "unexpected_error",
            "email": email,
            "dry_run": effective_dry_run,
            "provider": provider,
            "error": str(exc),
        }

    state, message = _friendly_selected_status(result)
    finished_at = datetime.now()
    status_payload.update(
        {
            "state": state,
            "message": message,
            "status": result.get("status"),
            "email_masked": _mask_email(result.get("email", email)),
            "user_id": result.get("user_id"),
            "patterns_count": result.get("patterns_count"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
            "error": result.get("error"),
            "diagnostics": result.get("diagnostics"),
        }
    )
    _write_selected_test_status(status_payload)
    return result


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
