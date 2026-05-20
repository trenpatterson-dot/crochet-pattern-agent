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
- a fitting project title
- project overview
- skill level
- hook size and yarn weight
- gauge guidance
- finished size estimate
- a concise materials list
- abbreviations
- exact stitch types used
- starting chain count or round setup
- a detailed Pattern Instructions section with row-by-row or round-by-round instructions
- stitch counts for each row or round where appropriate
- finishing steps
- pattern notes
- beginner tips
- a color suggestion
- why this pattern was designed for the user

Do not rely on vague-only instructions such as "repeat until it fits", "work in pattern",
"continue as needed", or "shape as desired" unless the same instruction also gives exact
row or round guidance and stitch counts.

For flat projects, instructions must use this shape:
Pattern Instructions:
Row 1:
Row 2:
Rows 3-10:
Final row:
Finishing:

For round or amigurumi projects, instructions must use this shape:
Pattern Instructions:
Round 1:
Round 2:
Rounds 3-6:
Stuff/shape:
Finish:

Keep the output practical, specific, and consistent.
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
      "instructions": "Pattern Instructions:\nRow 1: sc in second ch from hook and across. (20 sts)\nRow 2: ch 1, turn, sc across. (20 sts)\nRows 3-10: repeat Row 2. (20 sts)\nFinal row: sl st across for a firm edge. (20 sts)\nFinishing: fasten off and weave in ends.",
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
            "PROJECT OVERVIEW: Work a small lap blanket in straight rows with single crochet and half double crochet texture.",
            "EXACT STITCHES USED: ch, sc, hdc, sl st.",
            "STARTING CHAIN: ch 82.",
            "Pattern Instructions:",
            "Row 1: sc in second ch from hook and in each ch across. (81 sts)",
            "Row 2: ch 1, turn, sc in first st, hdc across to last st, sc in last st. (81 sts)",
            "Rows 3-52: repeat Row 2, counting 81 sts at the end of every row.",
            "Final row: ch 1, turn, sl st loosely across to firm the edge. (81 sts)",
            "Finishing: ch 1, work 1 round of sc around all edges, placing 3 sc in each corner; join with sl st, fasten off, weave in ends, and block flat.",
        ],
        "hats_scarves": [
            "PROJECT OVERVIEW: Make a beginner scarf in long rows with a clean single crochet edge and half double crochet body.",
            "EXACT STITCHES USED: ch, sc, hdc, sl st.",
            "STARTING CHAIN: ch 142.",
            "Pattern Instructions:",
            "Row 1: hdc in third ch from hook and in each ch across. (140 sts)",
            "Row 2: ch 2, turn, hdc across. (140 sts)",
            "Rows 3-12: repeat Row 2 for a scarf about 7 inches wide. (140 sts each row)",
            "Final row: ch 1, turn, sc across for a tidy edge. (140 sts)",
            "Finishing: fasten off, weave in ends, and block lightly so the scarf edges relax.",
        ],
        "amigurumi": [
            "PROJECT OVERVIEW: Crochet a small rounded amigurumi body in continuous single crochet rounds.",
            "EXACT STITCHES USED: magic ring, sc, inc, dec, sl st.",
            "ROUND SETUP: use a stitch marker for the first stitch of each round.",
            "Pattern Instructions:",
            "Round 1: 6 sc in magic ring. (6 sts)",
            "Round 2: inc around. (12 sts)",
            "Rounds 3-6: sc around. (12 sts each round)",
            "Round 7: [sc, dec] around. (8 sts)",
            "Stuff/shape: add a small amount of stuffing and shape the body evenly.",
            "Finish: dec around until closed, sl st to finish, fasten off, and weave the tail through the final stitches.",
        ],
        "clothing": [
            "PROJECT OVERVIEW: Make two simple rectangle panels, seam them into a loose shrug, and finish with single crochet edging.",
            "EXACT STITCHES USED: ch, hdc, sc, sl st.",
            "STARTING CHAIN: ch 44 for each panel.",
            "Pattern Instructions:",
            "Row 1: hdc in third ch from hook and across. (42 sts)",
            "Row 2: ch 2, turn, hdc across. (42 sts)",
            "Rows 3-34: repeat Row 2 for the first rectangle. (42 sts each row)",
            "Final row: ch 1, turn, sc across. (42 sts)",
            "Finishing: make a second matching panel, seam 12 stitches at each shoulder, seam side edges leaving 8 inches for each arm opening, then work 1 round of sc around openings.",
        ],
        "bags": [
            "PROJECT OVERVIEW: Crochet a sturdy tote from a rectangular base, then build the sides in joined rounds.",
            "EXACT STITCHES USED: ch, sc, hdc, sl st.",
            "STARTING CHAIN: ch 31 for the base.",
            "Pattern Instructions:",
            "Row 1: sc in second ch from hook and across. (30 sts)",
            "Rows 2-10: ch 1, turn, sc across to make the base rectangle. (30 sts each row)",
            "Round 1: sc evenly around the base, placing 3 sc in each corner; join with sl st. (84 sts)",
            "Rounds 2-18: ch 2, hdc around; join with sl st. (84 sts each round)",
            "Final row: ch 1, sc around the top edge; join with sl st. (84 sts)",
            "Finishing: make two 18-inch straps with rows of sc, sew them 4 inches in from each side, and reinforce each join with extra stitches.",
        ],
        "home_decor": [
            "PROJECT OVERVIEW: Make a flat mug rug or table mat with rows of single crochet and a neat border.",
            "EXACT STITCHES USED: ch, sc, hdc, sl st.",
            "STARTING CHAIN: ch 18.",
            "Pattern Instructions:",
            "Row 1: sc in second ch from hook and across. (17 sts)",
            "Row 2: ch 2, turn, hdc across. (17 sts)",
            "Rows 3-12: repeat Row 2. (17 sts each row)",
            "Final row: ch 1, turn, sc across. (17 sts)",
            "Finishing: sc evenly around all four sides, placing 3 sc in each corner; join with sl st, fasten off, and block flat.",
        ],
        "baby": [
            "PROJECT OVERVIEW: Crochet a small baby blanket with soft single crochet edges and easy half double crochet rows.",
            "EXACT STITCHES USED: ch, sc, hdc, sl st.",
            "STARTING CHAIN: ch 62.",
            "Pattern Instructions:",
            "Row 1: sc in second ch from hook and across. (61 sts)",
            "Row 2: ch 2, turn, hdc across. (61 sts)",
            "Rows 3-36: repeat Row 2, keeping the fabric soft and flexible. (61 sts each row)",
            "Final row: ch 1, turn, sc across. (61 sts)",
            "Finishing: work 1 round of sc around the blanket, placing 3 sc in each corner; join with sl st, fasten off, and weave in ends securely.",
        ],
        "holiday": [
            "PROJECT OVERVIEW: Make a small seasonal rectangle that can become a mug rug, gift tag, or ornament pocket.",
            "EXACT STITCHES USED: ch, sc, hdc, sl st.",
            "STARTING CHAIN: ch 16.",
            "Pattern Instructions:",
            "Row 1: sc in second ch from hook and across. (15 sts)",
            "Row 2: ch 2, turn, hdc across. (15 sts)",
            "Rows 3-8: repeat Row 2, changing color at the start of Row 5 if desired. (15 sts each row)",
            "Final row: ch 1, turn, sc across. (15 sts)",
            "Finishing: ch 10 for a hanging loop, sl st into the same corner, fasten off, weave in ends, and block flat.",
        ],
        "accessories": [
            "PROJECT OVERVIEW: Make a quick headband or wrist warmer rectangle with a clear stitch count and simple seam.",
            "EXACT STITCHES USED: ch, sc, hdc, sl st.",
            "STARTING CHAIN: ch 18.",
            "Pattern Instructions:",
            "Row 1: hdc in third ch from hook and across. (16 sts)",
            "Row 2: ch 2, turn, hdc across. (16 sts)",
            "Rows 3-28: repeat Row 2 for a small accessory rectangle. (16 sts each row)",
            "Final row: ch 1, turn, sc across. (16 sts)",
            "Finishing: bring short ends together, sl st through both layers to seam, fasten off, weave in ends, and turn seam to the inside.",
        ],
    }
    steps = list(templates.get(project_type, templates["accessories"]))
    if skill in {"intermediate", "advanced"} and project_type in {"blankets", "hats_scarves", "clothing"}:
        steps.insert(-1, "Optional detail: add one accent stripe after every 8 rows while keeping the same stitch count.")
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
        "repeat until it fits",
        "work in pattern",
        "continue as needed",
        "shape as desired",
    ]
    if normalized in vague_markers:
        return True
    has_row_or_round = bool(re.search(r"\b(row|round)\s+\d+", normalized))
    has_stitch_count = " sts" in normalized or " stitches" in normalized
    has_stitch_type = bool(re.search(r"\b(sc|hdc|dc|ch|sl st)\b", normalized))
    if any(marker in normalized for marker in vague_markers) and not (has_row_or_round and has_stitch_count):
        return True
    if not (has_row_or_round and has_stitch_count and has_stitch_type):
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
        "Write specific Pattern Instructions with exact stitch types, starting chain or round setup, "
        "row-by-row or round-by-round steps, stitch counts such as '(20 sts)', finishing steps, "
        "pattern notes, and beginner tips. Group long repeats only after Row 1 and Row 2 or "
        "Round 1 and Round 2 are fully specified."
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
Avoid vague-only instructions such as "repeat until it fits", "work in pattern",
"continue as needed", or "shape as desired" unless exact row/round guidance and
stitch counts are included in the same pattern.
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
