"""
Centralized URL generation for pattern, product, and tutorial links.

Keeps final email-facing URLs routed through one place so future affiliate
parameters can be added safely without rewriting the pipeline.
"""

import os
from urllib.parse import parse_qs, quote_plus, urlparse, urlunparse

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
    "joann.com": "https://www.joann.com/search?q={query}",
    "yarnspirations.com": "https://www.yarnspirations.com/search?q={query}",
    "lionbrand.com": "https://www.lionbrand.com/search?q={query}",
    "amazon.com": "https://www.amazon.com/s?k={query}",
    "lovecrafts.com": "https://www.lovecrafts.com/en-us/search?q={query}",
    "purlsoho.com": "https://www.purlsoho.com/search?type=product&q={query}",
}

AMAZON_ASSOCIATE_TAG = os.getenv("AMAZON_ASSOCIATE_TAG", "").strip()


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
    _ = link_type
    return url


def build_affiliate_url(url: str, store_domain: str = "", query: str = "", link_type: str = "product") -> str:
    sanitized = _sanitize_direct_url(url)
    if not sanitized:
        return ""

    normalized_domain = store_domain.lower().replace("www.", "").strip()
    if normalized_domain == "amazon.com" and AMAZON_ASSOCIATE_TAG:
        parsed = urlparse(sanitized)
        params = parse_qs(parsed.query)
        params["tag"] = [AMAZON_ASSOCIATE_TAG]
        query_string = "&".join(
            f"{key}={quote_plus(value)}"
            for key, values in params.items()
            for value in values
        )
        sanitized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query_string, ""))

    return _apply_future_affiliate_params(sanitized, link_type=link_type)


def finalize_url(url: str, link_type: str) -> str:
    sanitized = _sanitize_direct_url(url)
    if not sanitized:
        return ""
    return build_affiliate_url(sanitized, store_domain=_domain(sanitized), link_type=link_type)


def generate_pattern_url(pattern_name: str) -> str:
    query = quote_plus(f"{pattern_name} crochet pattern")
    return _apply_future_affiliate_params(
        f"https://www.google.com/search?q={query}",
        link_type="pattern",
    )


def material_query_normalizer(item_name: str, hook_size: str = "") -> str:
    raw = (item_name or "").strip()
    lowered = raw.lower()

    if "scissors" in lowered:
        return "small embroidery scissors"
    if "yarn needle" in lowered or "tapestry needle" in lowered:
        return "blunt tip yarn needle set"
    if "stitch marker" in lowered:
        return "locking stitch markers crochet"
    if "stuffing" in lowered or "fiberfill" in lowered:
        return "polyester fiberfill stuffing"
    if "crochet hook" in lowered or "hook" in lowered:
        size = (hook_size or "").strip()
        if not size:
            for token in raw.replace("(", " ").replace(")", " ").split():
                if "mm" in token.lower():
                    size = token
                    break
        size = size or "crochet hook"
        return f"{size} crochet hook".strip()

    return raw


def _vendor_name_for_domain(domain: str) -> str:
    names = {
        "michaels.com": "Michaels",
        "joann.com": "Joann",
        "yarnspirations.com": "Yarnspirations",
        "lionbrand.com": "Lion Brand",
        "amazon.com": "Amazon",
        "lovecrafts.com": "LoveCrafts",
        "purlsoho.com": "Purl Soho",
    }
    return names.get(domain, "")


def _should_use_google_fallback(query: str, preferred_domain: str) -> bool:
    normalized_domain = preferred_domain.lower().replace("www.", "").strip()
    if normalized_domain not in {"michaels.com", "joann.com", "lionbrand.com", "yarnspirations.com"}:
        return True

    generic_terms = {
        "scissors",
        "yarn needle",
        "needle",
        "stitch markers",
        "stuffing",
        "crochet hook",
    }
    return query.strip().lower() in generic_terms


def _is_generic_tool_query(query: str) -> bool:
    normalized = query.strip().lower()
    generic_queries = {
        "small embroidery scissors",
        "blunt tip yarn needle set",
        "locking stitch markers crochet",
        "polyester fiberfill stuffing",
    }
    return normalized in generic_queries or normalized.endswith("crochet hook")


def _google_vendor_search(query: str, vendor_name: str = "") -> str:
    suffix = f" {vendor_name}" if vendor_name else ""
    return f"https://www.google.com/search?q={quote_plus(f'{query}{suffix}')}"


def _amazon_search_url(query_text: str) -> str:
    return f"https://www.amazon.com/s?k={quote_plus(query_text)}"


def generate_product_url(item_name: str, preferred_domain: str = "", hook_size: str = "") -> str:
    normalized_domain = preferred_domain.lower().replace("www.", "").strip()
    query_text = material_query_normalizer(item_name, hook_size=hook_size)
    vendor_name = _vendor_name_for_domain(normalized_domain)

    if _is_generic_tool_query(query_text):
        return build_affiliate_url(
            _amazon_search_url(query_text),
            store_domain="amazon.com",
            query=query_text,
            link_type="product",
        )

    if _should_use_google_fallback(query_text, normalized_domain):
        return build_affiliate_url(
            _google_vendor_search(query_text, vendor_name=vendor_name),
            store_domain="google.com",
            query=query_text,
            link_type="product",
        )

    query = quote_plus(query_text)
    template = STORE_SEARCH_URLS.get(normalized_domain)
    if template:
        return build_affiliate_url(
            template.format(query=query),
            store_domain=normalized_domain,
            query=query_text,
            link_type="product",
        )

    return build_affiliate_url(
        _google_vendor_search(query_text, vendor_name=vendor_name),
        store_domain="google.com",
        query=query_text,
        link_type="product",
    )


def extract_youtube_video_id(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return ""

    host = (parsed.netloc or "").lower().replace("www.", "")
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if len(candidate) >= 11 else ""
    if host in {"youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
            return candidate if len(candidate) >= 11 else ""
        if parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
            candidate = parsed.path.strip("/").split("/")[1]
            return candidate if len(candidate) >= 11 else ""
    return ""


def generate_tutorial_search_url(pattern_name: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(f'{pattern_name} crochet tutorial')}"


def finalize_tutorial_url(url: str) -> str:
    return finalize_url(url, link_type="tutorial")


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
