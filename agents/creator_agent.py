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
AWKWARD_COPY_MARKERS = (
    "hats scarves",
    "a practical clothing",
    "main shape",
    "amigurumi-style project",
)

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


def _project_label(project_type: str) -> str:
    labels = {
        "blankets": "blanket",
        "hats_scarves": "scarf",
        "amigurumi": "amigurumi toy",
        "clothing": "wearable layer",
        "bags": "bag",
        "home_decor": "home decor piece",
        "baby": "baby item",
        "holiday": "seasonal piece",
        "accessories": "accessory",
    }
    return labels.get(project_type, project_type.replace("_", " "))


def _description_text(title: str, project_type: str, aesthetic: str) -> str:
    style_note = f" with a {aesthetic.lower()} feel" if aesthetic and aesthetic.lower() != "any" else ""
    descriptions = {
        "blankets": "A row-by-row blanket with an easy repeat, soft drape, and a tidy border finish.",
        "hats_scarves": "A wearable scarf with a straightforward repeat, gentle texture, and a polished edge.",
        "amigurumi": "A compact amigurumi project built in rounds with simple shaping and finishing steps.",
        "clothing": "A relaxed wearable made from easy panels with seaming checkpoints and fit-friendly construction.",
        "bags": "A practical crochet bag with a sturdy body, reinforced handles, and clean finishing details.",
        "home_decor": "A useful home project with simple repeats, crisp edges, and giftable finishing touches.",
        "baby": "A soft baby project with comfortable texture, easy construction, and a gentle finished feel.",
        "holiday": "A seasonal crochet make that stays approachable while still feeling festive and polished.",
        "accessories": "A quick accessory project with simple construction and an easy-to-style finished look.",
    }
    return descriptions.get(project_type, "A practical crochet project with clear shaping and a polished finish.") + style_note


def _description_needs_cleanup(text: str) -> bool:
    normalized = " ".join((text or "").lower().split())
    return not normalized or any(marker in normalized for marker in AWKWARD_COPY_MARKERS)


def _materials_for(project_type: str, yarn_weight: str) -> list[dict]:
    materials_by_project = {
        "blankets": [
            {"name": f"{yarn_weight} yarn", "quantity": "5-7 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "4"},
            {"name": "measuring tape", "quantity": "1"},
        ],
        "hats_scarves": [
            {"name": f"{yarn_weight} yarn", "quantity": "2-3 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "2"},
        ],
        "amigurumi": [
            {"name": f"{yarn_weight} yarn", "quantity": "1-2 skeins"},
            {"name": "smaller crochet hook", "quantity": "1"},
            {"name": "polyfill stuffing", "quantity": "1 bag"},
            {"name": "safety eyes or black yarn for embroidered eyes", "quantity": "1 set"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch marker", "quantity": "1"},
        ],
        "clothing": [
            {"name": f"{yarn_weight} yarn", "quantity": "4-6 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "6"},
            {"name": "measuring tape", "quantity": "1"},
        ],
        "bags": [
            {"name": f"{yarn_weight} yarn", "quantity": "3-4 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "4"},
        ],
        "home_decor": [
            {"name": f"{yarn_weight} yarn", "quantity": "2-4 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "2"},
        ],
        "baby": [
            {"name": f"{yarn_weight} yarn", "quantity": "3-5 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "4"},
        ],
        "holiday": [
            {"name": f"{yarn_weight} yarn", "quantity": "1-3 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "2"},
        ],
        "accessories": [
            {"name": f"{yarn_weight} yarn", "quantity": "1-2 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "2"},
        ],
    }
    return materials_by_project.get(
        project_type,
        [
            {"name": f"{yarn_weight} yarn", "quantity": "2-3 skeins"},
            {"name": "crochet hook", "quantity": "1"},
            {"name": "tapestry needle", "quantity": "1"},
            {"name": "stitch markers", "quantity": "2"},
        ],
    )


def _safe_title(project_type: str, aesthetic: str, index: int) -> str:
    titles_by_project = {
        "blankets": ["Soft Weekend Lap Blanket", "Textured Sofa Throw", "Cozy Stripe Baby Blanket"],
        "hats_scarves": ["Soft Loop Scarf", "Weekend Rib Scarf", "Simple Trail Scarf"],
        "amigurumi": ["Tiny Desk Frog Amigurumi", "Pocket Mushroom Friend", "Mini Sleepy Bear"],
        "clothing": ["Cozy Everyday Shrug", "Simple Layering Vest", "Easy Weekend Cocoon Cardigan"],
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
    if project_type == "blankets":
        return "6mm (J/10)"
    if project_type == "hats_scarves":
        return "5.5mm (I/9)"
    if project_type == "clothing":
        return "5.5mm (I/9)"
    if project_type == "baby":
        return "4.5mm (7)"
    if project_type in {"bags", "home_decor"}:
        return "5mm (H/8)"
    return "5mm (H/8)"


def _gauge_for(project_type: str) -> str:
    gauges = {
        "blankets": "12 sts x 10 rows = 4 inches in pattern",
        "hats_scarves": "14 sts x 12 rows = 4 inches in pattern",
        "amigurumi": "6 sc x 6 rounds = 2 inches",
        "clothing": "13 sts x 10 rows = 4 inches in pattern",
        "bags": "13 sts x 12 rows = 4 inches in pattern",
        "home_decor": "14 sts x 12 rows = 4 inches in pattern",
        "baby": "14 sts x 11 rows = 4 inches in pattern",
        "holiday": "14 sts x 12 rows = 4 inches in pattern",
        "accessories": "14 sts x 12 rows = 4 inches in pattern",
    }
    return gauges.get(project_type, "Make a small swatch and adjust hook size if needed.")


def _finished_size_for(project_type: str) -> str:
    sizes = {
        "blankets": "about 32 x 40 inches",
        "hats_scarves": "about 7 x 60 inches",
        "amigurumi": "about 4-6 inches tall",
        "clothing": "relaxed shrug made from two rectangles; size with a fit check",
        "bags": "about 12 x 14 inches",
        "home_decor": "set of 4 mug rugs, about 4 x 5 inches each",
        "baby": "about 24 x 28 inches",
        "holiday": "4 small giftable pieces",
        "accessories": "made to fit; measure as you go",
    }
    return sizes.get(project_type, "made to fit; measure as you go")


def _fallback_instructions(project_type: str, skill: str) -> str:
    templates = {
        "blankets": [
            "PROJECT OVERVIEW: Work this blanket in rows with a simple repeat and finish with a clean border.",
            "1. Crochet a gauge swatch, then chain a starting width of about 32 inches or your preferred lap-blanket width.",
            "2. Row 1: Work across the chain in your main stitch pattern, keeping the edge stitches relaxed and even.",
            "3. Row 2: Chain to turn, then repeat the same row pattern across. Use stitch markers on the first and last stitch if your edges tend to drift.",
            "4. Continue the row repeat until the blanket measures about 38 to 40 inches long.",
            "5. If you want more texture, add an accent stripe or one textured row every 6 to 8 rows.",
            "6. Add a border of 2 to 3 rounds of single crochet or half double crochet, working 3 stitches in each corner so the edges lie flat.",
            "7. Fasten off, weave in ends, and block lightly so the blanket settles into shape.",
        ],
        "hats_scarves": [
            "PROJECT OVERVIEW: Make a long scarf with a steady row repeat and an easy edging pass.",
            "1. Crochet a gauge swatch, then chain until your foundation measures about 60 inches for a standard scarf length.",
            "2. Row 1: Work across the chain in your chosen stitch pattern, keeping the tension relaxed for good drape.",
            "3. Row 2: Turn, chain to the correct height, and repeat the row pattern across.",
            "4. Continue repeating Row 2 until the scarf measures about 7 inches wide or your preferred width.",
            "5. Check the drape after a few inches; if the fabric feels too stiff, go up a hook size before continuing.",
            "6. Add a final edging row around the scarf, or add short fringe if you want a softer finish.",
            "7. Fasten off, weave in ends, and steam or block lightly so the edges smooth out.",
        ],
        "amigurumi": [
            "PROJECT OVERVIEW: Work the toy in continuous rounds, shape with increases and decreases, then stuff and finish firmly.",
            "1. Start with a magic ring and work 6 single crochet into the ring.",
            "2. Round 2 and beyond: Increase evenly to form the base, then work even rounds to build the body shape.",
            "3. Use a stitch marker at the start of each round so you do not lose your place.",
            "4. Add any color changes or small features before the piece becomes too narrow to handle comfortably.",
            "5. Place safety eyes before closing the head, or embroider the eyes if the finished piece is for a baby or young child.",
            "6. Stuff the shape firmly but evenly, then work decrease rounds to close the opening.",
            "7. Fasten off with a long tail, sew the opening closed, and stitch on any arms, ears, or other small parts securely.",
        ],
        "clothing": [
            "PROJECT OVERVIEW: Build this wearable from easy rectangles, then seam, try on, and refine the fit before finishing.",
            "1. Take a quick measurement across the upper back or around the bust so you can choose a comfortable finished width.",
            "2. Crochet a gauge swatch, then make the first panel as a rectangle using the listed stitch repeat.",
            "3. Repeat the same rectangle for the second panel, checking the length against your shoulder-to-hip preference as you go.",
            "4. Seam the panels along the shoulders and side edges, leaving generous openings for the arms.",
            "5. Try the piece on before finishing the seams so you can adjust the depth, drape, or arm opening if needed.",
            "6. Add edging around the front opening, sleeves, and lower hem with one or two tidy rounds.",
            "7. Weave in ends, block lightly, and do a final fit check before wearing.",
        ],
        "bags": [
            "PROJECT OVERVIEW: Crochet a sturdy bag body, then add handles and reinforce the opening.",
            "1. Start with a rectangle or oval base sized for the finished bag you want.",
            "2. Work the sides evenly, using stitch markers at the corners or side transitions.",
            "3. Continue until the bag body reaches your preferred height, checking that the fabric feels firm enough to hold shape.",
            "4. Create handles by chaining and skipping stitches, or crochet separate straps and sew them on securely.",
            "5. Add one final round around the opening and handles to strengthen the edge.",
            "6. Weave in ends carefully, especially around the strap joins.",
            "7. Block lightly if needed, then test the handles with a small amount of weight before regular use.",
        ],
        "home_decor": [
            "PROJECT OVERVIEW: Work this home decor piece in simple repeats with crisp edges and a tidy finish.",
            "1. Begin with the listed starting chain or center ring, depending on the shape you want.",
            "2. Establish the main stitch repeat in the first few rows or rounds, then keep the count consistent.",
            "3. Use stitch markers to keep corners, edge increases, or round joins easy to track.",
            "4. Continue until the piece reaches the planned dimensions.",
            "5. Add a contrasting edge, hanging loop, or second finishing round if the project benefits from structure.",
            "6. Fasten off, weave in ends, and block so the edges sit cleanly.",
        ],
        "baby": [
            "PROJECT OVERVIEW: Make a soft baby-friendly piece with gentle texture and comfortable finishing.",
            "1. Crochet a gauge swatch and choose a soft, washable yarn before starting.",
            "2. Chain to the listed width, then work the first row in an easy-to-count stitch pattern.",
            "3. Repeat the row pattern evenly, checking the fabric often so it stays soft and flexible.",
            "4. Continue until the piece reaches the intended length for stroller, crib, or nursery use.",
            "5. Add a soft border with rounded corners and no scratchy finishing details.",
            "6. Weave in all ends securely and block lightly before use.",
        ],
        "holiday": [
            "PROJECT OVERVIEW: Work a small seasonal project with simple shaping and a neat finished edge.",
            "1. Start with the listed chain or ring and establish the shape in the first row or round.",
            "2. Keep the stitch repeat compact so the project stays quick and giftable.",
            "3. Add any color changes near the beginning of a row or round for cleaner transitions.",
            "4. Continue until the motif or piece reaches the finished size you want.",
            "5. Add a hanging loop, border, or finishing tie if the project needs one.",
            "6. Weave in ends and block lightly so the shape looks crisp.",
        ],
        "accessories": [
            "PROJECT OVERVIEW: Make a quick accessory with a simple repeat and a polished finish.",
            "1. Measure the area the accessory needs to fit, then crochet a swatch before starting the full piece.",
            "2. Chain to the listed width or circumference and work the first row in pattern.",
            "3. Repeat the main stitch pattern until the piece fits comfortably.",
            "4. Join the ends if needed, then add a narrow edging row to clean up the outline.",
            "5. Weave in ends and block lightly if you want a smoother finish.",
        ],
    }
    steps = list(templates.get(project_type, templates["accessories"]))
    if skill in {"intermediate", "advanced"} and project_type in {"blankets", "hats_scarves", "clothing"}:
        steps.insert(-2, "Optional detail: add one accent stripe, textured section, or shaping row if you want more visual interest.")
    return "\n".join(steps)


def _fallback_notes(project_type: str, skill: str) -> list[str]:
    notes_by_project = {
        "blankets": [
            "Count stitches every few rows so the blanket width stays consistent.",
            "If the edges ripple, check your turning chain and border tension before adding more rows.",
        ],
        "hats_scarves": [
            "Drape matters more than firmness here, so do not crochet the scarf too tightly.",
            "Measure after a few repeats to decide whether you want a narrower or wider scarf.",
        ],
        "amigurumi": [
            "Keep the stitches tight enough that stuffing does not show through.",
            "For toys or child-facing items, embroider details instead of relying on loose plastic parts.",
        ],
        "clothing": [
            "Do a fit check before closing the final seams so the wearable stays comfortable.",
            "A light block before seaming can help panels line up more cleanly.",
        ],
        "bags": [
            "If the bag stretches too easily, switch to a tighter hook or sturdier yarn.",
            "Reinforce the handle joins well because they take the most strain.",
        ],
        "home_decor": [
            "Blocking makes a big difference on flat home pieces and matching sets.",
            "Use markers on corners or repeats if the shape starts to skew.",
        ],
        "baby": [
            "Choose soft, washable yarn and skip scratchy trims or stiff embellishments.",
            "Weave in ends extra securely for anything that will be washed often.",
        ],
        "holiday": [
            "Seasonal projects look cleaner when color changes happen at the edge or round join.",
            "Make one sample first if you want to batch-produce matching gift sets.",
        ],
        "accessories": [
            "A quick fit check halfway through usually saves more time than reworking the whole piece later.",
            "If the fabric feels too dense, go up a hook size for better comfort.",
        ],
    }
    notes = list(notes_by_project.get(project_type, notes_by_project["accessories"]))
    notes.append("Search for the stitch techniques used in the pattern rather than relying on an exact-match tutorial that may not exist.")
    if skill in {"beginner", "intermediate"}:
        notes.append("If the fabric curls or feels stiff, pause and check hook size, stitch count, and tension before continuing.")
    return notes[:4]


def _tutorial_guidance(title: str, project_type: str) -> str:
    guidance = {
        "blankets": f"Search YouTube for: crochet lap blanket row repeat simple border {title}",
        "hats_scarves": f"Search YouTube for: crochet scarf row repeat edging {title}",
        "amigurumi": f"Search YouTube for: amigurumi magic ring invisible decrease stuffing {title}",
        "clothing": f"Search YouTube for: crochet shrug rectangle cardigan seaming fit check {title}",
        "bags": f"Search YouTube for: crochet tote bag base handles sturdy strap {title}",
        "home_decor": f"Search YouTube for: crochet home decor edging blocking {title}",
        "baby": f"Search YouTube for: crochet baby blanket soft border {title}",
        "holiday": f"Search YouTube for: crochet holiday motif edging finishing {title}",
        "accessories": f"Search YouTube for: crochet accessory simple edging fit check {title}",
    }
    return guidance.get(project_type, f"Search YouTube for: crochet {title} tutorial")


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
        "chain the width you want, or start with a magic ring if this is an amigurumi-style project",
    ]
    if normalized in vague_markers:
        return True
    return len([line for line in (instructions or "").splitlines() if line.strip()]) < 5


def _instructions_need_cleanup(project_type: str, instructions: str) -> bool:
    normalized = " ".join((instructions or "").lower().split())
    if _is_vague_instructions(instructions):
        return True
    if any(marker in normalized for marker in AWKWARD_COPY_MARKERS):
        return True
    if project_type != "amigurumi" and "magic ring" in normalized:
        return True
    if project_type == "amigurumi" and "magic ring" not in normalized:
        return True
    if project_type == "blankets" and "border" not in normalized:
        return True
    if project_type == "hats_scarves" and "scarf" not in normalized and "edging" not in normalized:
        return True
    if project_type == "clothing" and "seam" not in normalized and "fit" not in normalized:
        return True
    return False


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
        or f"Designed to match your {skill} skill level and interest in { _project_label(project_type) } projects."
    )
    description = (pattern.get("description") or tagline or _description_text(title, project_type, user.get("aesthetic", ""))).strip()
    if _description_needs_cleanup(description):
        description = _description_text(title, project_type, user.get("aesthetic", ""))
    if _description_needs_cleanup(tagline):
        tagline = description
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
        "hook_size": pattern.get("hook_size") or _hook_for(project_type),
        "gauge": pattern.get("gauge") or _gauge_for(project_type),
        "finished_size": pattern.get("finished_size") or _finished_size_for(project_type),
        "estimated_time": pattern.get("estimated_time") or _default_estimated_time(skill, user.get("time_commitment", "any")),
        "materials": pattern.get("materials") or _materials_for(project_type, yarn_weight),
        "abbreviations": pattern.get("abbreviations") or {"ch": "chain", "sc": "single crochet", "hdc": "half double crochet", "sl st": "slip stitch"},
        "instructions": (
            _fallback_instructions(project_type, skill)
            if _instructions_need_cleanup(project_type, pattern.get("instructions", ""))
            else pattern.get("instructions")
        ),
        "notes": pattern.get("notes") or _fallback_notes(project_type, skill),
        "tutorial_guidance": pattern.get("tutorial_guidance") or _tutorial_guidance(title, project_type),
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
            f"{_project_label(project_type)} projects, with project-specific construction you can follow "
            "without depending on an external pattern page."
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
