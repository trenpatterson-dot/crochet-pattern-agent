"""
Competition Intelligence Agent

Builds a weekly market snapshot for StitchFlow Labs using public, search-based data.
It does not scrape logged-in pages or use private APIs.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import database
from . import llm

ARTIFACT_NAMES = ("trends", "competitors", "opportunities", "keywords")
REFRESH_DAYS = int(os.getenv("COMPETITION_INTEL_REFRESH_DAYS", "7"))
ROOT = Path(__file__).resolve().parent.parent
INTEL_ROOT = Path(os.getenv("COMPETITION_INTEL_DIR", ROOT / "intel"))
STABLE_INTEL_ROOT = ROOT / "intel"

SYSTEM_PROFILE = """
System under analysis: StitchFlow Labs crochet recommendation platform.

Current strengths:
- Email + web recommendation workflow
- Personalized pattern discovery
- Materials and affiliate linking
- Beginner through advanced user segmentation
- Project types already modeled: blankets, hats_scarves, amigurumi, clothing,
  bags, home_decor, baby, holiday, accessories

Current monetization:
- Amazon affiliate links
- AWIN affiliate partnerships
- CJ affiliate partnerships

Your task:
- Find competitor, trend, keyword, and buying-signal intelligence
- Use only public/search-based evidence
- Never invent sales numbers, search volume, ratings, or popularity
- If a signal is weak or uncertain, label it conservatively or omit it
""".strip()


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _latest_dir() -> Path:
    path = INTEL_ROOT / "latest"
    _ensure_dir(path)
    return path


def _stable_latest_dir() -> Path:
    path = STABLE_INTEL_ROOT / "latest"
    _ensure_dir(path)
    return path


def _history_dir() -> Path:
    path = INTEL_ROOT / "history"
    _ensure_dir(path)
    return path


def _history_run_dir(started_at: str) -> Path:
    safe_stamp = started_at.replace(":", "-")
    path = _history_dir() / safe_stamp
    _ensure_dir(path)
    return path


def _write_json(path: Path, payload: dict) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_latest_file(name: str) -> dict | None:
    path = _latest_dir() / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _sync_latest_exports(artifacts: dict[str, dict]) -> str:
    stable_dir = _stable_latest_dir()
    for name, payload in artifacts.items():
        if isinstance(payload, dict):
            _write_json(stable_dir / f"{name}.json", payload)
    return str(stable_dir)


def _search_evidence(queries: list[str], max_results: int = 5) -> list[dict]:
    results = []
    seen_urls = set()
    for query in queries:
        for item in llm.ddg_search(query, max_results=max_results):
            url = (item.get("href") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                {
                    "query": query,
                    "title": item.get("title", ""),
                    "url": url,
                    "snippet": item.get("body", ""),
                }
            )
    return results


def _call_llm(task_name: str, instructions: str, queries: list[str], schema_hint: str) -> dict:
    evidence = _search_evidence(queries)
    user_msg = f"""TASK: {task_name}

{SYSTEM_PROFILE}

Research instructions:
{instructions}

Public search evidence collected so far:
{json.dumps(evidence, indent=2)}

Return only valid JSON matching this schema:
{schema_hint}
"""

    raw = llm.chat(
        system=(
            "You are a market intelligence analyst. Use only public/search-based evidence. "
            "Do not scrape, log in, or fabricate missing details. Prefer cautious language."
        ),
        user_msg=user_msg,
        use_web_search=True,
        max_tokens=3500,
    )
    data = llm.parse_json(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"{task_name} did not return valid JSON.")
    return data


def _artifact_queries() -> dict[str, list[str]]:
    month = datetime.now().strftime("%B")
    return {
        "competitors": [
            "best Etsy crochet shops amigurumi blanket beginner",
            "Ravelry popular crochet patterns beginner amigurumi blanket",
            "top crochet YouTube channels beginner amigurumi blanket",
            "best crochet blogs beginner patterns crochet tutorials",
        ],
        "trends": [
            "Google Trends crochet patterns baby blanket amigurumi",
            "YouTube crochet search suggestions beginner amigurumi baby blanket",
            "Etsy trending crochet patterns amigurumi blanket baby",
            f"seasonal crochet patterns {month}",
        ],
        "keywords": [
            "beginner crochet kit amazon",
            "easy amigurumi pattern crochet",
            "cheap yarn for beginners crochet",
            "crochet baby blanket kit amazon",
        ],
        "opportunities": [
            "best crochet kits for beginners amazon",
            "crochet affiliate products yarn hooks kits amazon",
            "AWIN crochet yarn craft affiliate program",
            "CJ crochet supplies affiliate program",
        ],
    }


def _build_competitors(started_at: str) -> dict:
    schema_hint = """
{
  "generated_at": "ISO-8601 timestamp",
  "competitors": [
    {
      "name": "Competitor name",
      "platform": "Etsy | Ravelry | YouTube | Blog",
      "niche": "amigurumi | blankets | beginner | baby | seasonal | other",
      "engagement_signals": ["brief observed public signals only"],
      "observed_focus": ["pattern or content themes they emphasize"],
      "evidence_urls": ["https://..."],
      "notes": "short practical summary"
    }
  ]
}
""".strip()
    instructions = """
Identify a practical competitor set for a crochet recommendation business.
Include Etsy crochet shops, Ravelry popular pattern sources, YouTube crochet channels, and crochet blogs.
Capture only visible public engagement signals such as ratings, views, bestseller language, popularity labels,
subscriber mentions in snippets, or repeated appearance across search results.
If you cannot verify a signal from public evidence, omit it.
"""
    data = _call_llm("competitors", instructions, _artifact_queries()["competitors"], schema_hint)
    data["generated_at"] = started_at
    data.setdefault("competitors", [])
    return data


def _build_trends(started_at: str) -> dict:
    schema_hint = """
{
  "generated_at": "ISO-8601 timestamp",
  "weekly_summary": ["short trend summaries"],
  "trends": [
    {
      "topic": "crochet frog",
      "trend_type": "rising | seasonal | evergreen_buy_signal",
      "platforms": ["Google Trends", "YouTube", "Etsy", "Ravelry"],
      "confidence": "high | medium | low",
      "seasonality": "spring | baby gift season | evergreen | other",
      "why_it_matters": "brief business reason",
      "evidence_urls": ["https://..."]
    }
  ]
}
""".strip()
    instructions = """
Find rising crochet topics using public search-based signals related to Google Trends, YouTube suggestions,
and Etsy or Ravelry trend/popular pages. Emphasize repeat motifs, beginner-friendly projects, baby items,
giftable patterns, and seasonal demand. Output the top weekly trends only.
"""
    data = _call_llm("trends", instructions, _artifact_queries()["trends"], schema_hint)
    data["generated_at"] = started_at
    data.setdefault("weekly_summary", [])
    data.setdefault("trends", [])
    return data


def _build_keywords(started_at: str) -> dict:
    schema_hint = """
{
  "generated_at": "ISO-8601 timestamp",
  "keywords": [
    {
      "keyword": "beginner crochet kit",
      "intent": "buy | learn | pattern | materials",
      "competition_assessment": "likely_low | medium | high",
      "reason": "why this appears commercially useful",
      "related_trends": ["topic names"],
      "evidence_urls": ["https://..."]
    }
  ]
}
""".strip()
    instructions = """
Generate high-intent crochet keywords with practical buyer language. Prioritize terms that suggest purchase
intent, beginner readiness, or materials shopping intent. Use cautious qualitative competition labels only.
Do not claim exact volume or keyword difficulty.
"""
    data = _call_llm("keywords", instructions, _artifact_queries()["keywords"], schema_hint)
    data["generated_at"] = started_at
    data.setdefault("keywords", [])
    return data


def _build_opportunities(started_at: str, competitors: dict, trends: dict, keywords: dict) -> dict:
    schema_hint = """
{
  "generated_at": "ISO-8601 timestamp",
  "product_signals": [
    {
      "pattern_or_use_case": "baby blanket",
      "materials": ["cotton yarn", "5mm hook", "stitch markers"],
      "amazon_queries": ["baby blanket crochet kit", "soft cotton yarn for baby blanket"],
      "affiliate_categories": ["yarn", "hooks", "kits", "notions"],
      "evidence_urls": ["https://..."]
    }
  ],
  "opportunities": [
    {
      "title": "Beginner kits under $20",
      "opportunity_type": "content | product | affiliate | niche",
      "gap_summary": "what appears underserved",
      "why_now": "why demand appears timely",
      "recommended_action": "practical next step for StitchFlow Labs",
      "priority": "high | medium | low",
      "supporting_signals": ["short evidence-backed bullets"],
      "evidence_urls": ["https://..."]
    }
  ]
}
""".strip()
    instructions = f"""
Compare public competitor coverage with StitchFlow Labs' current recommendation model and monetization.
Identify missing categories, underserved niches, and product monetization gaps.
Map popular pattern themes to likely materials and purchase behavior using Amazon-style search intent and
affiliate-friendly product categories. Keep the output actionable for weekly planning.

Competitor data:
{json.dumps(competitors, indent=2)}

Trend data:
{json.dumps(trends, indent=2)}

Keyword data:
{json.dumps(keywords, indent=2)}
"""
    data = _call_llm("opportunities", instructions, _artifact_queries()["opportunities"], schema_hint)
    data["generated_at"] = started_at
    data.setdefault("product_signals", [])
    data.setdefault("opportunities", [])
    return data


def refresh_due(force: bool = False, refresh_days: int | None = None) -> bool:
    if force:
        return True

    window = refresh_days or REFRESH_DAYS
    latest = database.get_latest_competition_run()
    if latest and latest.get("finished_at"):
        try:
            finished_at = datetime.fromisoformat(latest["finished_at"])
            return datetime.now() >= finished_at + timedelta(days=window)
        except ValueError:
            return True

    path = _latest_dir() / "trends.json"
    if not path.exists():
        return True
    modified = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() >= modified + timedelta(days=window)


def load_latest_artifacts() -> dict[str, dict]:
    artifacts = {}
    for name in ARTIFACT_NAMES:
        from_db = database.get_latest_competition_artifact(name)
        if from_db and isinstance(from_db.get("artifact_json"), dict):
            artifacts[name] = from_db["artifact_json"]
            continue
        from_file = _read_latest_file(name)
        if isinstance(from_file, dict):
            artifacts[name] = from_file
    return artifacts


def build_prompt_context() -> str:
    artifacts = load_latest_artifacts()
    if not artifacts:
        return ""

    trends = artifacts.get("trends", {}).get("trends", [])[:5]
    keywords = artifacts.get("keywords", {}).get("keywords", [])[:5]
    opportunities = artifacts.get("opportunities", {}).get("opportunities", [])[:4]
    product_signals = artifacts.get("opportunities", {}).get("product_signals", [])[:4]

    lines = ["Weekly competition intelligence:"]

    if trends:
        lines.append("Top crochet trends:")
        for item in trends:
            lines.append(
                f"- {item.get('topic', 'unknown')}: {item.get('trend_type', 'signal')} "
                f"({item.get('confidence', 'low')} confidence)"
            )

    if keywords:
        lines.append("High-intent keyword opportunities:")
        for item in keywords:
            lines.append(
                f"- {item.get('keyword', 'unknown')} "
                f"[{item.get('competition_assessment', 'medium')}]"
            )

    if opportunities:
        lines.append("Market gaps to favor:")
        for item in opportunities:
            lines.append(f"- {item.get('title', 'unknown')}: {item.get('gap_summary', '')}")

    if product_signals:
        lines.append("Pattern-to-material buying signals:")
        for item in product_signals:
            materials = ", ".join(item.get("materials", [])[:4])
            lines.append(f"- {item.get('pattern_or_use_case', 'unknown')}: {materials}")

    return "\n".join(lines)


def run(force: bool = False) -> dict:
    database.init_db()
    if not refresh_due(force=force):
        latest = database.get_latest_competition_run()
        artifacts = load_latest_artifacts()
        stable_dir = _sync_latest_exports(artifacts) if artifacts else str(_stable_latest_dir())
        return {
            "status": "skipped",
            "reason": "fresh_snapshot_exists",
            "latest_run": latest,
            "stable_output_dir": stable_dir,
        }

    started_at = _timestamp()
    run_dir = _history_run_dir(started_at)

    competitors = _build_competitors(started_at)
    trends = _build_trends(started_at)
    keywords = _build_keywords(started_at)
    opportunities = _build_opportunities(started_at, competitors, trends, keywords)

    artifacts = {
        "competitors": competitors,
        "trends": trends,
        "keywords": keywords,
        "opportunities": opportunities,
    }

    for name, payload in artifacts.items():
        _write_json(_latest_dir() / f"{name}.json", payload)
        _write_json(run_dir / f"{name}.json", payload)
    stable_dir = _sync_latest_exports(artifacts)

    finished_at = _timestamp()
    summary = {
        "started_at": started_at,
        "finished_at": finished_at,
        "status": "ok",
        "competitor_count": len(competitors.get("competitors", [])),
        "trend_count": len(trends.get("trends", [])),
        "keyword_count": len(keywords.get("keywords", [])),
        "opportunity_count": len(opportunities.get("opportunities", [])),
        "output_dir": str(_latest_dir()),
        "stable_output_dir": stable_dir,
        "history_dir": str(run_dir),
    }
    database.save_competition_run(
        started_at=started_at,
        finished_at=finished_at,
        status="ok",
        summary=summary,
        artifacts=artifacts,
    )
    return summary
