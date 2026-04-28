"""
Crochet Pattern Finder Agent

Supports two LLM providers:
  - anthropic  → Claude claude-sonnet-4-6 with built-in web_search tool
  - ollama     → Local model via OpenAI-compatible API + DuckDuckGo search

Set LLM_PROVIDER in .env to switch between them.
"""

import json
import os
import re
from typing import Optional

import anthropic
import pathlib
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(pathlib.Path(__file__).parent / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_MODEL = "claude-sonnet-4-6"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

TRUSTED_SITES = [
    "ravelry.com",
    "lovecrafts.com",
    "allfreecrochet.com",
    "yarnspirations.com",
    "lionbrand.com",
    "garnstudio.com",
    "thesprucecrafts.com",
    "redheart.com",
    "purlsoho.com",
]

SYSTEM_PROMPT = """\
You are an expert crochet pattern curator. Find the top 5 crochet patterns for a crafter \
based on their preferences.

RULES:
- Only use patterns from these trusted sites: {sites}
- Also search YouTube for a tutorial video for each pattern
- Match skill level exactly — never suggest advanced patterns for beginners
- If user wants free patterns only, never include paid patterns
- Return ONLY valid JSON (no markdown fences, no explanation) in this exact structure:

{{
  "patterns": [
    {{
      "rank": 1,
      "title": "Pattern Name",
      "source_site": "ravelry.com",
      "url": "https://...",
      "skill_level": "beginner",
      "project_type": "amigurumi",
      "yarn_weight": "worsted",
      "hook_size": "5mm (H/8)",
      "estimated_time": "Weekend project (8-10 hours)",
      "materials": ["200g worsted yarn", "5mm hook", "polyester fiberfill"],
      "why_picked": "One sentence explaining the match",
      "video_tutorial": {{"title": "Tutorial Title", "url": "https://youtube.com/watch?v=..."}},
      "is_free": true,
      "price": null
    }}
  ]
}}""".format(sites=", ".join(TRUSTED_SITES))


def _build_user_prompt(user: dict) -> str:
    projects = ", ".join(user["project_types"])
    yarns = ", ".join(user["yarn_weights"]) if user["yarn_weights"] else "any weight"
    free_note = "IMPORTANT: Only include FREE patterns." if user["free_only"] else ""
    interests = f"Special interests/keywords: {user['special_interests']}" if user.get("special_interests") else ""

    return f"""Find the top 5 crochet patterns for this crafter:

Name: {user['name']}
Skill Level: {user['skill_level']}
Project Types: {projects}
Yarn Weight: {yarns}
Time Per Project: {user['time_commitment']}
{free_note}
{interests}

Search trusted crochet sites and YouTube, then return the top 5 as JSON."""


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


# ── Anthropic provider ────────────────────────────────────────────────────────

def _find_patterns_anthropic(user: dict) -> Optional[dict]:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        messages=[{"role": "user", "content": _build_user_prompt(user)}],
    )
    full_text = "".join(b.text for b in response.content if b.type == "text")
    return _extract_json(full_text)


# ── Ollama provider ───────────────────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


def _find_patterns_ollama(user: dict) -> Optional[dict]:
    projects = ", ".join(user["project_types"])
    skill = user["skill_level"]
    free_flag = "free " if user["free_only"] else ""

    # Build targeted searches
    queries = [
        f'{free_flag}{skill} crochet {projects} pattern site:{s}'
        for s in ["ravelry.com", "allfreecrochet.com", "yarnspirations.com"]
    ] + [f'{skill} crochet {projects} tutorial youtube']

    search_results = []
    for q in queries[:4]:
        results = _ddg_search(q, max_results=4)
        for r in results:
            search_results.append({
                "query": q,
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })

    context = json.dumps(search_results, indent=2)

    user_prompt = f"""{_build_user_prompt(user)}

Here are web search results to use as your source:
{context}

Pick the top 5 pattern results and format as the JSON structure in your instructions.
Only include URLs that appear in the search results above."""

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    response = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    raw = response.choices[0].message.content or ""
    return _extract_json(raw)


# ── Public API ────────────────────────────────────────────────────────────────

def find_patterns(user: dict) -> Optional[dict]:
    print(f"  [Agent/{LLM_PROVIDER}] {user['name']} — {user['skill_level']}, "
          f"{', '.join(user['project_types'])}")

    result = (
        _find_patterns_anthropic(user)
        if LLM_PROVIDER == "anthropic"
        else _find_patterns_ollama(user)
    )

    if result and "patterns" in result:
        print(f"  [Agent] Found {len(result['patterns'])} patterns for {user['name']}")
    else:
        print(f"  [Agent] WARNING: No patterns returned for {user['name']}")

    return result
