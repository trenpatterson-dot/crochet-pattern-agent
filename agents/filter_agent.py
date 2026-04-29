"""
Filter Agent — Crochet Expert

Receives raw candidates from the Search Agent and applies expert crochet judgment:
- Removes low-quality or unclear patterns
- Prefers highly rated or well-reviewed items
- Matches user preferences exactly
- Ranks the top 3 (2 original patterns are created separately by the Creator Agent)
"""

import json
from . import competition_intelligence_agent, llm

SYSTEM = """\
You are a crochet expert.

From the list of patterns provided:
- Remove low-quality or unclear patterns
- Prefer highly rated or well-reviewed items
- Match the user preferences exactly (skill level, style, budget, yarn type, color)
- If user wants free patterns, exclude any paid ones
- If user wants video tutorials, prefer patterns that have them
- If user wants printable patterns, prefer those
- Rank the top 3 best matches

For each of the top 3, return:
- rank (1–3)
- title
- url
- source_site
- skill_level
- project_type
- yarn_weight
- hook_size (your best estimate if not listed)
- estimated_time (e.g. "3–5 hours", "Full weekend")
- why_its_perfect (2–3 sentences: why this is an ideal match for THIS user)
- color_notes (how it fits their color preferences, if relevant)
- is_free (true/false)
- has_video (true/false)
- is_printable (true/false)

Return ONLY valid JSON: {"top_found": [...]}"""


def curate(user: dict, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    selected_test_mode = bool(user.get("_selected_test_mode"))
    projects = ", ".join(user.get("project_types", []))
    yarns = ", ".join(user.get("yarn_weights", [])) or "any"
    colors = user.get("color_preferences", "no preference")
    aesthetic = user.get("aesthetic", "any")
    budget = user.get("budget", "any")
    intel_context = competition_intelligence_agent.build_prompt_context()

    user_msg = f"""User Preferences:
Name: {user['name']}
Skill Level: {user['skill_level']}
Project Types: {projects}
Yarn Type: {yarns}
Time Per Project: {user.get("time_commitment", "any")}
Color Preferences: {colors}
Aesthetic Style: {aesthetic}
Budget for Materials: {budget}
Free Patterns Only: {"Yes" if user.get("free_only") else "No"}
Wants Video Tutorials: {"Yes" if user.get("wants_video") else "No preference"}
Wants Printable Patterns: {"Yes" if user.get("wants_printable") else "No preference"}
Special Interests: {user.get("special_interests") or "none"}

Pattern Candidates to evaluate:
{json.dumps(candidates, indent=2)}

Apply your expert crochet judgment. Remove poor fits. Rank the top 3 found patterns."""

    if intel_context:
        user_msg += (
            "\n\nMarket intelligence to use as a tie-breaker only after user fit, quality, and compliance:"
            f"\n{intel_context}"
        )

    raw = llm.chat(SYSTEM, user_msg, max_tokens=1200 if selected_test_mode else 1800)
    data = llm.parse_json(raw)

    if data and "top_found" in data:
        top3 = data["top_found"]
        print(f"    [Filter Agent] Selected top {len(top3)} found patterns")
        return top3

    print("    [Filter Agent] WARNING: Could not parse top_found")
    return []
