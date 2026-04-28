"""
Pattern link validation helpers.

Validates final found-pattern links without adding much latency.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from agents import link_builder, llm

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
ERROR_TEXT_MARKERS = {
    "we're sorry",
    "we’re sorry",
    "page not found",
    "404",
    "sorry, we can't find",
    "sorry, we cant find",
}


def _search_fallback(title: str) -> str:
    return link_builder.generate_pattern_url(title)


def _safe_pattern_search_fallback(title: str, source_site: str = "") -> str:
    return link_builder.generate_pattern_search_url(title, source_site=source_site)


def _material_search_fallback(name: str, store_name: str = "", url: str = "") -> str:
    return link_builder.generate_product_url(name)


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


def _is_allowed_ravelry_url(url: str) -> bool:
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().replace("www.", "")
    if domain != "ravelry.com":
        return True
    return "/patterns/library/" in (parsed.path or "")


def _pattern_candidate_queries(title: str, source_site: str = "") -> list[str]:
    normalized_site = (source_site or "").strip().lower()
    queries = []
    if "ravelry" in normalized_site:
        queries.append(f'{title} crochet pattern site:ravelry.com/patterns/library')
    elif normalized_site:
        queries.append(f'{title} crochet pattern site:{normalized_site}')
    queries.append(f"{title} crochet pattern")
    return queries


def _search_replacement_pattern_url(title: str, source_site: str, original_url: str = "") -> tuple[str, str]:
    original_finalized = link_builder.finalize_url(original_url, link_type="pattern")
    seen = {original_url.strip(), original_finalized}
    for query in _pattern_candidate_queries(title, source_site=source_site):
        results = llm.ddg_search(query, max_results=6)
        for result in results:
            candidate_url = (result.get("href") or result.get("url") or "").strip()
            if not candidate_url or candidate_url in seen:
                continue
            if not _is_allowed_ravelry_url(candidate_url):
                continue
            try:
                ok, final_url, status = _validate_url(candidate_url)
            except Exception:
                continue
            if not ok or status != 200 or not _is_allowed_ravelry_url(final_url):
                continue
            return link_builder.finalize_url(final_url, link_type="pattern"), query
    return "", ""


def _set_pattern_link_mode(pattern: dict, *, direct_url: str = "", search_url: str = "", note: str = "") -> dict:
    updated = dict(pattern)
    updated["url"] = direct_url
    updated["pattern_url"] = direct_url
    updated["pattern_search_url"] = search_url
    updated["pattern_link_status"] = "valid" if direct_url else "fallback_search"
    updated["pattern_cta_label"] = "View Pattern" if direct_url else ("Search Pattern" if search_url else "")
    updated["pattern_cta_url"] = direct_url or search_url
    if note:
        updated["link_validation_note"] = note
    return updated


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


def _is_unexpected_homepage_redirect(original_url: str, final_url: str) -> bool:
    try:
        original = urlparse(original_url.strip())
        final = urlparse(final_url.strip())
    except Exception:
        return False

    original_domain = (original.netloc or "").lower().replace("www.", "")
    final_domain = (final.netloc or "").lower().replace("www.", "")
    original_path = (original.path or "").strip("/")
    final_path = (final.path or "").strip("/")

    if not original_domain or original_domain != final_domain:
        return False
    if not original_path:
        return False
    return final_path == ""


def _page_contains_error_text(url: str, timeout_seconds: float = 4.0) -> tuple[bool, str]:
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
        body = response.read(8192)
        content = body.decode("utf-8", errors="ignore").lower()
        for marker in ERROR_TEXT_MARKERS:
            if marker in content:
                return True, marker
    return False, ""


def _is_lovecrafts_product_or_category_url(url: str) -> bool:
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().replace("www.", "")
    if domain != "lovecrafts.com":
        return True
    path = (parsed.path or "").lower()
    if "/en-us/search" in path:
        return True
    return any(
        token in path
        for token in ("/p/", "/product/", "/products/", "/category/", "/categories/", "/collections/")
    )


def _validate_external_material_url(url: str) -> tuple[bool, str, int | None, str]:
    if not _looks_like_direct_pattern_url(url):
        return False, url, None, "not a direct URL"
    try:
        ok, final_url, status = _validate_url(url)
    except Exception as exc:
        return False, url, None, str(exc)
    if not ok or status != 200:
        return False, final_url, status, f"status={status}"
    if _is_unexpected_homepage_redirect(url, final_url):
        return False, final_url, status, "unexpected homepage redirect"
    try:
        has_error_text, marker = _page_contains_error_text(final_url)
    except Exception as exc:
        return False, final_url, status, f"content check failed ({exc})"
    if has_error_text:
        return False, final_url, status, f"error text detected ({marker})"
    if not _is_lovecrafts_product_or_category_url(final_url):
        return False, final_url, status, "invalid LoveCrafts URL shape"
    return True, final_url, status, "validated"


def _set_material_link_mode(
    material: dict,
    *,
    cta_url: str = "",
    cta_label: str = "Shop Materials",
    strategy: str = "",
    note: str = "",
    store_url: str = "",
    affiliate_url: str = "",
    store_name: str = "",
) -> dict:
    updated = dict(material)
    updated["material_cta_url"] = cta_url
    updated["material_cta_label"] = cta_label if cta_url else ""
    updated["affiliate_url"] = affiliate_url or cta_url
    updated["store_url"] = store_url or cta_url
    updated["store_name"] = store_name or updated.get("store_name", "")
    updated["material_link_strategy"] = strategy
    updated["link_validation_note"] = note
    updated["approx_price"] = "Price varies by retailer"
    return updated


def _validate_pattern(pattern: dict) -> dict:
    validated = dict(pattern)
    url = (validated.get("url") or "").strip()
    title = validated.get("title", "crochet pattern")
    source_site = validated.get("source_site", "")
    fallback_search_url = _safe_pattern_search_fallback(title, source_site=source_site)

    if not url:
        print(f"    [Link Validator] MISSING: {title} -> no URL. Using search fallback.")
        return _set_pattern_link_mode(
            validated,
            search_url=fallback_search_url,
            note="missing direct pattern link; using search fallback",
        )

    if not _is_allowed_ravelry_url(url):
        retry_url, retry_query = _search_replacement_pattern_url(title, source_site, original_url=url)
        if retry_url:
            print(
                f"    [Link Validator] RETRY RAVELRY: {title} -> {retry_url} "
                f"(query={retry_query})"
            )
            return _set_pattern_link_mode(
                validated,
                direct_url=retry_url,
                note=f"replaced invalid ravelry URL via retry search ({retry_query})",
            )
        print(
            f"    [Link Validator] INVALID RAVELRY: {title} -> {url} "
            "missing /patterns/library/. Using search fallback."
        )
        return _set_pattern_link_mode(
            validated,
            search_url=fallback_search_url,
            note="invalid ravelry URL replaced with search fallback",
        )

    try:
        ok, final_url, status = _validate_url(url)
    except Exception as exc:
        retry_url, retry_query = _search_replacement_pattern_url(title, source_site, original_url=url)
        if retry_url:
            print(
                f"    [Link Validator] RETRY: {title} -> {retry_url} "
                f"(reason={exc}, query={retry_query})"
            )
            return _set_pattern_link_mode(
                validated,
                direct_url=retry_url,
                note=f"validated 200 after retry search ({retry_query})",
            )
        print(
            f"    [Link Validator] INVALID: {title} -> {url or 'missing url'} "
            f"({exc}). Using search fallback."
        )
        return _set_pattern_link_mode(
            validated,
            search_url=fallback_search_url,
            note=f"invalid link replaced with search fallback ({exc})",
        )

    if ok:
        if not _is_allowed_ravelry_url(final_url):
            retry_url, retry_query = _search_replacement_pattern_url(title, source_site, original_url=final_url)
            if retry_url:
                print(
                    f"    [Link Validator] RETRY RAVELRY REDIRECT: {title} -> {retry_url} "
                    f"(query={retry_query})"
                )
                return _set_pattern_link_mode(
                    validated,
                    direct_url=retry_url,
                    note=f"replaced redirected ravelry URL via retry search ({retry_query})",
                )
            print(
                f"    [Link Validator] INVALID RAVELRY REDIRECT: {title} -> {final_url} "
                "missing /patterns/library/. Using search fallback."
            )
            return _set_pattern_link_mode(
                validated,
                search_url=fallback_search_url,
                note="invalid ravelry redirect replaced with search fallback",
            )
        domain = _domain(final_url)
        if final_url != url:
            print(f"    [Link Validator] REPLACED: {title} -> redirected to {final_url}")
        elif domain in KNOWN_PATTERN_DOMAINS:
            print(f"    [Link Validator] OK: {title} -> {final_url}")
        else:
            print(f"    [Link Validator] OK (non-known domain): {title} -> {final_url}")
        return _set_pattern_link_mode(
            validated,
            direct_url=link_builder.finalize_url(final_url, link_type="pattern"),
            note="validated 200",
        )

    retry_url, retry_query = _search_replacement_pattern_url(title, source_site, original_url=url)
    if retry_url:
        print(
            f"    [Link Validator] RETRY STATUS: {title} -> {retry_url} "
            f"(status={status}, query={retry_query})"
        )
        return _set_pattern_link_mode(
            validated,
            direct_url=retry_url,
            note=f"validated 200 after retry search ({retry_query})",
        )

    print(
        f"    [Link Validator] INVALID: {title} -> {url or 'missing url'} "
        f"(status={status}). Using search fallback."
    )
    return _set_pattern_link_mode(
        validated,
        search_url=fallback_search_url,
        note=f"invalid link replaced with search fallback (status={status})",
    )


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
    store_domain = link_builder.infer_store_domain(store_name=store_name, url=url)
    hook_size = validated.get("hook_size", "")
    amazon_fallback = link_builder.generate_product_url(name, hook_size=hook_size)
    amazon_retry = link_builder.generate_retry_product_url(name, hook_size=hook_size)

    if store_domain and store_domain != "amazon.com" and url:
        ok, final_url, _, reason = _validate_external_material_url(url)
        if ok:
            final_domain = _domain(final_url)
            print(
                f"    [Link Validator] OK MATERIAL: {pattern_title} / {name} -> {final_url} "
                f"(material_link_strategy=validated_external_store, store={final_domain})"
            )
            return _set_material_link_mode(
                validated,
                cta_url=link_builder.finalize_url(final_url, link_type="product"),
                strategy="validated_external_store",
                note="validated external store URL",
                store_url=link_builder.finalize_url(final_url, link_type="product"),
                affiliate_url=link_builder.finalize_url(final_url, link_type="product"),
                store_name=store_name or link_builder._vendor_name_for_domain(final_domain),
            )

        if store_domain == "lovecrafts.com":
            lovecrafts_search = link_builder.generate_store_search_url(name, "lovecrafts.com", hook_size=hook_size)
            print(
                f"    [Link Validator] FALLBACK MATERIAL: {pattern_title} / {name} -> {lovecrafts_search} "
                f"(reason={reason}, material_link_strategy=lovecrafts_search_fallback)"
            )
            return _set_material_link_mode(
                validated,
                cta_url=lovecrafts_search,
                strategy="lovecrafts_search_fallback",
                note=f"invalid LoveCrafts direct link replaced with search fallback ({reason})",
                store_url=lovecrafts_search,
                affiliate_url=lovecrafts_search,
                store_name="LoveCrafts",
            )

        print(
            f"    [Link Validator] LOW CONFIDENCE MATERIAL: {pattern_title} / {name} -> {url} "
            f"(reason={reason}). Preferring Amazon affiliate fallback."
        )

    print(
        f"    [Link Validator] OK MATERIAL: {pattern_title} / {name} -> {amazon_fallback} "
        "(material_link_strategy=amazon_affiliate_search, validation=structured_amazon_affiliate)"
    )
    return _set_material_link_mode(
        validated,
        cta_url=amazon_fallback,
        strategy="amazon_affiliate_search",
        note="validated structured amazon affiliate search",
        store_url=amazon_fallback,
        affiliate_url=amazon_fallback,
        store_name="Amazon",
    )


def _validate_tutorial_link(pattern: dict) -> dict:
    validated = dict(pattern)
    tutorial = dict(validated.get("video_tutorial") or {})
    candidates = []
    seen = set()
    for candidate in [tutorial] + list(validated.get("tutorial_candidates") or []):
        url = (candidate or {}).get("url")
        if url and url not in seen:
            seen.add(url)
            candidates.append(dict(candidate))
    title = validated.get("title", "crochet pattern")
    for candidate in candidates:
        original_url = (candidate.get("url") or "").strip()
        video_id = link_builder.extract_youtube_video_id(original_url)
        if not video_id:
            continue

        clean_url = link_builder.finalize_tutorial_url(original_url)
        oembed_url = f"https://www.youtube.com/oembed?url={quote_plus(clean_url)}&format=json"
        try:
            ok, _, status = _validate_url(oembed_url)
            page_ok, page_final_url, _ = _validate_url(clean_url)
        except Exception:
            continue

        if ok and page_ok:
            candidate["url"] = page_final_url
            candidate["button_text"] = "Tutorial"
            candidate["tutorial_link_status"] = "valid"
            candidate["link_validation_note"] = "validated 200 via oembed and page check"
            validated["video_tutorial"] = candidate
            print(f"    [Link Validator] TUTORIAL OK: {title} -> {page_final_url} tutorial_link_status=valid")
            return validated

    print(f"    [Link Validator] TUTORIAL REMOVED: {title} -> no valid candidate tutorial_link_status=removed")
    validated["video_tutorial"] = None
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
