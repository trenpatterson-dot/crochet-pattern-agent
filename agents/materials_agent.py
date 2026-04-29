"""
Materials Agent - supply specialist

For each top pattern:
- finds a complete materials list with quantities
- links materials to reputable craft stores when available
- finds a YouTube tutorial video when available
- avoids price claims in output
"""

import json

from . import competition_intelligence_agent, llm

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
3. Do not include material prices.
4. Do not include total cost estimates.
5. Include one YouTube tutorial video if a relevant tutorial is available.

Return ONLY valid JSON in this format:
{{
  "enriched": [
    {{
      "title": "Pattern title",
      "materials": [
        {{
          "name": "Item name",
          "store_name": "Store",
          "store_url": "https://..."
        }}
      ],
      "total_cost_estimate": "",
      "video_tutorial": {{"title": "Tutorial title", "url": "https://youtube.com/watch?v=..."}} or null
    }}
  ]
}}"""


def _merge_pattern_data(base_pattern: dict, enriched_pattern: dict, youtube_by_pattern: dict[str, list[dict]]) -> dict:
    normalized = dict(base_pattern)
    normalized.update(enriched_pattern)
    normalized["materials"] = normalized.get("materials") or []
    normalized["total_cost_estimate"] = ""

    title = normalized.get("title", "")
    candidates = list(youtube_by_pattern.get(title, []))
    primary = normalized.get("video_tutorial")
    if primary and primary.get("url"):
        seen = {item.get("url") for item in candidates}
        if primary.get("url") not in seen:
            candidates.insert(0, primary)
    if not primary and candidates:
        normalized["video_tutorial"] = candidates[0]
    normalized["tutorial_candidates"] = candidates

    return normalized


def enrich(user: dict, patterns: list[dict], return_meta: bool = False):
    if not patterns:
        meta = {
            "input_count": 0,
            "enriched_count": 0,
            "reason": "no_input_patterns",
        }
        if return_meta:
            return [], meta
        return []

    selected_test_mode = bool(user.get("_selected_test_mode"))
    budget = user.get("budget", "no limit")
    wants_video = user.get("wants_video", True)
    intel_context = competition_intelligence_agent.build_prompt_context()

    user_msg = f"""Enrich these {len(patterns)} crochet patterns with materials, store links, and tutorials.

User's budget for materials: {budget}
User wants video tutorials: {"Yes" if wants_video else "No"}

Patterns to enrich:
{json.dumps(patterns, indent=2)}

For each pattern: list every material needed, do not include prices or total costs, and
{"include a YouTube tutorial when available" if wants_video else "set video_tutorial to null"}."""

    if intel_context:
        user_msg += (
            "\n\nUse this competition intelligence to prioritize likely buy-ready materials, kit components, "
            "and beginner-friendly notions when they genuinely fit the pattern:\n"
            f"{intel_context}"
        )

    yt_results = []
    for pattern in patterns:
        query = f"crochet {pattern.get('title', '')} tutorial youtube"
        hits = llm.ddg_search(query, max_results=3 if selected_test_mode else 6)
        found_for_pattern = 0
        for hit in hits:
            href = hit.get("href", "")
            if "youtube.com/watch" in href or "youtu.be/" in href or "youtube.com/shorts/" in href:
                yt_results.append(
                    {
                        "pattern": pattern.get("title"),
                        "url": href,
                        "title": hit.get("title"),
                    }
                )
                found_for_pattern += 1
                if found_for_pattern >= 3:
                    break

    if yt_results:
        user_msg += f"\n\nYouTube results:\n{json.dumps(yt_results, indent=2)}"

    youtube_by_pattern: dict[str, list[dict]] = {}
    for item in yt_results:
        youtube_by_pattern.setdefault(item["pattern"], [])
        urls = {entry.get("url") for entry in youtube_by_pattern[item["pattern"]]}
        if item["url"] not in urls:
            youtube_by_pattern[item["pattern"]].append(
                {"title": item["title"], "url": item["url"]}
            )

    raw = llm.chat(
        SYSTEM,
        user_msg,
        use_web_search=False,
        max_tokens=1800 if selected_test_mode else 3500,
    )
    data = llm.parse_json(raw)
    meta = {
        "input_count": len(patterns),
        "enriched_count": 0,
        "reason": "ok",
    }

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
        meta["enriched_count"] = len(enriched)
        if return_meta:
            return enriched, meta
        return enriched

    fallback = [_merge_pattern_data(item, {}, youtube_by_pattern) for item in patterns]
    print("    [Materials Agent] WARNING: Could not parse enriched JSON - returning fallback enrichment")
    meta["enriched_count"] = len(fallback)
    meta["reason"] = "parse_failed_fallback"
    if return_meta:
        return fallback, meta
    return fallback
