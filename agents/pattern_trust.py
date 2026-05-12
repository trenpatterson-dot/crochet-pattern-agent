"""
Pattern trust metadata and AI-risk heuristics.

This is intentionally rules-based. It does not verify a pattern by itself; it
adds review metadata and routes questionable items to a local manual queue.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REVIEW_QUEUE_PATH = ROOT / "logs" / "pattern_review_queue.jsonl"

VAGUE_MARKERS = (
    "easy crochet pattern",
    "beginner friendly crochet pattern",
    "make the pieces and sew together",
    "crochet the body",
    "repeat until done",
    "as shown",
    "follow the picture",
    "use any yarn",
    "simple and cute",
)

INFOGRAPHIC_MARKERS = (
    "crochet pattern in image",
    "free pattern in picture",
    "pattern below image",
    "see photo for steps",
    "pin now make later",
    "instant download pattern chart",
)

UNREALISTIC_BEGINNER_MARKERS = (
    "anyone can make this",
    "perfect first amigurumi",
    "no counting needed",
    "no experience required",
    "works up in minutes",
    "guaranteed beginner",
)

ADVANCED_BEGINNER_TECHNIQUES = (
    "magic ring",
    "color change",
    "invisible decrease",
    "seam",
    "join pieces",
    "safety eyes",
    "stuff firmly",
    "blo",
    "flo",
)


def _text_blob(pattern: dict) -> str:
    parts = [
        pattern.get("title", ""),
        pattern.get("source_site", ""),
        pattern.get("description", ""),
        pattern.get("snippet", ""),
        pattern.get("why_its_perfect", ""),
        pattern.get("why_created", ""),
        pattern.get("instructions", ""),
        pattern.get("tutorial_guidance", ""),
        pattern.get("compliance_note", ""),
    ]
    for note in pattern.get("notes") or []:
        parts.append(str(note))
    for material in pattern.get("materials") or []:
        parts.append(str(material.get("name", "")))
    return " ".join(str(part) for part in parts if part).lower()


def _has_materials(pattern: dict) -> bool:
    materials = pattern.get("materials") or []
    if not materials:
        return False
    names = " ".join(str(item.get("name", "")).lower() for item in materials)
    return "yarn" in names and ("hook" in names or pattern.get("hook_size"))


def _has_assembly_support(pattern: dict, blob: str) -> bool:
    if pattern.get("instructions"):
        return True
    return any(term in blob for term in ("assemble", "seam", "join", "fasten off", "weave in"))


def _tutorial_available(pattern: dict) -> bool:
    video = pattern.get("video_tutorial") or {}
    return bool(
        video.get("url")
        or pattern.get("tutorial_guidance")
        or pattern.get("tutorial_candidates")
        or pattern.get("has_video")
    )


def _creator_attribution(pattern: dict) -> str:
    for key in ("creator_attribution", "designer", "designer_name", "author", "creator"):
        value = (pattern.get(key) or "").strip()
        if value:
            return value
    if pattern.get("designer_credited") is True:
        return (pattern.get("source_site") or "").strip()
    return ""


def _stitch_count_risk(blob: str) -> tuple[int, list[str]]:
    reasons = []
    counts = [int(match) for match in re.findall(r"\b(\d{1,3})\s*(?:st|sts|stitches)\b", blob)]
    if "stitch count" in blob and not counts:
        reasons.append("mentions stitch counts without visible counts")
        return 1, reasons
    if len(counts) >= 3:
        jumps = [abs(current - previous) for previous, current in zip(counts, counts[1:])]
        if any(jump > 36 for jump in jumps):
            reasons.append("stitch counts jump sharply")
            return 2, reasons
    if "increase evenly" in blob and not counts:
        reasons.append("uses increase wording without count checkpoints")
        return 1, reasons
    return 0, reasons


def _difficulty_confidence(score: int, pattern: dict, blob: str) -> str:
    if score >= 6:
        return "low"
    beginner = (pattern.get("skill_level") or pattern.get("difficulty") or "").lower()
    advanced_terms = sum(1 for term in ADVANCED_BEGINNER_TECHNIQUES if term in blob)
    if "beginner" in beginner and advanced_terms >= 4:
        return "medium"
    return "high" if score <= 1 else "medium"


def _reality_check_summary(pattern: dict, reasons: list[str], blob: str) -> str:
    project_type = (pattern.get("project_type") or "pattern").replace("_", " ")
    watch_items = []
    for term, label in (
        ("color change", "color changes"),
        ("seam", "sewing or joining"),
        ("join pieces", "sewing or joining"),
        ("stitch count", "unclear stitch counts"),
        ("magic ring", "magic ring setup"),
        ("stuff", "stuffing and shaping"),
    ):
        if term in blob and label not in watch_items:
            watch_items.append(label)
    if not watch_items and reasons:
        watch_items = reasons[:2]
    if not watch_items:
        watch_items = ["unclear support details"]
    return (
        f"This {project_type} may look beginner-friendly, but "
        f"{', '.join(watch_items[:3])} may frustrate new crocheters."
    )


def assess_pattern(pattern: dict) -> dict:
    updated = dict(pattern)
    blob = _text_blob(updated)
    score = 0
    reasons = []

    creator = _creator_attribution(updated)
    source_url = updated.get("url") or updated.get("pattern_url") or updated.get("pattern_cta_url")
    has_tutorial = _tutorial_available(updated)

    if not updated.get("is_original") and not creator:
        score += 2
        reasons.append("missing creator attribution")
    if not source_url and not updated.get("is_original"):
        score += 2
        reasons.append("missing source URL")
    if not has_tutorial:
        score += 1
        reasons.append("tutorial support not obvious")
    if any(marker in blob for marker in VAGUE_MARKERS):
        score += 2
        reasons.append("vague generic wording")
    if any(marker in blob for marker in INFOGRAPHIC_MARKERS):
        score += 2
        reasons.append("suspicious infographic-style wording")
    if any(marker in blob for marker in UNREALISTIC_BEGINNER_MARKERS):
        score += 2
        reasons.append("unrealistic beginner claim")
    if not _has_materials(updated):
        score += 1
        reasons.append("missing yarn or hook materials")
    if not _has_assembly_support(updated, blob):
        score += 1
        reasons.append("assembly or finishing support is thin")

    stitch_score, stitch_reasons = _stitch_count_risk(blob)
    score += stitch_score
    reasons.extend(stitch_reasons)

    if updated.get("source_type") == "original_generated":
        reasons.append("generated original needs human review before verified claims")

    if score >= 6:
        risk_label = "likely_ai_generated"
    elif score >= 3:
        risk_label = "questionable"
    else:
        risk_label = "likely_legitimate"

    existing_review_status = (updated.get("review_status") or "").strip().lower()
    if existing_review_status in {"verified", "human_tested", "community_reviewed"}:
        review_status = existing_review_status
    elif risk_label == "likely_legitimate":
        review_status = "unreviewed"
    else:
        review_status = "needs_review"

    verified = bool(updated.get("verified")) and review_status in {
        "verified",
        "human_tested",
        "community_reviewed",
    }
    human_tested = bool(updated.get("human_tested"))

    updated.update(
        {
            "verified": verified,
            "human_tested": human_tested,
            "creator_attribution": creator,
            "tutorial_available": has_tutorial,
            "likely_ai_generated": risk_label == "likely_ai_generated",
            "ai_risk_score": min(score, 10),
            "ai_risk_label": risk_label,
            "ai_risk_reasons": reasons,
            "difficulty_confidence": _difficulty_confidence(score, updated, blob),
            "review_status": review_status,
            "last_verified_date": updated.get("last_verified_date") or None,
            "reality_check_summary": _reality_check_summary(updated, reasons, blob),
        }
    )
    return updated


def apply_trust_metadata(patterns: list[dict]) -> list[dict]:
    return [assess_pattern(pattern) for pattern in patterns]


def queue_review_items(patterns: list[dict], user: dict | None = None, queue_path: Path = REVIEW_QUEUE_PATH) -> dict:
    needs_review = [
        pattern for pattern in patterns
        if pattern.get("review_status") == "needs_review"
        or pattern.get("ai_risk_label") in {"questionable", "likely_ai_generated"}
    ]
    if not needs_review:
        return {"queued_count": 0, "queue_path": str(queue_path)}

    queue_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    user_context = {
        "skill_level": (user or {}).get("skill_level"),
        "project_types": (user or {}).get("project_types"),
    }
    with queue_path.open("a", encoding="utf-8") as handle:
        for pattern in needs_review:
            handle.write(
                json.dumps(
                    {
                        "queued_at": now,
                        "title": pattern.get("title"),
                        "source_site": pattern.get("source_site"),
                        "url": pattern.get("url") or pattern.get("pattern_cta_url"),
                        "review_status": pattern.get("review_status"),
                        "ai_risk_label": pattern.get("ai_risk_label"),
                        "ai_risk_score": pattern.get("ai_risk_score"),
                        "ai_risk_reasons": pattern.get("ai_risk_reasons", []),
                        "reality_check_summary": pattern.get("reality_check_summary"),
                        "user_context": user_context,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return {"queued_count": len(needs_review), "queue_path": str(queue_path)}
