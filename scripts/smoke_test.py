import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _set_env(db_path: Path) -> None:
    os.environ["DB_PATH"] = str(db_path)
    os.environ["COMPETITION_INTEL_DIR"] = str(db_path.parent / "intel")
    os.environ["FLASK_ENV"] = "development"
    os.environ["SERVER_BASE_URL"] = "https://crochet.example.com"
    os.environ["ADMIN_PASSWORD"] = "local-admin-pass"
    os.environ["FLASK_SECRET_KEY"] = "local-secret"
    os.environ["UNSUBSCRIBE_SECRET"] = "local-unsub-secret"
    os.environ["EMAIL_DRY_RUN"] = "true"
    os.environ["EMAIL_PREVIEW_PATH"] = str(db_path.parent / "email_preview_latest.html")
    os.environ["SEND_FIRST_EMAIL_ON_SIGNUP"] = "false"
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
        from agents import competition_intelligence_agent
        from agents import link_builder, link_validator
        import mailer
        import orchestrator
        import scheduler
        from server import app, _load_unsubscribe_email

        database.DB_PATH = db_path
        database.init_db()
        scheduler.LOCK_PATH = temp_root / "scheduler.lock"
        transport_debug = mailer.transport_debug_summary()
        assert transport_debug["reply_to_configured"], "Reply-To should be configured for feedback replies"
        assert transport_debug["reply_to_masked"] == "y***@gmail.com", (
            "Reply-To should point feedback replies to the configured inbox"
        )

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
                "email_frequency": "monthly",
                "wants_video": "on",
                "free_only": "on",
            },
            follow_redirects=False,
        )
        assert subscribe.status_code == 303, f"/subscribe returned {subscribe.status_code}"
        assert subscribe.headers["Location"].endswith("/success"), "subscribe should redirect to /success after save"

        success = client.get("/success")
        assert success.status_code == 200, f"/success returned {success.status_code}"
        blocked_success = client.get("/success", follow_redirects=False)
        assert blocked_success.status_code == 302, "direct /success without session should redirect to the form"
        assert blocked_success.headers["Location"].endswith("/"), "direct /success should redirect to /"

        users = database.get_active_users()
        assert len(users) == 1, f"expected 1 active user, found {len(users)}"
        user = users[0]
        assert user["email_frequency"] == "monthly", "email frequency preference was not saved"

        original_chat = competition_intelligence_agent.llm.chat
        original_ddg = competition_intelligence_agent.llm.ddg_search

        def fake_ddg_search(query, max_results=5):
            return [
                {
                    "title": f"Search result for {query}",
                    "href": f"https://example.com/{abs(hash(query)) % 100000}",
                    "body": "Public search snippet for testing.",
                }
            ]

        def fake_chat(system, user_msg, use_web_search=False, max_tokens=4096):
            if "TASK: competitors" in user_msg:
                assert "Splitting Yarn" in user_msg, "competitor prompt should include the beginner pain-point rubric"
                assert "Overall beginner-friendliness score from 1-10" in user_msg, (
                    "competitor prompt should require the beginner-friendliness score"
                )
                return json.dumps(
                    {
                        "generated_at": "2026-04-28T09:00:00",
                        "competitors": [
                            {
                                "name": "CozyLoops Studio",
                                "link": "https://example.com/etsy",
                                "platform": "Etsy",
                                "niche": "amigurumi",
                                "what_they_do_well": ["Simple project photos and visible beginner listings."],
                                "beginner_pain_points_addressed": ["Project Overwhelm"],
                                "beginner_pain_points_missed": [
                                    "Splitting Yarn",
                                    "Left-Handed Frustration",
                                    "The Finishing Gap",
                                ],
                                "confusing_beginner_experience": [
                                    "Listings do not visibly explain yarn splitting or finishing support."
                                ],
                                "opportunities_for_crochet_pattern_agent": [
                                    "Add beginner-first notes before the project link."
                                ],
                                "recommended_feature_content_ideas": [
                                    "Create a first-project checklist with yarn and finishing warnings."
                                ],
                                "overall_beginner_friendliness_score": 6,
                                "evidence_urls": ["https://example.com/etsy"],
                                "notes": "Visible beginner-friendly listings.",
                            }
                        ],
                    }
                )
            if "TASK: trends" in user_msg:
                return json.dumps(
                    {
                        "generated_at": "2026-04-28T09:00:00",
                        "weekly_summary": ["Baby blanket and frog motifs are rising."],
                        "trends": [
                            {
                                "topic": "crochet frog",
                                "trend_type": "rising",
                                "platforms": ["YouTube", "Etsy"],
                                "confidence": "medium",
                                "seasonality": "evergreen",
                                "why_it_matters": "Giftable and beginner-friendly.",
                                "evidence_urls": ["https://example.com/trend"],
                            }
                        ],
                    }
                )
            if "TASK: keywords" in user_msg:
                return json.dumps(
                    {
                        "generated_at": "2026-04-28T09:00:00",
                        "keywords": [
                            {
                                "keyword": "beginner crochet kit",
                                "intent": "buy",
                                "competition_assessment": "likely_low",
                                "reason": "Strong purchase language.",
                                "related_trends": ["starter kits"],
                                "evidence_urls": ["https://example.com/keyword"],
                            }
                        ],
                    }
                )
            if "TASK: opportunities" in user_msg:
                return json.dumps(
                    {
                        "generated_at": "2026-04-28T09:00:00",
                        "product_signals": [
                            {
                                "pattern_or_use_case": "baby blanket",
                                "materials": ["soft cotton yarn", "5mm hook", "stitch markers"],
                                "amazon_queries": ["baby blanket crochet kit"],
                                "affiliate_categories": ["yarn", "hooks", "kits"],
                                "evidence_urls": ["https://example.com/product"],
                            }
                        ],
                        "opportunities": [
                            {
                                "title": "Beginner kits under $20",
                                "opportunity_type": "affiliate",
                                "gap_summary": "Few competitors frame low-cost starter bundles clearly.",
                                "why_now": "Buyer intent is visible in search phrasing.",
                                "recommended_action": "Launch starter-kit recommendation blocks.",
                                "priority": "high",
                                "supporting_signals": ["buy-intent keyword language"],
                                "evidence_urls": ["https://example.com/opportunity"],
                            }
                        ],
                    }
                )
            raise AssertionError("unexpected intelligence prompt")

        competition_intelligence_agent.llm.chat = fake_chat
        competition_intelligence_agent.llm.ddg_search = fake_ddg_search
        try:
            intel_summary = competition_intelligence_agent.run(force=True)
        finally:
            competition_intelligence_agent.llm.chat = original_chat
            competition_intelligence_agent.llm.ddg_search = original_ddg

        assert intel_summary["status"] == "ok", "competition intelligence run should succeed"
        intel_root = Path(os.environ["COMPETITION_INTEL_DIR"])
        for name in ("trends", "competitors", "opportunities", "keywords"):
            assert (intel_root / "latest" / f"{name}.json").exists(), f"{name}.json should exist"
            latest_artifact = database.get_latest_competition_artifact(name)
            assert latest_artifact is not None, f"{name} artifact should be saved in SQLite"
        competitor_artifact = database.get_latest_competition_artifact("competitors")["artifact_json"]
        competitor = competitor_artifact["competitors"][0]
        assert "beginner_pain_points_addressed" in competitor, (
            "competitor artifact should include addressed beginner pain points"
        )
        assert "beginner_pain_points_missed" in competitor, (
            "competitor artifact should include missed beginner pain points"
        )
        assert competitor["overall_beginner_friendliness_score"] == 6, (
            "competitor artifact should include a 1-10 beginner-friendliness score"
        )

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

        def run_scheduler_with_fake_result():
            original_run = orchestrator.run
            try:
                orchestrator.run = lambda current_user: fake_result
                return scheduler.run()
            finally:
                orchestrator.run = original_run

        run_scheduler_with_fake_result()

        reports = database.get_reports_for_user(user["id"])
        assert not reports, "scheduler dry-run should not save a database report"
        preview_path = Path(os.environ["EMAIL_PREVIEW_PATH"])
        assert preview_path.exists(), "scheduler dry-run did not save an email preview artifact"
        assert "Smoke Test Pattern" in preview_path.read_text(encoding="utf-8"), (
            "dry-run preview should include the generated pattern"
        )
        assert run_scheduler_with_fake_result()["competition_intel"]["status"] == "skipped", (
            "fresh intelligence snapshot should skip a second refresh"
        )

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

        original_validate_url = link_validator._validate_url
        original_ddg_search = link_validator.llm.ddg_search
        try:
            def fake_validate_url(url, timeout_seconds=4.0):
                if "broken-ravelry" in url:
                    return False, url, 404
                if "ravelry.com/groups/" in url:
                    return True, url, 200
                if "retry-pattern" in url:
                    return True, url, 200
                if "still-bad" in url:
                    return False, url, 404
                if "valid-pattern" in url:
                    return True, url, 200
                return False, url, 404

            def fake_pattern_ddg(query, max_results=5):
                if "site:ravelry.com/patterns/library" in query and "Broken Bear" in query:
                    return [
                        {"href": "https://www.ravelry.com/groups/still-wrong"},
                        {"href": "https://www.ravelry.com/patterns/library/retry-pattern"},
                    ]
                if "No Match" in query:
                    return [{"href": "https://example.com/still-bad"}]
                return []

            link_validator._validate_url = fake_validate_url
            link_validator.llm.ddg_search = fake_pattern_ddg

            retried = link_validator.validate_patterns([
                {
                    "title": "Broken Bear",
                    "source_site": "ravelry.com",
                    "url": "https://www.ravelry.com/groups/broken-ravelry",
                    "skill_level": "beginner",
                    "project_type": "amigurumi",
                }
            ])
            assert retried[0]["url"] == "https://www.ravelry.com/patterns/library/retry-pattern", (
                "ravelry retry should replace non-library or 404 URLs with a valid library URL"
            )
            assert retried[0]["pattern_cta_label"] == "View Pattern", (
                "successful retry should keep the View Pattern CTA"
            )

            fallback = link_validator.validate_patterns([
                {
                    "title": "No Match",
                    "source_site": "ravelry.com",
                    "url": "https://www.ravelry.com/groups/still-bad",
                    "skill_level": "beginner",
                    "project_type": "amigurumi",
                }
            ])
            assert fallback[0]["url"] == "", "fallback patterns should not keep an invalid direct URL"
            assert fallback[0]["pattern_cta_label"] == "Search Pattern", (
                "failed validation should swap to a Search Pattern fallback CTA"
            )
            assert "site%3Aravelry.com" in fallback[0]["pattern_search_url"], (
                "ravelry fallback search should be scoped to site:ravelry.com"
            )
        finally:
            link_validator._validate_url = original_validate_url
            link_validator.llm.ddg_search = original_ddg_search

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
            {
                "name": "Chunky Yarn",
                "store_name": "LoveCrafts",
                "store_url": "https://www.lovecrafts.com/en-us/p/still-bad",
            },
        ]
        original_material_validate = link_validator._validate_external_material_url
        try:
            def fake_material_validate(url):
                if "lovecrafts.com/en-us/p/still-bad" in url:
                    return False, url, 404, "status=404"
                if "michaels.com/products/hook-example" in url:
                    return False, "https://www.michaels.com/", 200, "unexpected homepage redirect"
                return False, url, 404, "status=404"

            link_validator._validate_external_material_url = fake_material_validate
            material_checked = link_validator.validate_material_links(fake_result["patterns"])
        finally:
            link_validator._validate_external_material_url = original_material_validate

        materials = material_checked[0]["materials"]
        assert "amazon.com/s?k=small+craft+scissors+Fiskars" in materials[0]["affiliate_url"], (
            "scissors link should use Amazon affiliate search query"
        )
        assert "tag=smoketest-20" in materials[0]["affiliate_url"], (
            "scissors affiliate URL should include the Amazon associate tag"
        )
        assert materials[0]["material_cta_label"] == "Shop Materials", (
            "material CTA should use Shop Materials for Amazon fallback links"
        )
        assert "amazon.com/s?k=yarn+needle+set+blunt+tip" in materials[1]["affiliate_url"], (
            "yarn needle link should use Amazon affiliate search query"
        )
        assert "amazon.com/s?k=5mm+crochet+hook+ergonomic+beginner+set" in materials[2]["affiliate_url"], (
            "crochet hook link should fall back to a specific Amazon affiliate query when external validation is low confidence"
        )
        assert materials[2]["material_link_strategy"] == "amazon_affiliate_search", (
            "invalid external materials should prefer Amazon affiliate fallback"
        )
        assert "lovecrafts.com/en-us/search?q=" in materials[3]["affiliate_url"], (
            "LoveCrafts failures should use the LoveCrafts search fallback"
        )
        assert materials[3]["material_link_strategy"] == "lovecrafts_search_fallback", (
            "LoveCrafts failures should use the dedicated search fallback strategy"
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
        assert "Beginner Confidence" in rendered_html, "email HTML should include beginner confidence score"
        assert "Beginner Confidence: High" in rendered_html, "email HTML should render a confidence level"
        assert "<strong>Why:</strong>" in rendered_html, "email HTML should include confidence reason text"
        assert "Likely beginner-friendly" in rendered_html, (
            "confidence reason should use cautious beginner-friendly wording"
        )
        forbidden_guarantees = [
            "anyone can make this",
            "guaranteed",
            "guarantee",
        ]
        lowered_html = rendered_html.lower()
        assert not any(term in lowered_html for term in forbidden_guarantees), (
            "email HTML should not add fake beginner guarantees"
        )
        assert "Start Here" in rendered_html, "email HTML should include quick-start guidance"
        assert "How to Make It" in rendered_html, "email HTML should include guided tutorial steps"
        assert "What to Watch For" in rendered_html, "email HTML should include beginner tips"
        assert "If You Get Stuck" in rendered_html, "email HTML should include a recovery line"
        assert "Help improve future pattern picks" in rendered_html, "email HTML should include feedback prompt"
        assert "Just hit reply" in rendered_html, "feedback prompt should encourage direct replies"
        assert "Real feedback directly shapes what gets added next." in rendered_html, (
            "feedback prompt should explain why replies matter"
        )
        assert "Materials: yarn, hook, and basic tools from the list below." in rendered_html, (
            "guided tutorial should summarize materials in beginner-friendly language"
        )
        assert "Skill: Beginner blankets." in rendered_html, "guided tutorial should summarize skill level"
        assert "Search Tutorial" not in rendered_html, "email HTML should not show tutorial fallback CTA"
        assert "Tutorial</a>" not in rendered_html, "email HTML should not show tutorial CTA when link is invalid"
        search_fallback_html = mailer.build_html(
            user,
            [
                {
                    "title": "Fallback Pattern",
                    "source_site": "ravelry.com",
                    "skill_level": "beginner",
                    "project_type": "blankets",
                    "estimated_time": "1 hour",
                    "why_its_perfect": "Fallback coverage.",
                    "is_free": True,
                    "url": "",
                    "pattern_cta_label": "Search Pattern",
                    "pattern_cta_url": "https://www.google.com/search?q=fallback",
                    "pattern_search_url": "https://www.google.com/search?q=fallback",
                    "materials": [],
                }
            ],
        )
        assert "View Full Pattern</a>" in search_fallback_html, "email HTML should render the primary pattern CTA"
        assert "Start Here" in search_fallback_html, "fallback cards should include quick-start guidance"
        assert "How to Make It" in search_fallback_html, "fallback cards should include guided tutorial steps"
        assert "https://www.google.com/search?q=fallback" in search_fallback_html, (
            "fallback cards should link the primary CTA to the safe pattern search URL"
        )
        assert "What You" in rendered_html and "Quick Buy Links" in rendered_html, (
            "email HTML should use updated materials header"
        )
        assert "Shop Materials" in rendered_html, "email HTML should use the generic materials CTA text"
        assert (
            "This email may contain affiliate links. We may earn a small commission at no extra cost to you."
            in rendered_html
        ), "email HTML should include the affiliate disclosure"

        later_dry_run = run_scheduler_with_fake_result()
        assert later_dry_run["sent_count"] == 0, "scheduler dry-run should not count live sends"
        assert later_dry_run["skipped_count"] >= 1, "scheduler dry-run should leave subscriber send history untouched"

        first_send_result = database.upsert_user(
            name="First Send Tester",
            email="first@example.com",
            skill_level="beginner",
            project_types=["blankets"],
            yarn_weights=["cotton"],
            time_commitment="quick",
            color_preferences="green",
            aesthetic="Cozy",
            budget="$10-$25",
            free_only=True,
            wants_video=True,
            wants_printable=False,
            special_interests="",
        )
        original_run = orchestrator.run
        original_send = mailer.send_report
        try:
            orchestrator.run = lambda current_user: fake_result
            mailer.send_report = lambda current_user, patterns, dry_run_override=None: True
            first_send = scheduler.send_first_report_if_not_sent(
                "first@example.com",
                dry_run_override=False,
            )
            second_send = scheduler.send_first_report_if_not_sent(
                "first@example.com",
                dry_run_override=False,
            )
        finally:
            orchestrator.run = original_run
            mailer.send_report = original_send

        assert first_send["status"] == "sent", "first signup send should send immediately"
        assert second_send["status"] == "first_report_already_sent", (
            "first signup send should not duplicate after last_report_sent is set"
        )
        first_send_reports = database.get_reports_for_user(first_send_result["user_id"])
        assert len(first_send_reports) == 1, "first signup send should save exactly one live report"

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
        assert not database.get_user_by_email(user["email"])["active"], (
            "unsubscribe did not deactivate the target user"
        )

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
