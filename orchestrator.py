"""
Crochet Pattern Finder orchestrator.

Coordinates the agent pipeline and records diagnostics so dry-run failures can be
understood from admin and Render logs without exposing subscriber details.
"""

import threading
from typing import Optional

from agents import (
    compliance_agent,
    creator_agent,
    filter_agent,
    link_validator,
    materials_agent,
    search_agent,
)


def _selected_test_fallback_count(user: dict) -> int:
    return 3 if user.get("_selected_test_mode") else 1


def _run_creator_fallback(user: dict, diagnostics: dict, reason: str) -> list[dict]:
    print(f"[Orchestrator] Fallback: generating original pattern ideas because {reason}.")
    originals, creator_meta = creator_agent.create(
        user,
        pattern_count=_selected_test_fallback_count(user),
        fallback_mode=True,
        return_meta=True,
    )
    diagnostics["creator_meta"] = creator_meta
    diagnostics["original_created_count"] = len(originals)
    diagnostics["fallback_used"] = True
    diagnostics["fallback_reason"] = reason
    return originals


def run(user: dict) -> Optional[dict]:
    name = user["name"]
    skill = user["skill_level"]
    projects = ", ".join(user.get("project_types", []))
    diagnostics = {
        "search_candidates_count": 0,
        "filtered_candidates_count": 0,
        "compliance_approved_count": 0,
        "original_created_count": 0,
        "materials_enriched_count": 0,
        "final_usable_pattern_count": 0,
        "failure_reason": None,
        "fallback_used": False,
    }

    print(f"\n{'=' * 55}")
    print(f"[Orchestrator] Pipeline started for {name}")
    print(f"  Skill: {skill} | Projects: {projects}")
    print(f"  Aesthetic: {user.get('aesthetic', 'any')} | Budget: {user.get('budget', 'any')}")
    print(f"{'=' * 55}")

    approved_found: list[dict] = []
    originals: list[dict] = []
    all_patterns: list[dict] = []

    print("\n[Orchestrator] -> Search Agent: finding pattern candidates...")
    candidates, search_meta = search_agent.find_candidates(user, return_meta=True)
    diagnostics["search_meta"] = search_meta
    diagnostics["search_candidates_count"] = len(candidates)
    print(f"[Orchestrator] Search candidates after parse: {len(candidates)}")

    if not candidates:
        diagnostics["failure_reason"] = (
            "search_parse_failed"
            if search_meta.get("reason") == "parse_failed"
            else "search_zero_candidates"
        )
        originals = _run_creator_fallback(user, diagnostics, diagnostics["failure_reason"])
        if not originals:
            print("[Orchestrator] FAIL: Search returned no candidates and fallback creator returned nothing.")
            return {"user_name": name, "patterns": [], "diagnostics": diagnostics}
        all_patterns = list(originals)
    else:
        print("\n[Orchestrator] -> Filter Agent (Crochet Expert): selecting top 3 found patterns...")
        top3, filter_meta = filter_agent.curate(user, candidates, return_meta=True)
        diagnostics["filter_meta"] = filter_meta
        diagnostics["filtered_candidates_count"] = len(top3)
        print(f"[Orchestrator] Filter selected patterns: {len(top3)}")

        if not top3:
            diagnostics["failure_reason"] = (
                "filter_parse_failed"
                if filter_meta.get("reason") == "parse_failed"
                else "filter_zero_candidates"
            )
            originals = _run_creator_fallback(user, diagnostics, diagnostics["failure_reason"])
            if not originals:
                print("[Orchestrator] FAIL: Filter returned no patterns and fallback creator returned nothing.")
                return {"user_name": name, "patterns": [], "diagnostics": diagnostics}
            all_patterns = list(originals)
        else:
            print("\n[Orchestrator] -> Compliance Agent + Creator Agent running in parallel...")
            worker_errors: list[tuple[str, Exception]] = []

            def run_compliance():
                try:
                    result, compliance_meta = compliance_agent.verify(top3, return_meta=True)
                    diagnostics["compliance_meta"] = compliance_meta
                    approved_found.extend(result)
                except Exception as exc:
                    worker_errors.append(("compliance", exc))

            def run_creator():
                try:
                    result, creator_meta = creator_agent.create(user, return_meta=True)
                    diagnostics["creator_meta"] = creator_meta
                    originals.extend(result)
                except Exception as exc:
                    worker_errors.append(("creator", exc))

            t_compliance = threading.Thread(target=run_compliance)
            t_creator = threading.Thread(target=run_creator)
            t_compliance.start()
            t_creator.start()
            t_compliance.join()
            t_creator.join()

            if worker_errors:
                stage, exc = worker_errors[0]
                raise RuntimeError(f"{stage.title()} Agent failed: {exc}") from exc

            diagnostics["compliance_approved_count"] = len(approved_found)
            diagnostics["original_created_count"] = len(originals)
            print(f"[Orchestrator] Compliance approved patterns: {len(approved_found)}")
            print(f"[Orchestrator] Creator original patterns: {len(originals)}")

            if not approved_found and not originals:
                diagnostics["failure_reason"] = "compliance_and_creator_zero_patterns"
                originals = _run_creator_fallback(user, diagnostics, diagnostics["failure_reason"])
                if not originals:
                    print("[Orchestrator] FAIL: Both Compliance and Creator returned nothing.")
                    return {"user_name": name, "patterns": [], "diagnostics": diagnostics}

            if len(approved_found) < len(top3):
                dropped = len(top3) - len(approved_found)
                print(f"[Orchestrator] {dropped} found pattern(s) removed by compliance review.")

            if approved_found:
                print("\n[Orchestrator] -> Link Validator: checking final found-pattern URLs...")
                approved_found = link_validator.validate_patterns(approved_found)
                diagnostics["compliance_approved_count"] = len(approved_found)

            all_patterns = approved_found + originals

    print(
        f"\n[Orchestrator] Combined: {len(approved_found)} found + "
        f"{len(all_patterns) - len(approved_found)} original = {len(all_patterns)} total"
    )

    print("\n[Orchestrator] -> Materials Agent: adding store links + tutorials...")
    enriched, materials_meta = materials_agent.enrich(user, all_patterns, return_meta=True)
    diagnostics["materials_meta"] = materials_meta
    diagnostics["materials_enriched_count"] = len(enriched)

    print("\n[Orchestrator] -> Link Validator: checking final materials/store URLs...")
    enriched = link_validator.validate_material_links(enriched)

    print("\n[Orchestrator] -> Link Validator: checking final tutorial URLs...")
    enriched = link_validator.validate_tutorial_links(enriched)

    diagnostics["final_usable_pattern_count"] = len(enriched)
    if not enriched and not diagnostics.get("failure_reason"):
        diagnostics["failure_reason"] = "final_zero_patterns"

    print(f"[Orchestrator] Final usable patterns: {len(enriched)}")
    print(f"\n[Orchestrator] DONE: Pipeline complete -- {len(enriched)} patterns ready for {name}")
    print(
        f"  ({len(approved_found)} found from trusted sites, "
        f"{len(all_patterns) - len(approved_found)} original)\n"
    )

    return {
        "user_name": name,
        "patterns": enriched,
        "found_count": len(approved_found),
        "original_count": len(all_patterns) - len(approved_found),
        "diagnostics": diagnostics,
    }
