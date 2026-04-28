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
      "color_suggestion": "Soft neutral tones",
      "why_created": "Designed to match the user's preferences",
      "license_type": "original - personal use free",
      "is_free": true
    }
  ]
}"""


def create(user: dict) -> list[dict]:
    if DEFAULT_PATTERN_COUNT <= 0:
        print("    [Creator Agent] Skipped original pattern generation")
        return []

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

    user_msg = f"""Design {DEFAULT_PATTERN_COUNT} original crochet pattern(s) for this person:

Name: {name}
Skill Level: {skill}
Project Types: {projects}
Yarn Weight Preference: {yarns}
Color Preferences: {colors}
Aesthetic Style: {aesthetic}
Time Per Project: {time_pref}
Special Interests: {interests or "none"}

{instruction_note}
Keep each pattern personal, mathematically consistent, and easy to follow."""

    raw = llm.chat(SYSTEM, user_msg, max_tokens=2800)
    data = llm.parse_json(raw)

    if data and "original_patterns" in data:
        patterns = data["original_patterns"][:DEFAULT_PATTERN_COUNT]
        for pattern in patterns:
            pattern["is_original"] = True
            pattern["url"] = None
            pattern["source_site"] = "Original - created for you"
            pattern["compliance_note"] = None
        print(f"    [Creator Agent] Designed {len(patterns)} original patterns for {name}")
        return patterns

    print("    [Creator Agent] WARNING: Could not parse original patterns")
    return []
