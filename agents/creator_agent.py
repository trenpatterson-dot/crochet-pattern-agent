"""
Creator Agent - original crochet pattern designer

Generates original crochet patterns written specifically for the user.
Patterns are calibrated to their exact skill level, aesthetic, yarn preference,
color choices, and project type.
"""

import os

from . import llm

DEFAULT_PATTERN_COUNT = max(0, int(os.getenv("ORIGINAL_PATTERN_COUNT", "1")))
DEFAULT_INSTRUCTION_DETAIL = os.getenv("ORIGINAL_PATTERN_DETAIL", "compact").strip().lower()

SYSTEM = """\
You are an experienced crochet pattern designer. Your job is to write original crochet
patterns tailored specifically to one user's preferences.

Each pattern must include:
- a fitting name
- skill level
- hook size and yarn weight
- gauge
- finished size
- a concise materials list
- abbreviations
- instructions
- notes
- a color suggestion
- why this pattern was designed for the user

Keep the output compact, practical, and consistent.
Return ONLY valid JSON:
{
  "original_patterns": [
    {
      "title": "Pattern Name",
      "tagline": "One-line description",
      "is_original": true,
      "skill_level": "beginner",
      "project_type": "blanket",
      "yarn_weight": "bulky",
      "hook_size": "8mm (L/11)",
      "gauge": "8 sts x 8 rows = 4 inches",
      "finished_size": "30 x 36 inches",
      "estimated_time": "4-6 hours",
      "materials": [{"name": "bulky yarn", "quantity": "3 skeins"}],
      "abbreviations": {"ch": "chain", "sc": "single crochet"},
      "instructions": "Compact, usable instructions",
      "notes": ["Tip 1"],
      "tutorial_guidance": "Search YouTube for: crochet Pattern Name tutorial",
      "color_suggestion": "Soft neutral tones",
      "why_created": "Designed to match the user's preferences",
      "license_type": "original - personal use free",
      "is_free": true
    }
  ]
}"""


def create(
    user: dict,
    pattern_count: int | None = None,
    fallback_mode: bool = False,
    return_meta: bool = False,
):
    requested_count = DEFAULT_PATTERN_COUNT if pattern_count is None else max(0, int(pattern_count))
    if requested_count <= 0:
        print("    [Creator Agent] Skipped original pattern generation")
        meta = {
            "requested_count": requested_count,
            "created_count": 0,
            "reason": "pattern_generation_disabled",
            "fallback_mode": fallback_mode,
        }
        if return_meta:
            return [], meta
        return []

    selected_test_mode = bool(user.get("_selected_test_mode"))
    name = user["name"]
    skill = user["skill_level"]
    projects = ", ".join(user.get("project_types", ["any"]))
    yarns = ", ".join(user.get("yarn_weights", [])) or "any weight"
    colors = user.get("color_preferences", "no preference")
    aesthetic = user.get("aesthetic", "any")
    time_pref = user.get("time_commitment", "any")
    interests = user.get("special_interests", "")

    instruction_note = (
        "Keep instructions compact and practical: group repeats and avoid extra prose."
        if DEFAULT_INSTRUCTION_DETAIL == "compact"
        else "Write detailed instructions."
    )

    fallback_note = (
        "These are fallback originals because sourced web patterns were unavailable. "
        "Label them clearly as original generated ideas, do not invent external pattern links, "
        "and include tutorial_guidance search text instead of a tutorial URL."
        if fallback_mode
        else ""
    )

    user_msg = f"""Design {requested_count} original crochet pattern(s) for this person:

Name: {name}
Skill Level: {skill}
Project Types: {projects}
Yarn Weight Preference: {yarns}
Color Preferences: {colors}
Aesthetic Style: {aesthetic}
Time Per Project: {time_pref}
Special Interests: {interests or "none"}

{instruction_note}
{fallback_note}
Keep each pattern personal, mathematically consistent, and easy to follow."""

    raw = llm.chat(SYSTEM, user_msg, max_tokens=1600 if selected_test_mode else 2800)
    data = llm.parse_json(raw)
    meta = {
        "requested_count": requested_count,
        "created_count": 0,
        "reason": "ok",
        "fallback_mode": fallback_mode,
    }

    if data and "original_patterns" in data:
        patterns = data["original_patterns"][:requested_count]
        for pattern in patterns:
            pattern["is_original"] = True
            pattern["url"] = None
            pattern["source_site"] = (
                "Original generated idea - created for you"
                if fallback_mode
                else "Original - created for you"
            )
            pattern["compliance_note"] = None
            pattern["video_tutorial"] = None
            pattern["tutorial_guidance"] = (
                pattern.get("tutorial_guidance")
                or f"Search YouTube or Google for: crochet {pattern.get('title', 'pattern')} tutorial"
            )
        meta["created_count"] = len(patterns)
        print(f"    [Creator Agent] Designed {len(patterns)} original patterns for {name}")
        if return_meta:
            return patterns, meta
        return patterns

    print("    [Creator Agent] WARNING: Could not parse original patterns")
    meta["reason"] = "parse_failed"
    if return_meta:
        return [], meta
    return []
