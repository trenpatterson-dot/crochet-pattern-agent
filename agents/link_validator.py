"""
Pattern link validation helpers.

Validates final found-pattern links without adding much latency.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from agents import link_builder

KNOWN_PATTERN_DOMAINS = {
    "etsy.com",
    "ravelry.com",
    "blogspot.com",
    "wordpress.com",
    "allfreecrochet.com",
    "yarnspirations.com",
    "lionbrand.com",
    "lovecrafts.com",
    "garnstudio.com",
    "purlsoho.com",
    "redheart.com",
    "thesprucecrafts.com",
}

KNOWN_STORE_DOMAINS = link_builder.KNOWN_STORE_DOMAINS


def _search_fallback(title: str) -> str:
    return link_builder.generate_pattern_url(title)


def _material_search_fallback(name: str, store_name: str = "", url: str = "") -> str:
    domain = link_builder.infer_store_domain(store_name, url)
    return link_builder.generate_product_url(name, preferred_domain=domain)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _looks_like_direct_pattern_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    return bool(parsed.netloc and parsed.path and parsed.path != "/")


def _validate_url(url: str, timeout_seconds: float = 4.0) -> tuple[bool, str, int | None]:
    if not _looks_like_direct_pattern_url(url):
        return False, url, None

    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
            )
        },
        method="GET",
    )
    with urlopen(req, timeout=timeout_seconds) as response:
        status = getattr(response, "status", None)
        final_url = response.geturl() or url
        return status == 200, final_url, status


def _validate_pattern(pattern: dict) -> dict:
    validated = dict(pattern)
    url = (validated.get("url") or "").strip()
    title = validated.get("title", "crochet pattern")
    domain = _domain(url)

    try:
        ok, final_url, status = _validate_url(url)
    except Exception as exc:
        fallback = _search_fallback(title)
        print(
            f"    [Link Validator] INVALID: {title} -> {url or 'missing url'} "
            f"({exc}). Replaced with search fallback."
        )
        validated["url"] = fallback
        validated["link_validation_note"] = f"invalid link replaced ({exc})"
        return validated

    if ok:
        if final_url != url:
            print(f"    [Link Validator] REPLACED: {title} -> redirected to {final_url}")
        elif domain in KNOWN_PATTERN_DOMAINS:
            print(f"    [Link Validator] OK: {title} -> {final_url}")
        else:
            print(f"    [Link Validator] OK (non-known domain): {title} -> {final_url}")
        validated["url"] = link_builder.finalize_url(final_url, link_type="pattern")
        validated["link_validation_note"] = "validated 200"
        return validated

    fallback = _search_fallback(title)
    print(
        f"    [Link Validator] INVALID: {title} -> {url or 'missing url'} "
        f"(status={status}). Replaced with search fallback."
    )
    validated["url"] = fallback
    validated["link_validation_note"] = f"invalid link replaced (status={status})"
    return validated


def validate_patterns(patterns: list[dict]) -> list[dict]:
    if not patterns:
        return []

    max_workers = min(4, len(patterns))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(_validate_pattern, patterns))


def _validate_material_link(material: dict, pattern_title: str) -> dict:
    validated = dict(material)
    name = validated.get("name", "crochet supply")
    url = (validated.get("store_url") or "").strip()
    store_name = validated.get("store_name", "")
    domain = link_builder.infer_store_domain(store_name, url)
    hook_size = validated.get("hook_size", "")
    strategy = "vendor_search"

    fallback = link_builder.generate_product_url(name, preferred_domain=domain, hook_size=hook_size)
    validated["affiliate_url"] = fallback
    validated["store_url"] = fallback
    validated["approx_price"] = "Price varies by retailer"
    if fallback.startswith("https://www.google.com/search?q="):
        strategy = "google_fallback"
    validated["material_link_strategy"] = strategy
    validated["link_validation_note"] = "search link generated"

    try:
        ok, final_url, status = _validate_url(url)
    except Exception as exc:
        print(
            f"    [Link Validator] INVALID MATERIAL: {pattern_title} / {name} -> {url or 'missing url'} "
            f"({exc}). Replaced with search fallback. material_link_strategy={strategy}"
        )
        validated["link_validation_note"] = f"invalid material link replaced ({exc})"
        return validated

    if ok:
        print(
            f"    [Link Validator] OK MATERIAL: {pattern_title} / {name} -> {fallback} "
            f"(material_link_strategy={strategy})"
        )
        validated["link_validation_note"] = "validated 200 via search strategy"
        return validated

    print(
        f"    [Link Validator] INVALID MATERIAL: {pattern_title} / {name} -> {url or 'missing url'} "
        f"(status={status}). Replaced with search fallback. material_link_strategy={strategy}"
    )
    validated["link_validation_note"] = f"invalid material link replaced (status={status})"
    return validated


def _validate_tutorial_link(pattern: dict) -> dict:
    validated = dict(pattern)
    tutorial = dict(validated.get("video_tutorial") or {})
    title = validated.get("title", "crochet pattern")
    original_url = (tutorial.get("url") or "").strip()
    fallback_url = link_builder.generate_tutorial_search_url(title)
    tutorial["button_text"] = "Search Tutorial"
    tutorial["tutorial_link_status"] = "fallback"

    video_id = link_builder.extract_youtube_video_id(original_url)
    if not video_id:
        tutorial["url"] = fallback_url
        tutorial["title"] = tutorial.get("title") or f"Search tutorial for {title}"
        validated["video_tutorial"] = tutorial
        print(
            f"    [Link Validator] TUTORIAL FALLBACK: {title} -> missing valid video ID. "
            f"tutorial_link_status=fallback"
        )
        return validated

    clean_url = link_builder.finalize_tutorial_url(original_url)
    oembed_url = f"https://www.youtube.com/oembed?url={quote_plus(clean_url)}&format=json"
    try:
        ok, final_url, status = _validate_url(oembed_url)
    except Exception as exc:
        tutorial["url"] = fallback_url
        tutorial["title"] = tutorial.get("title") or f"Search tutorial for {title}"
        tutorial["link_validation_note"] = f"tutorial fallback ({exc})"
        validated["video_tutorial"] = tutorial
        print(
            f"    [Link Validator] TUTORIAL FALLBACK: {title} -> {clean_url} ({exc}). "
            f"tutorial_link_status=fallback"
        )
        return validated

    if ok:
        tutorial["url"] = clean_url
        tutorial["button_text"] = "Tutorial"
        tutorial["tutorial_link_status"] = "valid"
        tutorial["link_validation_note"] = "validated 200 via oembed"
        validated["video_tutorial"] = tutorial
        print(f"    [Link Validator] TUTORIAL OK: {title} -> {clean_url} tutorial_link_status=valid")
        return validated

    tutorial["url"] = fallback_url
    tutorial["title"] = tutorial.get("title") or f"Search tutorial for {title}"
    tutorial["link_validation_note"] = f"tutorial fallback (status={status})"
    validated["video_tutorial"] = tutorial
    print(
        f"    [Link Validator] TUTORIAL FALLBACK: {title} -> {clean_url} (status={status}). "
        f"tutorial_link_status=fallback"
    )
    return validated


def validate_material_links(patterns: list[dict]) -> list[dict]:
    if not patterns:
        return []

    validated_patterns = []
    for pattern in patterns:
        normalized = dict(pattern)
        materials = normalized.get("materials") or []
        title = normalized.get("title", "pattern")
        if not materials:
            validated_patterns.append(normalized)
            continue

        max_workers = min(4, len(materials))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            normalized["materials"] = list(
                pool.map(lambda material: _validate_material_link(material, title), materials)
            )
        validated_patterns.append(normalized)

    return validated_patterns


def validate_tutorial_links(patterns: list[dict]) -> list[dict]:
    if not patterns:
        return []
    return [_validate_tutorial_link(pattern) if pattern.get("video_tutorial") else dict(pattern) for pattern in patterns]
