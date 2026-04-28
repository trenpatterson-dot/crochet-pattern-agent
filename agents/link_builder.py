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
SMART_QUERY_MAP = {
    "scissors": "small craft scissors Fiskars",
    "stitch markers": "locking stitch markers crochet pack",
    "stuffing": "polyester fiberfill stuffing small bag",
    "yarn": "worsted weight yarn beginner soft acrylic",
    "crochet hook": "ergonomic crochet hook set beginner",
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


def generate_pattern_search_url(pattern_name: str, source_site: str = "") -> str:
    query_parts = [pattern_name.strip(), "crochet pattern"]
    normalized_site = (source_site or "").strip().lower()
    if "ravelry" in normalized_site:
        query_parts.append("site:ravelry.com")
    elif normalized_site:
        query_parts.append(f"site:{normalized_site}")

    query = quote_plus(" ".join(part for part in query_parts if part))
    return _apply_future_affiliate_params(
        f"https://www.google.com/search?q={query}",
        link_type="pattern",
    )


def material_query_normalizer(item_name: str, hook_size: str = "") -> str:
    raw = (item_name or "").strip()
    lowered = raw.lower()

    if "scissors" in lowered:
        return SMART_QUERY_MAP["scissors"]
    if "yarn needle" in lowered or "tapestry needle" in lowered:
        return "yarn needle set blunt tip"
    if "stitch marker" in lowered:
        return SMART_QUERY_MAP["stitch markers"]
    if "stuffing" in lowered or "fiberfill" in lowered:
        return SMART_QUERY_MAP["stuffing"]
    if "crochet hook" in lowered or "hook" in lowered:
        size = (hook_size or "").strip()
        if not size:
            for token in raw.replace("(", " ").replace(")", " ").split():
                if "mm" in token.lower():
                    size = token
                    break
        size = size or "crochet hook"
        return f"{size} crochet hook ergonomic beginner set".strip()
    if "yarn" == lowered or lowered.startswith("yarn "):
        if "worsted" in lowered or "acrylic" in lowered:
            return f"{raw} beginner soft acrylic".strip()
        return SMART_QUERY_MAP["yarn"]

    return raw


def refine_product_query(item_name: str, hook_size: str = "") -> str:
    raw = (item_name or "").strip()
    lowered = raw.lower()

    if "scissors" in lowered:
        return "small craft scissors"
    if "yarn needle" in lowered or "tapestry needle" in lowered:
        return "large eye tapestry needle set"
    if "stitch marker" in lowered:
        return "crochet stitch marker pack"
    if "stuffing" in lowered or "fiberfill" in lowered:
        return "polyester fiberfill stuffing"
    if "crochet hook" in lowered or "hook" in lowered:
        size = (hook_size or "").strip()
        if not size:
            for token in raw.replace("(", " ").replace(")", " ").split():
                if "mm" in token.lower():
                    size = token
                    break
        size = size or ""
        return f"{size} crochet hook ergonomic".strip()
    if "yarn" in lowered:
        return "soft acrylic crochet yarn"
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


def _amazon_search_url(query_text: str) -> str:
    return f"https://www.amazon.com/s?k={quote_plus(query_text)}"


def generate_product_url(item_name: str, preferred_domain: str = "", hook_size: str = "") -> str:
    query_text = material_query_normalizer(item_name, hook_size=hook_size)
    return build_affiliate_url(
        _amazon_search_url(query_text),
        store_domain="amazon.com",
        query=query_text,
        link_type="product",
    )


def generate_retry_product_url(item_name: str, hook_size: str = "") -> str:
    query_text = refine_product_query(item_name, hook_size=hook_size)
    return build_affiliate_url(
        _amazon_search_url(query_text),
        store_domain="amazon.com",
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
