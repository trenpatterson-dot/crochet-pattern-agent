"""
Crochet Pattern Finder — Orchestrator

Coordinates the 5-agent pipeline:
  1. Search Agent      → finds 10-15 raw pattern candidates from trusted sites
  2. Filter Agent      → crochet expert selects top 3 found patterns
  3. Compliance Agent  → verifies licensing, source legitimacy, no copyright risk
     Creator Agent     → (runs in parallel with Compliance) designs 2 original patterns
  4. Materials Agent   → enriches all 5 patterns (3 found + 2 original) with store links

Every report = 3 curated found patterns + 2 original patterns made for that user.
"""

import threading
from typing import Optional
from agents import (
    search_agent,
    filter_agent,
    compliance_agent,
    creator_agent,
    materials_agent,
    link_validator,
)


def run(user: dict) -> Optional[dict]:
    name = user["name"]
    skill = user["skill_level"]
    projects = ", ".join(user.get("project_types", []))

    print(f"\n{'='*55}")
    print(f"[Orchestrator] Pipeline started for {name}")
    print(f"  Skill: {skill} | Projects: {projects}")
    print(f"  Aesthetic: {user.get('aesthetic','any')} | Budget: {user.get('budget','any')}")
    print(f"{'='*55}")

    # ── Step 1: Search Agent ──────────────────────────────────
    print("\n[Orchestrator] -> Search Agent: finding pattern candidates...")
    candidates = search_agent.find_candidates(user)
    if not candidates:
        print("[Orchestrator] FAIL: Search Agent returned no candidates. Aborting.")
        return None

    # ── Step 2: Filter Agent (Crochet Expert) — top 3 ─────────
    print("\n[Orchestrator] -> Filter Agent (Crochet Expert): selecting top 3 found patterns...")
    top3 = filter_agent.curate(user, candidates)
    if not top3:
        print("[Orchestrator] FAIL: Filter Agent returned no patterns. Aborting.")
        return None

    # ── Steps 3a & 3b: Compliance + Creator run in parallel ───
    print("\n[Orchestrator] -> Compliance Agent + Creator Agent running in parallel...")

    approved_found = []
    originals = []
    worker_errors = []

    def run_compliance():
        try:
            result = compliance_agent.verify(top3)
            approved_found.extend(result)
        except Exception as exc:
            worker_errors.append(("compliance", exc))

    def run_creator():
        try:
            result = creator_agent.create(user)
            originals.extend(result)
        except Exception as exc:
            worker_errors.append(("creator", exc))

    t_compliance = threading.Thread(target=run_compliance)
    t_creator    = threading.Thread(target=run_creator)

    t_compliance.start()
    t_creator.start()
    t_compliance.join()
    t_creator.join()

    if worker_errors:
        stage, exc = worker_errors[0]
        raise RuntimeError(f"{stage.title()} Agent failed: {exc}") from exc

    if not approved_found and not originals:
        print("[Orchestrator] FAIL: Both Compliance and Creator returned nothing. Aborting.")
        return None

    if len(approved_found) < len(top3):
        dropped = len(top3) - len(approved_found)
        print(f"[Orchestrator] {dropped} found pattern(s) removed by compliance review.")

    if approved_found:
        print("\n[Orchestrator] -> Link Validator: checking final found-pattern URLs...")
        approved_found = link_validator.validate_patterns(approved_found)

    # Combine: found first, then originals
    all_patterns = approved_found + originals
    print(f"\n[Orchestrator] Combined: {len(approved_found)} found + {len(originals)} original = {len(all_patterns)} total")

    # ── Step 4: Materials Agent ───────────────────────────────
    print("\n[Orchestrator] -> Materials Agent: adding store links + tutorials...")
    enriched = materials_agent.enrich(user, all_patterns)

    print("\n[Orchestrator] -> Link Validator: checking final materials/store URLs...")
    enriched = link_validator.validate_material_links(enriched)

    print("\n[Orchestrator] -> Link Validator: checking final tutorial URLs...")
    enriched = link_validator.validate_tutorial_links(enriched)

    print(f"\n[Orchestrator] DONE: Pipeline complete -- {len(enriched)} patterns ready for {name}")
    print(f"  ({len(approved_found)} found from trusted sites, {len(originals)} original)\n")

    return {
        "user_name": name,
        "patterns": enriched,
        "found_count": len(approved_found),
        "original_count": len(originals),
    }
