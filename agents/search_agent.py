"""
Search Agent — finds 10-15 raw pattern candidates from trusted crochet sites.
Does not rank or filter — just gathers candidates for the Filter Agent to review.
"""

import json
from . import competition_intelligence_agent, llm

TRUSTED_SITES = [
    "ravelry.com", "lovecrafts.com", "allfreecrochet.com",
    "yarnspirations.com", "lionbrand.com", "garnstudio.com",
    "thesprucecrafts.com", "redheart.com", "purlsoho.com",
]

SEARCH_SEED_SITES = [
    "ravelry.com/patterns/library",
    "allfreecrochet.com",
    "yarnspirations.com",
]

SYSTEM = f"""\
You are a crochet pattern researcher. Search trusted crochet sites ONLY: {", ".join(TRUSTED_SITES)}

Find 8 raw pattern candidates matching the user's preferences. Do NOT rank or filter — \
that is done by the crochet expert in the next step. Just gather candidates.

For each pattern return:
- title
- url (must be from a trusted site above)
- source_site
- skill_level (beginner / intermediate / advanced)
- project_type
- yarn_weight
- color_notes (if mentioned)
- rating (e.g. "4.8/5 stars" — if visible on the page)
- is_free (true/false)
- has_video (true/false — if a video tutorial is linked)
- is_printable (true/false — if a printable PDF version exists)
- snippet (1-2 sentence description)

Return ONLY valid JSON: {{"candidates": [...]}}"""


def find_candidates(user: dict) -> list[dict]:
    selected_test_mode = bool(user.get("_selected_test_mode"))
    projects = ", ".join(user["project_types"])
    skill = user["skill_level"]
    colors = user.get("color_preferences", "")
    aesthetic = user.get("aesthetic", "")
    yarn = ", ".join(user.get("yarn_weights", [])) or "any"
    free_note = "User wants FREE patterns only." if user.get("free_only") else ""
    video_note = "User wants patterns with video tutorials." if user.get("wants_video") else ""
    print_note = "User wants printable patterns." if user.get("wants_printable") else ""
    interests = user.get("special_interests", "")
    budget = user.get("budget", "")
    intel_context = competition_intelligence_agent.build_prompt_context()

    user_msg = f"""Search for crochet patterns matching these preferences:

Skill Level: {skill}
Project Types: {projects}
Yarn Type: {yarn}
Time Per Project: {user.get("time_commitment", "any")}
Color Preferences: {colors or "no preference"}
Aesthetic Style: {aesthetic or "any"}
Budget for Materials: {budget or "no limit"}
{free_note}
{video_note}
{print_note}
{f"Special Interests: {interests}" if interests else ""}

Find 8 diverse candidates from trusted crochet sites."""

    if intel_context:
        user_msg += (
            "\n\nUse this market intelligence as a secondary ranking signal when choosing "
            "which pattern themes to search first. Keep user fit and trusted-site sourcing as the primary rule.\n"
            f"{intel_context}"
        )

    raw_results = []
    seed_sites = SEARCH_SEED_SITES[:2] if selected_test_mode else SEARCH_SEED_SITES
    ddg_max_results = 2 if selected_test_mode else 4
    chat_max_tokens = 1200 if selected_test_mode else 2500
    for site in seed_sites:
        q = f"{skill} {projects} crochet pattern {colors} site:{site}"
        raw_results.extend(llm.ddg_search(q, max_results=ddg_max_results))

    if raw_results:
        context = json.dumps([
            {"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
            for r in raw_results
        ], indent=2)
        user_msg += f"\n\nWeb search results to draw from when useful:\n{context}"

    raw = llm.chat(SYSTEM, user_msg, use_web_search=False, max_tokens=chat_max_tokens)
    data = llm.parse_json(raw)

    if data and "candidates" in data:
        candidates = data["candidates"]
        print(f"    [Search Agent] Found {len(candidates)} candidates")
        return candidates

    print("    [Search Agent] WARNING: Could not parse candidates")
    return []
