"""
Amazon product discovery — free scraping, no SerpAPI.

Flow:
  1. Take a trending keyword from Pinterest TrendCache
  2. Search Amazon for that keyword
  3. Extract: name, ASIN, price, image, URL
  4. Return top results → scheduler adds to ProductCandidate queue
"""
import logging
import re
import time
import random
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# High-commission categories to prioritize in searches
# beauty=10%, home=3%, fitness=1% — beauty first always
NICHE_SEARCH_SUFFIXES = {
    "beauty":    ["amazon beauty", "skincare amazon", "makeup amazon finds"],
    "home_decor": ["amazon home decor", "home finds amazon", "room decor amazon"],
    "fitness":   ["amazon wellness", "self care amazon", "supplements amazon"],
}

AMAZON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def _build_affiliate_url(asin: str, associate_tag: str) -> str:
    # Full amazon.com URL — Pinterest trusts these more than amzn.to short links
    return f"https://www.amazon.com/dp/{asin}?tag={associate_tag}&linkCode=ll1&language=en_US&ref_=as_li_ss_tl"


def search_products(
    keyword: str,
    category: Optional[str] = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Search Amazon for products matching a keyword via SerpAPI.
    Falls back to empty list if SerpAPI key not configured.
    Returns list of {name, asin, amazon_url, image_url, price, category}.
    """
    from config import Config

    associate_tag = Config.AMAZON_ASSOCIATE_TAG or "auragirlcreat-20"

    # Try SerpAPI first (works from Cloud Run — no IP blocking)
    serpapi_key = _get_serpapi_key()
    if serpapi_key:
        try:
            results = _search_via_serpapi(keyword, serpapi_key, max_results=max_results)
            for r in results:
                if r.get("asin"):
                    r["amazon_url"] = _build_affiliate_url(r["asin"], associate_tag)
                r["category"] = category or _guess_category(r.get("name", ""))
            logger.info(f"SerpAPI search '{keyword}': {len(results)} products found")
            return results
        except Exception as e:
            logger.error(f"SerpAPI search failed for '{keyword}': {e}")

    return []


def _get_serpapi_key() -> str:
    """Get SerpAPI key from DB setting or environment config."""
    try:
        from app.models import Setting
        key = Setting.get("serpapi_key", "")
        if key:
            return key
    except Exception:
        pass
    from config import Config
    return Config.SERPAPI_KEY or ""


def _search_via_serpapi(keyword: str, api_key: str, max_results: int = 5) -> list[dict]:
    """Search Amazon products using SerpAPI's Amazon Search engine."""
    params = {
        "engine": "amazon",
        "k": keyword,
        "api_key": api_key,
        "amazon_domain": "amazon.com",
    }
    resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    products = []
    organic = data.get("organic_results", [])
    for item in organic[:max_results]:
        asin = item.get("asin", "")
        name = item.get("title", "")
        if not asin or not name:
            continue
        # Price — SerpAPI returns price as string like "$38.00" or float
        price_raw = item.get("price", {})
        if isinstance(price_raw, dict):
            price = str(price_raw.get("value", "0"))
        elif isinstance(price_raw, (int, float)):
            price = str(price_raw)
        else:
            price = str(price_raw).replace("$", "").strip()

        image_url = item.get("thumbnail", "") or item.get("image", "")

        products.append({
            "name": name,
            "asin": asin,
            "image_url": image_url,
            "price": price,
        })

    return products


def _scrape_amazon_search(keyword: str, max_results: int = 5) -> list[dict]:
    """Stub — Amazon blocks Cloud Run IPs. Use SerpAPI instead."""
    return []


def _fetch_amazon_product(asin: str) -> Optional[dict]:
    """Stub — Amazon blocks Cloud Run IPs. Use SerpAPI instead."""
    return None


def discover_products_for_trends(trends: list[dict], per_trend: int = 3) -> list[dict]:
    """
    Search Amazon for products matching Pinterest trend keywords.
    All queries come from TrendEntry data — nothing hardcoded.
    """
    all_products = []
    seen_asins = set()

    for trend in trends[:20]:
        keyword         = trend.get("keyword", "")
        niche           = trend.get("niche") or trend.get("category", "beauty")
        source_category = trend.get("source_category", "")
        if not keyword:
            continue
        products = search_products(keyword, category=niche, max_results=per_trend)
        for p in products:
            asin = p.get("asin", "")
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
                p["trend_keyword"]   = keyword
                p["source_category"] = source_category
                all_products.append(p)
        time.sleep(random.uniform(2, 4))

    return all_products


# Luxury Beauty brands on Amazon → 10% commission
LUXURY_BEAUTY_BRANDS = [
    "la mer", "tatcha", "charlotte tilbury", "sk-ii", "sk ii", "sisley",
    "sulwhasoo", "valmont", "dr. barbara sturm", "barbara sturm", "augustinus bader",
    "dyson", "nars", "pat mcgrath", "pat mcgrath labs", "hourglass", "by terry",
    "drunk elephant", "de la mer", "cle de peau", "clé de peau", "shiseido",
    "estee lauder", "estée lauder", "lancome", "lancôme", "ysl beauty",
    "yves saint laurent", "giorgio armani beauty", "dior beauty", "chanel beauty",
    "givenchy beauty", "tom ford beauty", "guerlain", "la prairie",
    "peter thomas roth", "sunday riley", "kate somerville", "perricone md",
    "tata harper", "ilia", "westman atelier", "merit", "rare beauty",
    # Additional luxury beauty brands from TrendEntry products
    "clinique", "jan marini", "caudalie", "dr. jart", "dr jart", "laneige",
    "embryolisse", "erborian", "la roche-posay", "la roche posay", "avene",
    "avène", "cle de peau", "beaute", "beauté", "kiehl's", "kiehls",
    "origins", "fresh beauty", "olehenriksen", "ole henriksen",
    "boscia", "belif", "innisfree", "missha", "some by mi",
    "paula's choice", "paulas choice", "the ordinary", "niod",
    "medik8", "image skincare", "obagi", "skinceuticals",
    "murad", "glowbiotics", "revision skincare", "elta md",
    "colorescience", "dermablend", "it cosmetics", "urban decay",
    "too faced", "benefit cosmetics", "tarte", "becca", "smashbox",
]


def is_luxury_beauty(product_name: str) -> bool:
    """Return True if this product name contains a known luxury beauty brand (10% commission)."""
    name_lower = product_name.lower()
    return any(brand in name_lower for brand in LUXURY_BEAUTY_BRANDS)


def _guess_category(name: str) -> str:
    """Guess niche from product name. Detects luxury beauty brands for accurate 10% commission."""
    n = name.lower()
    # Check luxury beauty brands first — 10% commission
    if any(brand in n for brand in LUXURY_BEAUTY_BRANDS):
        return "luxury_beauty"
    if any(w in n for w in ["nail", "makeup", "serum", "moisturizer", "cleanser", "toner", "mask", "lash", "lip", "foundation", "concealer", "blush", "skincare", "retinol", "vitamin c", "niacinamide", "spf", "sunscreen"]):
        return "beauty"
    if any(w in n for w in ["home", "decor", "candle", "vase", "throw", "blanket", "rug", "lamp", "shelf", "organizer", "pillow", "frame", "wall art"]):
        return "home_decor"
    if any(w in n for w in ["supplement", "collagen", "protein", "vitamin", "probiotic", "massage", "foam roller", "yoga", "workout", "wellness", "glow up"]):
        return "fitness"
    return "beauty"
