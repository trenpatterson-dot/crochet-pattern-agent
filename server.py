"""
Flask server for preferences, unsubscribe, and admin actions.
"""

import hmac
import json
import logging
import os
import pathlib
import threading

from dotenv import load_dotenv
from flask import Flask, Response, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, URLSafeSerializer

load_dotenv(pathlib.Path(__file__).parent / ".env")
import database
import scheduler
from agents import competition_intelligence_agent

database.init_db()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
UNSUBSCRIBE_SECRET = os.getenv("UNSUBSCRIBE_SECRET", app.secret_key)
RUN_LOCK = threading.Lock()
INTEL_LOCK = threading.Lock()
logger = logging.getLogger(__name__)

PROJECT_TYPES = [
    ("blankets", "Blankets & Afghans"),
    ("hats_scarves", "Hats & Scarves"),
    ("amigurumi", "Toys & Amigurumi"),
    ("clothing", "Clothing & Wearables"),
    ("bags", "Bags & Totes"),
    ("home_decor", "Home Decor"),
    ("baby", "Baby Items"),
    ("holiday", "Holiday & Seasonal"),
    ("accessories", "Accessories (gloves, shawls, etc.)"),
]

YARN_TYPES = [
    ("cotton", "Cotton"),
    ("acrylic", "Acrylic"),
    ("wool", "Wool"),
    ("blend", "Blends"),
    ("any", "No preference"),
]

AESTHETICS = ["Minimal", "Cozy", "Modern", "Cute", "Seasonal", "Boho", "Classic"]
BUDGETS = ["$10-$25", "$25-$50", "$50+", "No limit"]


def _mask_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return email[:1] + "***" if email else ""
    local, domain = email.split("@", 1)
    masked_local = (local[:1] + "***") if local else "***"
    return f"{masked_local}@{domain}"


def _mask_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    return f"{name[:1]}*** ({len(name)} chars)"


def _is_production() -> bool:
    return os.getenv("FLASK_ENV", "production").strip().lower() == "production"


def _admin_setup_error() -> Response | None:
    if ADMIN_PASSWORD:
        return None

    message = "ADMIN_PASSWORD is not configured."
    if _is_production():
        message += " Set ADMIN_PASSWORD before exposing admin routes in production."
        return Response(message, 500)

    return Response(message + " Configure it locally to use admin routes.", 503)


def _require_admin():
    setup_error = _admin_setup_error()
    if setup_error:
        return setup_error

    supplied = request.authorization.password if request.authorization else ""
    if hmac.compare_digest(supplied, ADMIN_PASSWORD):
        return None

    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Crochet Admin"'},
    )


def _scheduler_worker():
    try:
        scheduler.run()
    finally:
        RUN_LOCK.release()


def _start_scheduler_run() -> bool:
    if not RUN_LOCK.acquire(blocking=False):
        return False

    worker = threading.Thread(target=_scheduler_worker, daemon=True)
    worker.start()
    return True


def _competition_intel_worker():
    try:
        competition_intelligence_agent.run(force=True)
    finally:
        INTEL_LOCK.release()


def _start_competition_intel_run() -> bool:
    if not INTEL_LOCK.acquire(blocking=False):
        return False

    worker = threading.Thread(target=_competition_intel_worker, daemon=True)
    worker.start()
    return True


def _load_unsubscribe_email(token: str) -> str | None:
    if not token:
        return None

    serializer = URLSafeSerializer(UNSUBSCRIBE_SECRET, salt="unsubscribe")
    try:
        payload = serializer.loads(token)
    except BadSignature:
        return None
    return str(payload.get("email", "")).strip().lower() or None


@app.route("/")
def index():
    return render_template(
        "form.html",
        project_types=PROJECT_TYPES,
        yarn_types=YARN_TYPES,
        aesthetics=AESTHETICS,
        budgets=BUDGETS,
    )


@app.route("/subscribe", methods=["POST"])
def subscribe():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    logger.info(
        "subscribe received email=%s name=%s db_path=%s",
        _mask_email(email),
        _mask_name(name),
        database.DB_PATH,
    )

    if not name or not email:
        logger.warning("subscribe rejected missing_required_fields email=%s", _mask_email(email))
        return render_template(
            "form.html",
            project_types=PROJECT_TYPES,
            yarn_types=YARN_TYPES,
            aesthetics=AESTHETICS,
            budgets=BUDGETS,
            error="Name and email are required.",
        )

    try:
        save_result = database.upsert_user(
            name=name,
            email=email,
            skill_level=request.form.get("skill_level", "beginner"),
            project_types=request.form.getlist("project_types") or ["any"],
            yarn_weights=request.form.getlist("yarn_weights") or ["any"],
            time_commitment=request.form.get("time_commitment", "any"),
            color_preferences=request.form.get("color_preferences", "").strip(),
            aesthetic=request.form.get("aesthetic", ""),
            budget=request.form.get("budget", ""),
            free_only="free_only" in request.form,
            wants_video="wants_video" in request.form,
            wants_printable="wants_printable" in request.form,
            special_interests=request.form.get("special_interests", "").strip(),
        )
    except Exception:
        logger.exception(
            "subscribe save_failed email=%s db_path=%s",
            _mask_email(email),
            database.DB_PATH,
        )
        return render_template(
            "form.html",
            project_types=PROJECT_TYPES,
            yarn_types=YARN_TYPES,
            aesthetics=AESTHETICS,
            budgets=BUDGETS,
            error="We couldn't save your preferences right now. Please try again.",
        ), 500

    logger.info(
        "subscribe save_ok email=%s action=%s user_id=%s active=%s total_users=%s active_users=%s db_path=%s",
        _mask_email(email),
        save_result.get("action"),
        save_result.get("user_id"),
        save_result.get("active"),
        save_result.get("total_users"),
        save_result.get("active_users"),
        database.DB_PATH,
    )
    session["subscription_success_name"] = name
    session["subscription_success_user_id"] = save_result.get("user_id")
    return redirect(url_for("success"), code=303)


@app.route("/success")
def success():
    name = session.pop("subscription_success_name", None)
    user_id = session.pop("subscription_success_user_id", None)
    if not name:
        logger.info("success blocked missing_subscription_session db_path=%s", database.DB_PATH)
        return redirect(url_for("index"))

    logger.info(
        "success rendered user_id=%s db_path=%s",
        user_id,
        database.DB_PATH,
    )
    return render_template("success.html", name=name)


@app.route("/unsubscribe")
def unsubscribe():
    email = _load_unsubscribe_email(request.args.get("token", ""))
    if email:
        database.deactivate_user(email)
    return render_template("unsubscribed.html", email=email)


@app.route("/admin")
def admin():
    auth_error = _require_admin()
    if auth_error:
        return auth_error
    users = database.get_all_users()
    summary = database.get_storage_debug_summary()
    logger.info(
        "admin dashboard_loaded total_users=%s active_users=%s inactive_users=%s total_reports=%s db_path=%s",
        summary.get("total_users"),
        summary.get("active_users"),
        summary.get("inactive_users"),
        summary.get("total_reports"),
        summary.get("db_path"),
    )
    return render_template("admin.html", users=users, storage_debug=summary)


@app.route("/admin/reset-due", methods=["POST"])
def admin_reset_due():
    auth_error = _require_admin()
    if auth_error:
        return auth_error

    email = request.form.get("email", "").strip().lower()
    if not email:
        return Response("Subscriber email is required.", 400)

    database.reset_user_due_now(email)
    return redirect(url_for("admin") + "?due_reset=1")


@app.route("/admin/run", methods=["POST"])
def admin_run():
    auth_error = _require_admin()
    if auth_error:
        return auth_error

    if not _start_scheduler_run():
        return Response("Scheduler is already running.", 409)

    return redirect(url_for("admin") + "?running=1")


@app.route("/internal/scheduler/run", methods=["POST"])
def internal_scheduler_run():
    auth_error = _require_admin()
    if auth_error:
        return auth_error

    if not _start_scheduler_run():
        return Response("Scheduler is already running.", 409)

    return Response("Scheduler run started.", 202)


@app.route("/admin/intel/run", methods=["POST"])
def admin_competition_intel_run():
    auth_error = _require_admin()
    if auth_error:
        return auth_error

    if not _start_competition_intel_run():
        return Response("Competition intelligence run is already active.", 409)

    return redirect(url_for("admin") + "?intel_running=1")


@app.route("/admin/intel/latest/<artifact_name>")
def admin_competition_intel_latest(artifact_name):
    auth_error = _require_admin()
    if auth_error:
        return auth_error

    if artifact_name not in {"trends", "competitors", "opportunities", "keywords"}:
        return Response("Unknown artifact.", 404)

    payload = database.get_latest_competition_artifact(artifact_name)
    if not payload:
        return Response("No intelligence artifact found.", 404)

    return Response(
        json.dumps(payload["artifact_json"], indent=2),
        mimetype="application/json",
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("FLASK_PORT", 5050)))
    debug = os.getenv("FLASK_ENV", "production") == "development"
    print(f"Crochet Pattern Finder -> http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
