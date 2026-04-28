import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _set_env(db_path: Path) -> None:
    os.environ["DB_PATH"] = str(db_path)
    os.environ["FLASK_ENV"] = "development"
    os.environ["SERVER_BASE_URL"] = "https://crochet.example.com"
    os.environ["ADMIN_PASSWORD"] = "local-admin-pass"
    os.environ["FLASK_SECRET_KEY"] = "local-secret"
    os.environ["UNSUBSCRIBE_SECRET"] = "local-unsub-secret"
    os.environ["EMAIL_DRY_RUN"] = "true"
    os.environ["GMAIL_USER"] = "dryrun@example.com"
    os.environ["GMAIL_APP_PASSWORD"] = "not-used"
    os.environ["AMAZON_ASSOCIATE_TAG"] = "smoketest-20"


def main() -> int:
    temp_root = ROOT / ".tmp"
    temp_root.mkdir(exist_ok=True)
    db_path = temp_root / "smoke_test.db"

    try:
        if db_path.exists():
            db_path.unlink()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _set_env(db_path)

        import database
        from agents import link_builder, link_validator
        import mailer
        import orchestrator
        import scheduler
        from server import app, _load_unsubscribe_email

        database.DB_PATH = db_path
        database.init_db()
        scheduler.LOCK_PATH = temp_root / "scheduler.lock"

        client = app.test_client()

        root = client.get("/")
        assert root.status_code == 200, f"/ returned {root.status_code}"

        admin = client.get("/admin")
        assert admin.status_code == 401, f"/admin without auth returned {admin.status_code}"

        auth = {"Authorization": "Basic bG9jYWw6bG9jYWwtYWRtaW4tcGFzcw=="}
        admin_ok = client.get("/admin", headers=auth)
        assert admin_ok.status_code == 200, f"/admin with auth returned {admin_ok.status_code}"

        subscribe = client.post(
            "/subscribe",
            data={
                "name": "Smoke Tester",
                "email": "smoke@example.com",
                "skill_level": "beginner",
                "project_types": ["blankets"],
                "yarn_weights": ["cotton"],
                "time_commitment": "quick",
                "color_preferences": "blue",
                "aesthetic": "Cozy",
                "budget": "$10-$25",
                "wants_video": "on",
                "free_only": "on",
            },
        )
        assert subscribe.status_code == 200, f"/subscribe returned {subscribe.status_code}"

        users = database.get_active_users()
        assert len(users) == 1, f"expected 1 active user, found {len(users)}"
        user = users[0]

        fake_result = {
            "user_name": user["name"],
            "patterns": [
                {
                    "title": "Smoke Test Pattern",
                    "source_site": "Original - created for you",
                    "skill_level": "beginner",
                    "project_type": "blankets",
                    "estimated_time": "1 hour",
                    "why_created": "Safe dry-run validation pattern.",
                    "is_original": True,
                    "materials": [],
                    "abbreviations": {},
                    "instructions": "Row 1: ch 10",
                    "notes": [],
                    "hook_size": "5mm",
                    "yarn_weight": "cotton",
                    "gauge": "not important",
                    "finished_size": "small",
                    "tagline": "Validation pattern",
                    "color_suggestion": "blue",
                    "license_type": "original - personal use free",
                    "is_free": True,
                    "video_tutorial": {
                        "title": "Broken tutorial",
                        "url": "https://www.youtube.com/watch?v=",
                    },
                }
            ],
            "found_count": 0,
            "original_count": 1,
        }

        original_run = orchestrator.run
        original_send = mailer.send_report
        try:
            orchestrator.run = lambda current_user: fake_result
            mailer.send_report = lambda current_user, patterns: True
            scheduler.run()
        finally:
            orchestrator.run = original_run
            mailer.send_report = original_send

        reports = database.get_reports_for_user(user["id"])
        assert reports, "scheduler dry-run did not save a report"

        normalized_scissors = link_builder.material_query_normalizer("scissors")
        normalized_needles = link_builder.material_query_normalizer("yarn needle set")
        normalized_hook = link_builder.material_query_normalizer("Crochet Hook", hook_size="5mm")
        normalized_stuffing = link_builder.material_query_normalizer("stuffing")
        assert normalized_scissors == "small craft scissors Fiskars", "scissors query should be specific"
        assert normalized_needles == "yarn needle set blunt tip", "yarn needle query should use blunt tip wording"
        assert normalized_hook == "5mm crochet hook ergonomic beginner set", "crochet hook query should include hook size and specificity"
        assert normalized_stuffing == "polyester fiberfill stuffing small bag", "stuffing query should be specific"

        tutorial_checked = link_validator.validate_tutorial_links(fake_result["patterns"])
        assert tutorial_checked[0]["video_tutorial"] is None, "invalid tutorial should be removed"

        fake_result["patterns"][0]["materials"] = [
            {
                "name": "scissors",
                "store_name": "Michaels",
                "store_url": "https://www.michaels.com/products/example",
            },
            {
                "name": "yarn needle set",
                "store_name": "Joann",
                "store_url": "https://www.joann.com/products/example",
            },
            {
                "name": "Crochet Hook",
                "store_name": "Michaels",
                "store_url": "https://www.michaels.com/products/hook-example",
                "hook_size": "5mm",
            },
        ]
        material_checked = link_validator.validate_material_links(fake_result["patterns"])
        materials = material_checked[0]["materials"]
        assert "amazon.com/s?k=small+craft+scissors+Fiskars" in materials[0]["affiliate_url"], (
            "scissors link should use Amazon affiliate search query"
        )
        assert "tag=smoketest-20" in materials[0]["affiliate_url"], (
            "scissors affiliate URL should include the Amazon associate tag"
        )
        assert "amazon.com/s?k=yarn+needle+set+blunt+tip" in materials[1]["affiliate_url"], (
            "yarn needle link should use Amazon affiliate search query"
        )
        assert "amazon.com/s?k=5mm+crochet+hook+ergonomic+beginner+set" in materials[2]["affiliate_url"], (
            "crochet hook link should use a specific Amazon affiliate query"
        )
        assert all(item["approx_price"] == "Price varies by retailer" for item in materials), (
            "material pricing should be normalized"
        )

        final_checked = link_validator.validate_tutorial_links(material_checked)
        rendered_html = mailer.build_html(user, final_checked)
        assert "https://crochet.example.com/unsubscribe?token=" in rendered_html, (
            "email HTML is missing the production unsubscribe URL"
        )
        assert "https://crochet.example.com" in rendered_html, (
            "email HTML is missing the production update preferences URL"
        )
        assert "localhost" not in rendered_html, "email HTML should never contain localhost"
        assert "~$" not in rendered_html, "email HTML should not contain approximate pricing"
        assert "$4.99" not in rendered_html, "email HTML should not contain fake pricing"
        assert "Price varies by retailer" in rendered_html, "email HTML should show retailer-safe pricing text"
        assert "Search Tutorial" not in rendered_html, "email HTML should not show tutorial fallback CTA"
        assert "Tutorial</a>" not in rendered_html, "email HTML should not show tutorial CTA when link is invalid"
        assert "What You" in rendered_html and "Quick Buy Links" in rendered_html, (
            "email HTML should use updated materials header"
        )
        assert "Shop on Amazon" in rendered_html, "email HTML should use Amazon CTA text"
        assert (
            "This email may contain affiliate links. We may earn a small commission at no extra cost to you."
            in rendered_html
        ), "email HTML should include the affiliate disclosure"

        assert scheduler.run()["sent_count"] == 0, "second scheduler run should not re-send before due date"
        assert scheduler.run()["skipped_count"] >= 1, "second scheduler run should skip not-due subscriber"

        reset_due = client.post("/admin/reset-due", data={"email": user["email"]}, headers=auth)
        assert reset_due.status_code == 302, f"/admin/reset-due returned {reset_due.status_code}"
        users = database.get_active_users()
        assert users[0]["last_report_sent"] is None, "reset due now did not clear last_report_sent"

        scheduler.LOCK_PATH.write_text("locked", encoding="utf-8")
        locked = scheduler.run()
        assert locked["error_summary"] == ["scheduler_locked"], "lock test should report scheduler_locked"
        scheduler.LOCK_PATH.unlink(missing_ok=True)

        token = mailer._unsubscribe_token(user["email"])
        assert _load_unsubscribe_email(token) == user["email"]

        unsub = client.get(f"/unsubscribe?token={token}")
        assert unsub.status_code == 200, f"/unsubscribe returned {unsub.status_code}"
        assert len(database.get_active_users()) == 0, "unsubscribe did not deactivate the user"

        print("Smoke test passed.")
        return 0
    finally:
        if db_path.exists():
            try:
                db_path.unlink()
            except PermissionError:
                pass
        pycache_dir = temp_root / "__pycache__"
        if pycache_dir.exists():
            shutil.rmtree(pycache_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
