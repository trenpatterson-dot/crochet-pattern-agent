"""
Compliance Agent - legal and licensing verifier
"""

import json

from . import llm

TRUSTED_SITES = {
    "ravelry.com",
    "lovecrafts.com",
    "allfreecrochet.com",
    "yarnspirations.com",
    "lionbrand.com",
    "garnstudio.com",
    "thesprucecrafts.com",
    "redheart.com",
    "purlsoho.com",
}

SYSTEM = """\
You review crochet patterns for newsletter safety.

Check only patterns that are not from the trusted domain list.
We link to patterns, we do not reproduce them.

Return ONLY valid JSON:
{
  "results": [
    {
      "title": "...",
      "verdict": "approved" or "approved_with_note" or "flagged" or "rejected",
      "license_type": "free / personal use / paid / unknown",
      "designer_credited": true,
      "compliance_note": "Brief note or null",
      "rejection_reason": "Reason or null"
    }
  ],
  "summary": "One sentence summary"
}"""


def _domain(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def verify(patterns: list[dict]) -> list[dict]:
    if not patterns:
        return []

    fast_approved = []
    needs_review = []

    for pattern in patterns:
        domain = _domain(pattern.get("url", ""))
        if domain in TRUSTED_SITES:
            pattern["license_type"] = pattern.get("license_type", "unknown")
            pattern["designer_credited"] = pattern.get("designer_credited", True)
            fast_approved.append(pattern)
        else:
            pattern["_domain_warning"] = f"Domain '{domain}' is not on the trusted sites list"
            needs_review.append(pattern)

    if not needs_review:
        print(f"    [Compliance Agent] Fast-path approved {len(fast_approved)}/{len(patterns)} patterns by trusted domain")
        return fast_approved

    patterns_json = json.dumps(needs_review, indent=2)
    user_msg = f"""Review these {len(needs_review)} crochet patterns for compliance and legal safety.

Trusted source domains: {", ".join(sorted(TRUSTED_SITES))}

Patterns to review:
{patterns_json}

Check source legitimacy, licensing terms, and designer attribution.
Return concise JSON verdicts only."""

    raw = llm.chat(SYSTEM, user_msg, use_web_search=False, max_tokens=1800)
    data = llm.parse_json(raw)

    if not data or "results" not in data:
        print("    [Compliance Agent] WARNING: Could not parse response - passing flagged items through with caution")
        for pattern in needs_review:
            pattern["compliance_note"] = "Could not fully verify - link with caution"
        return fast_approved + needs_review

    results = data["results"]
    summary = data.get("summary", "")
    print(f"    [Compliance Agent] {summary}")

    verdict_map = {result.get("title", "").lower(): result for result in results}
    approved = list(fast_approved)

    for pattern in needs_review:
        key = pattern.get("title", "").lower()
        result = verdict_map.get(key)

        if not result:
            pattern["compliance_note"] = "Could not verify - link with caution"
            approved.append(pattern)
            continue

        verdict = result.get("verdict", "approved")
        note = result.get("compliance_note")
        reason = result.get("rejection_reason")

        if verdict == "rejected":
            print(f"    [Compliance Agent] REJECTED: {pattern.get('title')} - {reason}")
            continue

        if verdict in ("approved_with_note", "flagged") and note:
            pattern["compliance_note"] = note
            print(f"    [Compliance Agent] {verdict.upper()}: {pattern.get('title')} - {note}")

        pattern["license_type"] = result.get("license_type", "unknown")
        pattern["designer_credited"] = result.get("designer_credited", True)
        approved.append(pattern)

    print(f"    [Compliance Agent] {len(approved)}/{len(patterns)} patterns approved")
    return approved
