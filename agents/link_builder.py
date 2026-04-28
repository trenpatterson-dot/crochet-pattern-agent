"""
Centralized URL generation for pattern and product links.

Keeps current direct links intact where possible, while routing all final
email-facing URLs through one place so future affiliate parameters can be
added safely.
"""

from urllib.parse import quote_plus, urlparse, urlunparse

KNOWN_STORE_DOMAINS = {
    "michaels.com",
    "joann.com",
    "yarnspirations.com",
    "lionbrand.com",
    "amazon.com",
    "lovecrafts.com",
    "purlsoho.com",
}

STORE_SEARCH_URLS = {
    "michaels.com": "https://www.michaels.com/search?q={query}",
    "joann.com": "https://www.joann.com/search/?q={query}",
    "yarnspirations.com": "https://www.yarnspirations.com/search?q={query}",
    "lionbrand.com": "https://www.lionbrand.com/search?q={query}",
    "amazon.com": "https://www.amazon.com/s?k={query}",
    "lovecrafts.com": "https://www.lovecrafts.com/en-us/search?q={query}",
    "purlsoho.com": "https://www.purlsoho.com/search?type=product&q={query}",
}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _sanitize_direct_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def _apply_future_affiliate_params(url: str, link_type: str) -> str:
    # Placeholder only. Keep URLs unchanged until affiliate activation is approved.
    _ = link_type
    return url


def finalize_url(url: str, link_type: str) -> str:
    sanitized = _sanitize_direct_url(url)
    if not sanitized:
        return ""
    return _apply_future_affiliate_params(sanitized, link_type=link_type)


def generate_pattern_url(pattern_name: str) -> str:
    query = quote_plus(f"{pattern_name} crochet pattern")
    return _apply_future_affiliate_params(
        f"https://www.google.com/search?q={query}",
        link_type="pattern",
    )


def generate_product_url(item_name: str, preferred_domain: str = "") -> str:
    normalized_domain = preferred_domain.lower().replace("www.", "").strip()
    query = quote_plus(item_name)
    template = STORE_SEARCH_URLS.get(normalized_domain)
    if template:
        return _apply_future_affiliate_params(
            template.format(query=query),
            link_type="product",
        )
    return _apply_future_affiliate_params(
        f"https://www.google.com/search?q={quote_plus(f'{item_name} crochet supplies')}",
        link_type="product",
    )


def infer_store_domain(store_name: str = "", url: str = "") -> str:
    domain = _domain(url)
    if domain in KNOWN_STORE_DOMAINS:
        return domain

    normalized = store_name.strip().lower()
    if "michaels" in normalized:
        return "michaels.com"
    if "joann" in normalized:
        return "joann.com"
    if "yarnspirations" in normalized:
        return "yarnspirations.com"
    if "lion brand" in normalized:
        return "lionbrand.com"
    if "amazon" in normalized:
        return "amazon.com"
    if "love crafts" in normalized or "lovecrafts" in normalized:
        return "lovecrafts.com"
    if "purl soho" in normalized:
        return "purlsoho.com"
    return ""
