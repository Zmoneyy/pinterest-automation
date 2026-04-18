"""
Amazon product search via SerpAPI Amazon engine.

Searches Amazon directly using SerpAPI's Amazon engine,
returning product titles, images, prices, ASINs, and affiliate links.
"""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def _build_affiliate_url(asin: str, associate_tag: str) -> str:
    return f"https://www.amazon.com/dp/{asin}?tag={associate_tag}"


def _category_to_query_suffix(category: Optional[str]) -> str:
    suffixes = {
        "beauty":     "beauty",
        "fashion":    "women fashion",
        "home_decor": "home decor",
        "kitchen":    "kitchen",
        "office":     "office supplies",
        "tech":       "tech gadgets",
        "fitness":    "fitness",
        "garden":     "garden",
        "pets":       "pet supplies",
        "art":        "art craft",
    }
    return suffixes.get(category or "", "")


def search_products(
    keyword: str,
    category: Optional[str] = None,
    max_results: int = 8,
) -> list[dict]:
    """
    Search Amazon directly via SerpAPI Amazon engine.

    Returns a list of dicts with keys:
        name, asin, amazon_url, image_url, price, category
    Returns empty list if SerpAPI is not configured or search fails.
    """
    from config import Config

    if not Config.SERP_API_KEY:
        logger.warning("SERP_API_KEY not configured — skipping product search")
        return []

    suffix = _category_to_query_suffix(category)
    query  = f"{keyword} {suffix}".strip()

    try:
        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "engine":  "amazon",
                "k":       query,
                "api_key": Config.SERP_API_KEY,
                "amazon_domain": "amazon.com",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"SerpAPI Amazon search failed for '{keyword}': {e}")
        return []

    results  = data.get("organic_results", [])
    products = []

    for item in results[:max_results]:
        asin  = item.get("asin")
        title = item.get("title", "")
        if not title or not asin:
            continue

        affiliate_url = (
            _build_affiliate_url(asin, Config.AMAZON_ASSOCIATE_TAG)
            if Config.AMAZON_ASSOCIATE_TAG
            else f"https://www.amazon.com/dp/{asin}"
        )

        price = item.get("price") or item.get("price_unit")

        products.append({
            "name":       title[:255],
            "asin":       asin,
            "amazon_url": affiliate_url,
            "image_url":  item.get("thumbnail"),
            "price":      price,
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


# Evergreen search queries — focused on 3 core niches: Beauty, Home Decor, Kitchen
EVERGREEN_QUERIES = [
    # Beauty
    ("press on nails amazon", "beauty"),
    ("nail art kit amazon", "beauty"),
    ("skincare routine amazon affordable", "beauty"),
    ("face serum amazon", "beauty"),
    ("lip gloss set amazon", "beauty"),
    ("makeup brush set amazon", "beauty"),
    ("lash serum amazon", "beauty"),
    ("tanning drops amazon", "beauty"),
    ("sunscreen amazon beauty", "beauty"),
    ("hair accessories aesthetic amazon", "beauty"),
    # Home Decor
    ("candle warmer aesthetic amazon", "home_decor"),
    ("aesthetic room decor amazon", "home_decor"),
    ("throw pillow covers amazon", "home_decor"),
    ("wall art prints amazon", "home_decor"),
    ("cozy home finds amazon", "home_decor"),
    ("vase aesthetic amazon", "home_decor"),
    ("picture frames aesthetic amazon", "home_decor"),
    ("amazon home decor under 30", "home_decor"),
    # Health & Wellness
    ("collagen supplements amazon", "fitness"),
    ("glow skin supplements amazon", "fitness"),
    ("sunscreen amazon spf", "fitness"),
    ("self care products amazon", "fitness"),
    ("tanning drops amazon", "fitness"),
    ("wellness supplements amazon women", "fitness"),
    ("hair growth supplements amazon", "fitness"),
    ("amazon water bottle aesthetic", "fitness"),
    ("vitamins for women amazon", "fitness"),
]


def discover_evergreen_products(per_query: int = 4) -> list[dict]:
    """
    Search Amazon for evergreen + seasonal products across all 3 niches.
    Runs daily to keep the approval queue stocked with variety.
    """
    from app.seasonal import get_seasonal_search_queries, get_current_season

    season_info = get_current_season()
    seasonal_queries = get_seasonal_search_queries()

    # Combine evergreen + seasonal queries
    all_queries = list(EVERGREEN_QUERIES) + seasonal_queries

    seen_asins: set[str] = set()
    all_candidates = []

    for query, category in all_queries:
        results = search_products(query, category=category, max_results=per_query)
        for r in results:
            asin = r.get("asin")
            if asin and asin in seen_asins:
                continue
            if asin:
                seen_asins.add(asin)
            r["trend_keyword"] = query
            all_candidates.append(r)

    logger.info(
        f"Product discovery: {len(all_candidates)} products found "
        f"(season target: {season_info['season']})."
    )
    return all_candidates
