#!/usr/bin/env python3
"""Local-only manual feedback analysis for Crochet Pattern Agent.

This script reads manually pasted feedback and writes structured recommendations.
It does not edit app files, send emails, access secrets, deploy, publish, or use
network services.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROCESSED_DIR = ROOT / "feedback" / "processed"
OUTPUT_DIR = ROOT / "feedback" / "output"

ISSUE_TYPES = (
    "bug",
    "UX confusion",
    "broken link",
    "missing feature",
    "content clarity",
    "monetization",
    "email design",
    "landing page",
    "backend/scheduler",
    "market research",
)

PRIORITIES = ("critical", "high", "medium", "low")
DECISIONS = ("execute_now", "backlog", "reject", "needs_more_data")

TYPE_KEYWORDS = {
    "bug": ("error", "crash", "broken", "bug", "doesn't work", "does not work", "failed", "wrong"),
    "UX confusion": ("confusing", "confused", "hard to use", "not sure", "unclear where", "can't find"),
    "broken link": ("404", "dead link", "broken link", "link doesn't work", "link does not work", "invalid url"),
    "missing feature": ("wish", "would like", "can you add", "missing", "need a way", "filter", "option"),
    "content clarity": ("wording", "instructions", "abbreviation", "explain", "unclear", "too vague"),
    "monetization": ("affiliate", "price", "cost", "amazon", "shop", "buy", "ad"),
    "email design": ("email", "inbox", "subject", "button", "cta", "newsletter"),
    "landing page": ("landing", "signup", "form", "homepage", "subscribe page"),
    "backend/scheduler": ("scheduler", "send", "sent twice", "database", "server", "admin", "unsubscribe"),
    "market research": ("competitor", "youtube", "pinterest", "blog", "ravelry", "etsy", "research"),
}

AREA_MAP = {
    "bug": "runtime behavior",
    "UX confusion": "user experience",
    "broken link": "link validation",
    "missing feature": "product backlog",
    "content clarity": "pattern/email copy",
    "monetization": "affiliate/materials flow",
    "email design": "email rendering",
    "landing page": "signup page",
    "backend/scheduler": "scheduler/backend",
    "market research": "competition/community strategy",
}

PRIORITY_KEYWORDS = {
    "critical": ("can't unsubscribe", "cannot unsubscribe", "secret", "password", "api key", "charged", "privacy"),
    "high": ("can't", "cannot", "broken", "404", "failed", "sent twice", "wrong link", "doesn't work"),
    "medium": ("confusing", "unclear", "hard", "missing", "wish", "would like", "frustrating"),
    "low": ("nice to have", "minor", "small", "maybe", "could"),
}


def split_entries(raw_text: str) -> list[str]:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"\n\s*---+\s*\n|\n\s*\n+", normalized)
    return [part.strip() for part in parts if part.strip()]


def classify_entry(text: str) -> str:
    lowered = text.lower()
    scores = {
        issue_type: sum(1 for keyword in keywords if keyword in lowered)
        for issue_type, keywords in TYPE_KEYWORDS.items()
    }
    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score == 0:
        return "UX confusion"
    return best_type


def assign_priority(text: str, issue_type: str) -> str:
    lowered = text.lower()
    for priority in PRIORITIES:
        if any(keyword in lowered for keyword in PRIORITY_KEYWORDS[priority]):
            return priority
    if issue_type in {"bug", "broken link", "backend/scheduler"}:
        return "high"
    if issue_type in {"UX confusion", "email design", "landing page", "content clarity"}:
        return "medium"
    return "low"


def recommend_decision(text: str, issue_type: str, priority: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ("spam", "irrelevant", "not related", "ignore")):
        return "reject"
    if any(marker in lowered for marker in ("maybe", "not sure", "someone said", "unclear", "need more")):
        return "needs_more_data"
    if priority in {"critical", "high"}:
        return "execute_now"
    if issue_type in {"missing feature", "market research", "monetization"}:
        return "backlog"
    return "backlog" if priority == "low" else "execute_now"


def summarize_entry(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 160:
        return compact
    return compact[:157].rstrip() + "..."


def build_item(index: int, text: str) -> dict:
    issue_type = classify_entry(text)
    priority = assign_priority(text, issue_type)
    decision = recommend_decision(text, issue_type, priority)
    return {
        "id": f"feedback-{index:03d}",
        "issue_type": issue_type,
        "priority": priority,
        "recommended_decision": decision,
        "affected_area": AREA_MAP.get(issue_type, "general"),
        "summary": summarize_entry(text),
        "raw_excerpt": summarize_entry(text),
        "recommended_action": recommended_action(issue_type, priority, decision),
    }


def recommended_action(issue_type: str, priority: str, decision: str) -> str:
    if decision == "reject":
        return "Do not act unless similar feedback repeats."
    if decision == "needs_more_data":
        return "Ask a follow-up question or wait for repeated examples before changing code."
    if priority in {"critical", "high"}:
        return f"Inspect the {AREA_MAP.get(issue_type, 'relevant')} code/docs and prepare a focused fix."
    return f"Add to backlog for {AREA_MAP.get(issue_type, 'general')} improvement."


def analyze_feedback(raw_text: str) -> dict:
    entries = split_entries(raw_text)
    items = [build_item(index, entry) for index, entry in enumerate(entries, start=1)]
    priority_counts = Counter(item["priority"] for item in items)
    type_counts = Counter(item["issue_type"] for item in items)
    decision_counts = Counter(item["recommended_decision"] for item in items)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "item_count": len(items),
        "items": items,
        "summary": {
            "priority_counts": {priority: priority_counts.get(priority, 0) for priority in PRIORITIES},
            "type_counts": {issue_type: type_counts.get(issue_type, 0) for issue_type in ISSUE_TYPES},
            "decision_counts": {decision: decision_counts.get(decision, 0) for decision in DECISIONS},
        },
    }


def build_backlog(items: list[dict]) -> list[dict]:
    backlog_items = [
        item for item in items
        if item["recommended_decision"] in {"execute_now", "backlog", "needs_more_data"}
    ]
    priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    decision_rank = {"execute_now": 0, "needs_more_data": 1, "backlog": 2}
    backlog_items.sort(
        key=lambda item: (
            priority_rank.get(item["priority"], 9),
            decision_rank.get(item["recommended_decision"], 9),
            item["id"],
        )
    )
    return [
        {
            "id": item["id"],
            "title": item["summary"],
            "issue_type": item["issue_type"],
            "priority": item["priority"],
            "decision": item["recommended_decision"],
            "affected_area": item["affected_area"],
            "recommended_action": item["recommended_action"],
        }
        for item in backlog_items
    ]


def build_summary_markdown(analysis: dict, backlog: list[dict]) -> str:
    lines = [
        "# Feedback Summary",
        "",
        "Local-only analysis. Raw feedback stays in `feedback/raw/` and should not be committed.",
        "",
        f"- Generated at: {analysis['generated_at']}",
        f"- Feedback items: {analysis['item_count']}",
        "",
        "## Priority Summary",
    ]
    for priority, count in analysis["summary"]["priority_counts"].items():
        lines.append(f"- {priority}: {count}")
    lines.extend(["", "## Issue Type Summary"])
    for issue_type, count in analysis["summary"]["type_counts"].items():
        if count:
            lines.append(f"- {issue_type}: {count}")
    lines.extend(["", "## Recommended Decisions"])
    for decision, count in analysis["summary"]["decision_counts"].items():
        lines.append(f"- {decision}: {count}")
    lines.extend(["", "## Structured Issues"])
    for item in analysis["items"]:
        lines.extend(
            [
                "",
                f"### {item['id']}",
                f"- Type: {item['issue_type']}",
                f"- Priority: {item['priority']}",
                f"- Decision: {item['recommended_decision']}",
                f"- Affected area: {item['affected_area']}",
                f"- Summary: {item['summary']}",
                f"- Recommended action: {item['recommended_action']}",
            ]
        )
    lines.extend(["", "## Backlog Preview"])
    if not backlog:
        lines.append("- No backlog items generated.")
    for item in backlog:
        lines.append(f"- [{item['priority']}] {item['title']} ({item['affected_area']})")
    return "\n".join(lines) + "\n"


def build_codex_prompt(analysis: dict, backlog: list[dict]) -> str:
    execute_items = [
        item for item in backlog
        if item["decision"] == "execute_now"
    ]
    top_items = execute_items or backlog[:5]
    affected_areas = sorted({item["affected_area"] for item in top_items}) or ["to be determined"]
    task_lines = [
        f"- {item['id']}: {item['recommended_action']} Summary: {item['title']}"
        for item in top_items
    ] or ["- Review the feedback summary and decide whether more data is needed."]
    return "\n".join(
        [
            "Goal:",
            "Improve Crochet Pattern Agent using manually collected user feedback.",
            "",
            "Context:",
            "Raw feedback was analyzed locally by `feedback_team.py`. Do not expose raw user feedback.",
            f"Total feedback items: {analysis['item_count']}.",
            "",
            "Affected Areas:",
            *[f"- {area}" for area in affected_areas],
            "",
            "Tasks:",
            *task_lines,
            "",
            "Constraints:",
            "- Do not auto-edit files without inspecting the relevant code first.",
            "- Do not send emails.",
            "- Do not access `.env`, API keys, tokens, credentials, or deployment secrets.",
            "- Do not commit raw feedback.",
            "- Keep changes small and evidence-based.",
            "- Preserve existing dry-run and scheduler behavior unless the task specifically targets it.",
            "",
            "Tests To Run:",
            "- python -m py_compile feedback_team.py",
            "- python scripts/smoke_test.py, if runtime code is changed",
            "- Add focused regression tests if app behavior changes",
            "",
        ]
    )


def write_outputs(analysis: dict) -> dict[str, Path]:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    backlog = build_backlog(analysis["items"])
    paths = {
        "items": PROCESSED_DIR / "feedback_items.json",
        "summary": OUTPUT_DIR / "feedback_summary.md",
        "codex_prompt": OUTPUT_DIR / "codex_prompt.txt",
        "backlog": OUTPUT_DIR / "backlog.json",
    }
    paths["items"].write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    paths["summary"].write_text(build_summary_markdown(analysis, backlog), encoding="utf-8")
    paths["codex_prompt"].write_text(build_codex_prompt(analysis, backlog), encoding="utf-8")
    paths["backlog"].write_text(json.dumps(backlog, indent=2), encoding="utf-8")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze local manual feedback for Crochet Pattern Agent.")
    parser.add_argument("--input", required=True, help="Path to a local raw feedback text file.")
    args = parser.parse_args()
    input_path = Path(args.input)
    raw_text = input_path.read_text(encoding="utf-8")
    analysis = analyze_feedback(raw_text)
    paths = write_outputs(analysis)
    print(f"Analyzed {analysis['item_count']} feedback item(s).")
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
