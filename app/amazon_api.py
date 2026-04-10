"""
Amazon product search via SerpAPI (Google Shopping).

Searches Amazon products for a keyword using SerpAPI's Google Shopping engine,
extracts ASIN from product URLs, and builds affiliate links automatically.
"""
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")


def _extract_asin(url: str) -> Optional[str]:
    m = _ASIN_RE.search(url or "")
    return m.group(1) if m else None


def _build_affiliate_url(asin: str, associate_tag: str) -> str:
    return f"https://www.amazon.com/dp/{asin}?tag={associate_tag}"


def _category_to_query_suffix(category: Optional[str]) -> str:
    suffixes = {
        "beauty":     "beauty skincare makeup",
        "fashion":    "women fashion clothing",
        "home_decor": "home decor aesthetic",
        "kitchen":    "kitchen gadgets",
        "office":     "desk office supplies",
        "tech":       "tech gadgets",
        "fitness":    "fitness workout",
        "garden":     "garden outdoor",
        "pets":       "pet supplies",
        "art":        "art craft supplies",
    }
    return suffixes.get(category or "", "")


def search_products(
    keyword: str,
    category: Optional[str] = None,
    max_results: int = 8,
) -> list[dict]:
    """
    Search Amazon via SerpAPI Google Shopping for products matching `keyword`.

    Returns a list of dicts with keys:
        name, asin, amazon_url, image_url, price, category
    Returns empty list if SerpAPI is not configured or search fails.
    """
    from config import Config

    if not Config.SERP_API_KEY:
        logger.warning("SERP_API_KEY not configured — skipping product search")
        return []

    suffix = _category_to_query_suffix(category)
    query  = f"{keyword} {suffix} site:amazon.com".strip()

    try:
        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "engine":   "google_shopping",
                "q":        query,
                "api_key":  Config.SERP_API_KEY,
                "num":      max_results,
                "gl":       "us",
                "hl":       "en",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"SerpAPI search failed for '{keyword}': {e}")
        return []

    results  = data.get("shopping_results", [])
    products = []

    for item in results[:max_results]:
        link  = item.get("link", "")
        title = item.get("title", "")
        if not title:
            continue

        # Only keep Amazon results
        if "amazon.com" not in link:
            continue

        asin = _extract_asin(link)
        if not asin:
            # Try product_link field
            asin = _extract_asin(item.get("product_link", ""))

        affiliate_url = (
            _build_affiliate_url(asin, Config.AMAZON_ASSOCIATE_TAG)
            if asin and Config.AMAZON_ASSOCIATE_TAG
            else link
        )

        # Price
        price = item.get("price")
        if price and not str(price).startswith("$"):
            price = f"${price}"

        products.append({
            "name":       title[:255],
            "asin":       asin,
            "amazon_url": affiliate_url,
            "image_url":  item.get("thumbnail"),
            "price":      str(price) if price else None,
            "category":   category or "general",
        })

    return products


def discover_products_for_trends(trends: list[dict], per_trend: int = 5) -> list[dict]:
    """
    Given a list of trend dicts (with 'keyword' and 'category' keys),
    search Amazon for each and return all candidates combined.
    Deduplicates by ASIN.
    """
    seen_asins: set[str] = set()
    all_candidates = []

    for trend in trends:
        keyword  = trend.get("keyword", "")
        category = trend.get("category")
        if not keyword:
            continue

        results = search_products(keyword, category=category, max_results=per_trend)
        for r in results:
            asin = r.get("asin")
            if asin and asin in seen_asins:
                continue
            if asin:
                seen_asins.add(asin)
            r["trend_keyword"] = keyword
            all_candidates.append(r)

    return all_candidates
