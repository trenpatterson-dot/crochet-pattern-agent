"""
Creator Agent - original crochet pattern designer

Generates original crochet patterns written specifically for the user.
Patterns are calibrated to their exact skill level, aesthetic, yarn preference,
color choices, and project type.
"""

import os
import re

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
      "description": "Short overview of the idea",
      "materials": [{"name": "bulky yarn", "quantity": "3 skeins"}],
      "abbreviations": {"ch": "chain", "sc": "single crochet"},
      "instructions": "Compact, usable instructions",
      "notes": ["Tip 1"],
      "tutorial_guidance": "Search YouTube for: crochet Pattern Name tutorial",
      "color_suggestion": "Soft neutral tones",
      "why_created": "Designed to match the user's preferences",
      "why_it_matches": "Designed to match the user's preferences",
      "difficulty": "beginner",
      "source_type": "original_generated",
      "license_type": "original - personal use free",
      "is_free": true
    }
  ]
}"""


def _default_project_type(user: dict, index: int = 0) -> str:
    project_types = user.get("project_types") or ["accessories"]
    return project_types[index % len(project_types)]


def _default_yarn_weight(user: dict) -> str:
    weights = [value for value in (user.get("yarn_weights") or []) if value and value != "any"]
    return weights[0] if weights else "medium"


def _default_estimated_time(skill: str, time_pref: str) -> str:
    if time_pref == "quick_weekend":
        return "2-4 hours"
    if time_pref == "few_evenings":
        return "4-6 hours"
    if skill == "beginner":
        return "3-5 hours"
    if skill == "advanced":
        return "Weekend project"
    return "4-6 hours"


def _difficulty_label(skill: str) -> str:
    return skill or "beginner"


def _description_text(title: str, project_type: str, aesthetic: str) -> str:
    style_note = f" with a {aesthetic.lower()} feel" if aesthetic and aesthetic.lower() != "any" else ""
    return (
        f"A small, satisfying {project_type.replace('_', ' ')} project{style_note} "
        "with enough structure to follow and enough flexibility to make it yours."
    )


def _materials_for(project_type: str, yarn_weight: str) -> list[dict]:
    base = [
        {"name": f"{yarn_weight} yarn", "quantity": "2-3 skeins"},
        {"name": "crochet hook", "quantity": "1"},
        {"name": "tapestry needle", "quantity": "1"},
        {"name": "stitch markers", "quantity": "4"},
    ]
    if project_type in {"amigurumi", "baby"}:
        base.append({"name": "polyfill stuffing", "quantity": "1 bag"})
    if project_type in {"blankets", "home_decor"}:
        base[0]["quantity"] = "4-6 skeins"
    return base


def _safe_title(project_type: str, aesthetic: str, index: int) -> str:
    titles_by_project = {
        "blankets": ["Soft Weekend Lap Blanket", "Textured Sofa Throw", "Cozy Stripe Baby Blanket"],
        "hats_scarves": ["Ribbed Morning Beanie", "Soft Loop Scarf", "Simple Trail Cowl"],
        "amigurumi": ["Tiny Desk Frog Amigurumi", "Pocket Mushroom Friend", "Mini Sleepy Bear"],
        "clothing": ["Easy Cotton Market Tee", "Simple Layering Vest", "Cozy Everyday Shrug"],
        "bags": ["Easy Cotton Market Tote", "Everyday Drawstring Project Bag", "Textured Book Tote"],
        "home_decor": ["Cozy Holiday Mug Rug Set", "Simple Basket Tray", "Soft Table Mat Duo"],
        "baby": ["Soft Stroller Blanket", "Tiny Bootie Practice Set", "Gentle Nursery Lovey"],
        "holiday": ["Cozy Holiday Mug Rug Set", "Simple Gift Card Sleeve", "Winter Star Garland"],
        "accessories": ["Quick Texture Headband", "Soft Wrist Warmer Set", "Simple Button Cowl"],
    }
    options = titles_by_project.get(project_type, titles_by_project["accessories"])
    return options[index % len(options)]


def _hook_for(project_type: str) -> str:
    if project_type == "amigurumi":
        return "3.5mm (E/4)"
    if project_type in {"blankets", "home_decor"}:
        return "5.5mm (I/9)"
    return "5mm (H/8)"


def _finished_size_for(project_type: str) -> str:
    sizes = {
        "blankets": "about 32 x 40 inches",
        "hats_scarves": "scarf about 6 x 56 inches or beanie to fit",
        "amigurumi": "about 4-6 inches tall",
        "clothing": "made to your measurements",
        "bags": "about 12 x 14 inches",
        "home_decor": "set of 4 mug rugs, about 4 x 5 inches each",
        "baby": "about 24 x 28 inches",
        "holiday": "4 small giftable pieces",
        "accessories": "made to fit; measure as you go",
    }
    return sizes.get(project_type, "made to fit; measure as you go")


def _fallback_instructions(project_type: str, skill: str) -> str:
    project_label = project_type.replace("_", " ")
    steps = [
        f"PROJECT OVERVIEW: Make a practical {project_label} using simple rows or rounds, clean edges, and a finish that still looks polished.",
        "1. Make a small gauge swatch first so your finished size does not surprise you.",
        "2. Chain the width you want, or start with a magic ring if this is an amigurumi-style project.",
        "3. Work the main body in steady rows or rounds, using stitch markers at the edges or round starts.",
        "4. Add texture every few rows with a simple repeat such as one row of single crochet followed by one row of half double crochet.",
        "5. Measure as you go and stop when the piece reaches the size listed for the project.",
        "6. Add a clean border or final round in single crochet to help the edges sit neatly.",
        "7. Fasten off, weave in ends, and block lightly if the fabric needs help relaxing.",
    ]
    if skill in {"intermediate", "advanced"}:
        steps.insert(5, "5. Add one optional accent row, color stripe, or shaping detail if you want a little more interest.")
    return "\n".join(steps[:8])


def _fallback_notes(project_type: str, skill: str) -> list[str]:
    notes = [
        "Keep your first version simple; you can add color changes or texture once the base shape feels right.",
        "Use stitch markers generously so the edges and round starts stay easy to find.",
        "Search YouTube for the stitch names in the instructions rather than a fake exact-pattern video.",
    ]
    if skill in {"beginner", "intermediate"}:
        notes.append("If the fabric curls or feels stiff, pause and check hook size, stitch count, and tension before continuing.")
    if project_type == "amigurumi":
        notes.append("For toys or child-facing items, embroider details instead of using loose small parts.")
    return notes[:4]


def _tutorial_guidance(title: str) -> str:
    return f"Search YouTube or Google for: crochet {title} tutorial"


def _is_generic_title(title: str) -> bool:
    normalized = title.strip().lower()
    if re.search(r"\bidea\s+\d+\b", normalized):
        return True
    return normalized in {"crochet idea", "original crochet idea", "cozy crochet idea"}


def _is_vague_instructions(instructions: str) -> bool:
    normalized = " ".join((instructions or "").lower().split())
    vague_markers = [
        "start with a foundation chain, crochet the main shape, then finish edges and weave in ends",
        "compact, usable instructions",
    ]
    if normalized in vague_markers:
        return True
    return len([line for line in (instructions or "").splitlines() if line.strip()]) < 5


def _normalize_pattern(pattern: dict, user: dict, index: int, *, fallback_mode: bool) -> dict:
    skill = (pattern.get("skill_level") or pattern.get("difficulty") or user.get("skill_level") or "beginner").strip().lower()
    project_type = (pattern.get("project_type") or _default_project_type(user, index)).strip().lower()
    yarn_weight = (pattern.get("yarn_weight") or _default_yarn_weight(user)).strip().lower()
    title = (pattern.get("title") or _safe_title(project_type, user.get("aesthetic", ""), index)).strip()
    if _is_generic_title(title):
        title = _safe_title(project_type, user.get("aesthetic", ""), index)
    tagline = (pattern.get("tagline") or pattern.get("description") or "").strip()
    why_created = (
        pattern.get("why_created")
        or pattern.get("why_it_matches")
        or f"Designed to match your {skill} skill level and interest in {project_type.replace('_', ' ')} projects."
    )
    description = (pattern.get("description") or tagline or _description_text(title, project_type, user.get("aesthetic", ""))).strip()
    normalized = {
        "title": title,
        "tagline": tagline or description,
        "description": description,
        "is_original": True,
        "source_type": "original_generated",
        "source_site": "Original generated idea - created for you" if fallback_mode else "Original - created for you",
        "url": None,
        "pattern_cta_url": "",
        "pattern_cta_label": "",
        "skill_level": skill,
        "difficulty": _difficulty_label(skill),
        "project_type": project_type,
        "yarn_weight": yarn_weight,
        "hook_size": pattern.get("hook_size") or "5mm (H/8)",
        "gauge": pattern.get("gauge") or "Pattern gauge varies; make a small swatch first.",
        "finished_size": pattern.get("finished_size") or "Flexible based on your stitch count",
        "estimated_time": pattern.get("estimated_time") or _default_estimated_time(skill, user.get("time_commitment", "any")),
        "materials": pattern.get("materials") or _materials_for(project_type, yarn_weight),
        "abbreviations": pattern.get("abbreviations") or {"ch": "chain", "sc": "single crochet", "hdc": "half double crochet", "sl st": "slip stitch"},
        "instructions": (
            _fallback_instructions(project_type, skill)
            if _is_vague_instructions(pattern.get("instructions", ""))
            else pattern.get("instructions")
        ),
        "notes": pattern.get("notes") or _fallback_notes(project_type, skill),
        "tutorial_guidance": pattern.get("tutorial_guidance") or _tutorial_guidance(title),
        "video_tutorial": None,
        "color_suggestion": pattern.get("color_suggestion") or (user.get("color_preferences") or "Soft neutral tones"),
        "why_created": why_created,
        "why_it_matches": pattern.get("why_it_matches") or why_created,
        "license_type": "original - personal use free",
        "is_free": True,
        "compliance_note": None,
    }
    return normalized


def _extract_patterns_payload(data):
    if isinstance(data, list):
        return data, "top_level_list"
    if isinstance(data, dict):
        for key in ("original_patterns", "patterns", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value, key
    return None, "missing_pattern_list"


def _parse_creator_output(raw: str):
    data = llm.parse_json(raw)
    if data is None:
        return None, "invalid_json"
    patterns, source_key = _extract_patterns_payload(data)
    if patterns is None:
        return None, f"missing_expected_list:{source_key}"
    return patterns, source_key


def _deterministic_fallback_patterns(user: dict, requested_count: int) -> list[dict]:
    skill = (user.get("skill_level") or "beginner").strip().lower()
    aesthetic = user.get("aesthetic", "")
    base_projects = user.get("project_types") or ["accessories", "home_decor", "baby"]
    patterns = []
    for index in range(requested_count):
        project_type = _default_project_type({"project_types": base_projects}, index)
        title = _safe_title(project_type, aesthetic, index)
        description = _description_text(title, project_type, aesthetic)
        why = (
            f"Designed around your {skill} skill level and interest in "
            f"{project_type.replace('_', ' ')} projects, with a practical shape you can finish "
            "without chasing a long external pattern."
        )
        patterns.append(
            _normalize_pattern(
                {
                    "title": title,
                    "tagline": description,
                    "description": description,
                    "project_type": project_type,
                    "skill_level": skill,
                    "hook_size": _hook_for(project_type),
                    "finished_size": _finished_size_for(project_type),
                    "instructions": _fallback_instructions(project_type, skill),
                    "notes": _fallback_notes(project_type, skill),
                    "why_created": why,
                    "why_it_matches": why,
                },
                user,
                index,
                fallback_mode=True,
            )
        )
    return patterns


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
        "and include tutorial_guidance search text instead of a tutorial URL. "
        "Return JSON only. No markdown. No explanation. No prose before or after the JSON. "
        "Use exactly one top-level object with an original_patterns array."
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
    meta = {
        "requested_count": requested_count,
        "created_count": 0,
        "reason": "ok",
        "fallback_mode": fallback_mode,
    }
    parsed_patterns, parse_source = _parse_creator_output(raw)

    if parsed_patterns is None:
        print(f"    [Creator Agent] WARNING: invalid creator JSON ({parse_source})")
        meta["reason"] = "invalid_json"
    else:
        normalized_patterns = [
            _normalize_pattern(pattern, user, index, fallback_mode=fallback_mode)
            for index, pattern in enumerate(parsed_patterns[:requested_count])
            if isinstance(pattern, dict)
        ]
        if normalized_patterns:
            meta["created_count"] = len(normalized_patterns)
            meta["parse_source"] = parse_source
            print(f"    [Creator Agent] Designed {len(normalized_patterns)} original patterns for {name}")
            if return_meta:
                return normalized_patterns, meta
            return normalized_patterns
        print("    [Creator Agent] WARNING: creator parsed 0 usable items")
        meta["reason"] = "parsed_zero_items"

    if selected_test_mode and fallback_mode:
        fallback_patterns = _deterministic_fallback_patterns(user, requested_count)
        meta["reason"] = "deterministic_fallback_used"
        meta["created_count"] = len(fallback_patterns)
        print(f"    [Creator Agent] Deterministic fallback used for {len(fallback_patterns)} original ideas")
        if return_meta:
            return fallback_patterns, meta
        return fallback_patterns

    if meta["reason"] == "parsed_zero_items":
        print("    [Creator Agent] WARNING: Creator returned 0 usable pattern items")
    else:
        print("    [Creator Agent] WARNING: Could not parse original patterns")
    if return_meta:
        return [], meta
    return []
