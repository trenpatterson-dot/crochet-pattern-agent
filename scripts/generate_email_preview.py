import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    os.environ.setdefault("EMAIL_DRY_RUN", "true")

    import database
    import mailer

    database.init_db()
    users = database.get_active_users()
    if not users:
        print("No active subscribers available for preview.", file=sys.stderr)
        return 1

    user = next((u for u in users if u["email"] == "smoke@example.com"), users[0])
    reports = database.get_reports_for_user(user["id"], limit=1)
    if not reports:
        print(f"No saved reports found for {user['email']}.", file=sys.stderr)
        return 1

    patterns = json.loads(reports[0]["patterns_json"])["patterns"]
    html = mailer.build_html(user, patterns)

    preview_dir = ROOT / "logs"
    preview_dir.mkdir(exist_ok=True)
    preview_path = preview_dir / "email_preview_latest.html"
    preview_path.write_text(html, encoding="utf-8")

    print(preview_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
