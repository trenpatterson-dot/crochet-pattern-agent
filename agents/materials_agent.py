"""
Materials Agent - supply specialist

For each top pattern:
- finds a complete materials list with quantities
- links materials to reputable craft stores when available
- finds a YouTube tutorial video when available
- estimates total cost versus the user's budget
"""

import json

from . import llm

TRUSTED_STORES = [
    "lionbrand.com",
    "yarnspirations.com",
    "lovecrafts.com",
    "michaels.com",
    "joann.com",
    "purlsoho.com",
]

SYSTEM = f"""\
You are a crochet supply specialist. For each pattern provided:

1. List all materials needed, including yarn, hook size, and notions.
2. Add a purchase link from a reputable craft store when one is clearly available:
   {", ".join(TRUSTED_STORES)}
3. Estimate the total material cost in USD.
4. Include one YouTube tutorial video if a relevant tutorial is available.

Return ONLY valid JSON in this format:
{{
  "enriched": [
    {{
      "title": "Pattern title",
      "materials": [
        {{
          "name": "Item name",
          "store_name": "Store",
          "store_url": "https://...",
          "approx_price": "$8.99"
        }}
      ],
      "total_cost_estimate": "$15-$25",
      "video_tutorial": {{"title": "Tutorial title", "url": "https://youtube.com/watch?v=..."}} or null
    }}
  ]
}}"""


def _merge_pattern_data(base_pattern: dict, enriched_pattern: dict, youtube_by_pattern: dict[str, dict]) -> dict:
    normalized = dict(base_pattern)
    normalized.update(enriched_pattern)
    normalized["materials"] = normalized.get("materials") or []
    normalized["total_cost_estimate"] = normalized.get("total_cost_estimate") or "Unknown"

    title = normalized.get("title", "")
    if not normalized.get("video_tutorial") and title in youtube_by_pattern:
        normalized["video_tutorial"] = youtube_by_pattern[title]

    return normalized


def enrich(user: dict, patterns: list[dict]) -> list[dict]:
    if not patterns:
        return []

    budget = user.get("budget", "no limit")
    wants_video = user.get("wants_video", True)

    user_msg = f"""Enrich these {len(patterns)} crochet patterns with materials, store links, and tutorials.

User's budget for materials: {budget}
User wants video tutorials: {"Yes" if wants_video else "No"}

Patterns to enrich:
{json.dumps(patterns, indent=2)}

For each pattern: list every material needed, estimate total cost, and
{"include a YouTube tutorial when available" if wants_video else "set video_tutorial to null"}."""

    yt_results = []
    for pattern in patterns:
        query = f"crochet {pattern.get('title', '')} tutorial youtube"
        hits = llm.ddg_search(query, max_results=3)
        for hit in hits:
            if "youtube.com/watch" in hit.get("href", ""):
                yt_results.append(
                    {
                        "pattern": pattern.get("title"),
                        "url": hit.get("href"),
                        "title": hit.get("title"),
                    }
                )
                break

    if yt_results:
        user_msg += f"\n\nYouTube results:\n{json.dumps(yt_results, indent=2)}"

    youtube_by_pattern = {
        item["pattern"]: {"title": item["title"], "url": item["url"]}
        for item in yt_results
    }

    raw = llm.chat(SYSTEM, user_msg, use_web_search=False, max_tokens=3500)
    data = llm.parse_json(raw)

    if data and "enriched" in data:
        original_by_title = {
            pattern.get("title", "").strip().lower(): pattern for pattern in patterns
        }
        enriched = []
        for item in data["enriched"]:
            key = item.get("title", "").strip().lower()
            base_pattern = original_by_title.get(key, {})
            enriched.append(_merge_pattern_data(base_pattern, item, youtube_by_pattern))
        print(f"    [Materials Agent] Enriched {len(enriched)} patterns")
        return enriched

    fallback = [_merge_pattern_data(item, {}, youtube_by_pattern) for item in patterns]
    print("    [Materials Agent] WARNING: Could not parse enriched JSON - returning fallback enrichment")
    return fallback
