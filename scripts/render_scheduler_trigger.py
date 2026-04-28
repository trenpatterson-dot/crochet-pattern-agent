import base64
import os
import sys
from urllib import error, request


def _build_url() -> str:
    base_url = os.getenv("SCHEDULER_TRIGGER_BASE_URL", "").strip()
    if not base_url:
        raise RuntimeError("SCHEDULER_TRIGGER_BASE_URL is not configured.")
    if not base_url.startswith(("http://", "https://")):
        base_url = f"http://{base_url}"
    return f"{base_url.rstrip('/')}/internal/scheduler/run"


def main() -> int:
    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    if not admin_password:
        raise RuntimeError("ADMIN_PASSWORD is not configured.")

    token = base64.b64encode(f"render-cron:{admin_password}".encode("utf-8")).decode("ascii")
    req = request.Request(_build_url(), method="POST")
    req.add_header("Authorization", f"Basic {token}")

    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            print(f"Scheduler trigger status: {resp.status}")
            if body:
                print(body)
            return 0 if resp.status in (200, 202) else 1
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        print(f"Scheduler trigger failed: {exc.code}")
        if body:
            print(body)
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Scheduler trigger error: {exc}", file=sys.stderr)
        raise SystemExit(1)
