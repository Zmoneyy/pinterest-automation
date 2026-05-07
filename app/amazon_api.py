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
    Search Amazon for products matching a keyword.
    Returns list of {name, asin, amazon_url, image_url, price, category}.
    """
    from config import Config

    associate_tag = Config.AMAZON_ASSOCIATE_TAG or "auragirlcreat-20"

    try:
        results = _scrape_amazon_search(keyword, max_results=max_results)
        # Tag each with affiliate URL and category
        for r in results:
            if r.get("asin"):
                r["amazon_url"] = _build_affiliate_url(r["asin"], associate_tag)
            r["category"] = category or _guess_category(r.get("name", ""))
        logger.info(f"Amazon search '{keyword}': {len(results)} products found")
        return results
    except Exception as e:
        logger.error(f"Amazon search failed for '{keyword}': {e}")
        return []


def _scrape_amazon_search(keyword: str, max_results: int = 5) -> list[dict]:
    """
    Find Amazon products by searching Google (avoids Amazon's IP blocks on Cloud Run).
    Extracts ASIN from result URLs, then fetches each product page for details.
    """
    from bs4 import BeautifulSoup

    # Search DuckDuckGo HTML (doesn't block Cloud Run IPs unlike Google/Amazon)
    ddg_url = "https://html.duckduckgo.com/html/"
    params = {"q": f"site:amazon.com/dp {keyword}"}
    ddg_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://duckduckgo.com/",
    }

    time.sleep(random.uniform(1.0, 2.5))

    try:
        resp = requests.post(ddg_url, data=params, headers=ddg_headers, timeout=20)
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed for '{keyword}': {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract ASINs from DDG result URLs
    asins_seen = set()
    asins = []
    for a in soup.select("a.result__url, a.result__a, a[href]"):
        href = a.get("href", "")
        m = re.search(r"amazon\.com/(?:[^/]+/)?dp/([A-Z0-9]{10})", href)
        if m:
            asin = m.group(1)
            if asin not in asins_seen:
                asins_seen.add(asin)
                asins.append(asin)
        if len(asins) >= max_results * 3:
            break

    if not asins:
        logger.warning(f"No Amazon ASINs found via DuckDuckGo for '{keyword}'")
        return []

    # Fetch each product page for name, price, image
    results = []
    for asin in asins:
        if len(results) >= max_results:
            break
        try:
            product = _fetch_amazon_product(asin)
            if product:
                results.append(product)
            time.sleep(random.uniform(1.0, 2.0))
        except Exception as e:
            logger.debug(f"Failed to fetch ASIN {asin}: {e}")
            continue

    return results[:max_results]


def _fetch_amazon_product(asin: str) -> Optional[dict]:
    """Fetch a single Amazon product page and extract name, price, image."""
    from bs4 import BeautifulSoup

    url = f"https://www.amazon.com/dp/{asin}"
    try:
        resp = requests.get(url, headers=AMAZON_HEADERS, timeout=20)
        if not resp.ok:
            return None
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Name
    name_tag = soup.select_one("#productTitle") or soup.select_one("#title")
    name = name_tag.get_text(strip=True) if name_tag else ""
    if not name or len(name) < 5:
        return None

    # Price — try multiple selectors
    price = ""
    for sel in [
        ".a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#price_inside_buybox",
        ".a-price-whole",
    ]:
        p = soup.select_one(sel)
        if p:
            raw = p.get_text(strip=True).replace("$", "").replace(",", "").strip()
            try:
                price = str(round(float(re.search(r"[\d.]+", raw).group()), 2))
                break
            except Exception:
                continue

    # Min price floor: $30 (strategy is 10% luxury beauty, min $3/sale)
    try:
        if not price or float(price) < 30:
            return None
    except Exception:
        return None

    # Image
    image_url = ""
    for sel in ["#landingImage", "#imgBlkFront", "#main-image"]:
        img = soup.select_one(sel)
        if img:
            image_url = img.get("src") or img.get("data-src") or ""
            if image_url:
                break

    return {
        "name": name[:200],
        "asin": asin,
        "amazon_url": f"https://www.amazon.com/dp/{asin}",
        "image_url": image_url,
        "price": price,
        "rating": 0.0,
        "reviews": 0,
    }


# Luxury beauty searches that reliably return 10% commission products
LUXURY_BEAUTY_SEARCHES = [
    ("charlotte tilbury amazon", "Charlotte Tilbury"),
    ("tatcha skincare amazon", "Tatcha"),
    ("drunk elephant serum amazon", "Drunk Elephant"),
    ("rare beauty selena gomez amazon", "Rare Beauty"),
    ("merit beauty amazon", "Merit"),
    ("nars cosmetics amazon", "NARS"),
    ("dyson airwrap amazon", "Dyson"),
    ("sunday riley amazon", "Sunday Riley"),
    ("peter thomas roth amazon", "Peter Thomas Roth"),
    ("ilia beauty amazon", "ILIA"),
    ("kate somerville amazon", "Kate Somerville"),
    ("pat mcgrath amazon", "Pat McGrath"),
    ("shiseido amazon", "Shiseido"),
    ("estee lauder amazon", "Estée Lauder"),
    ("lancôme amazon", "Lancôme"),
    ("ysl beauty amazon", "YSL Beauty"),
    ("tom ford beauty amazon", "Tom Ford Beauty"),
    ("la mer moisturizer amazon", "La Mer"),
    ("sk-ii facial treatment amazon", "SK-II"),
    ("westman atelier amazon", "Westman Atelier"),
]


def discover_products_for_trends(trends: list[dict], per_trend: int = 3) -> list[dict]:
    """
    Search Amazon for products. ALWAYS leads with luxury beauty (10% commission)
    searches first, then trend-matched products.
    """
    all_products = []
    seen_asins = set()

    def _add_products(products, trend_keyword, source_category):
        for p in products:
            asin = p.get("asin", "")
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
                p["trend_keyword"]   = trend_keyword
                p["source_category"] = source_category
                all_products.append(p)

    # ── STEP 1: Always search luxury beauty brands first (10% commission) ──
    # Shuffle so we don't always get the same brands
    luxury_searches = list(LUXURY_BEAUTY_SEARCHES)
    random.shuffle(luxury_searches)
    for query, brand in luxury_searches[:8]:   # top 8 luxury brands per run
        products = search_products(query, category="luxury_beauty", max_results=3)
        _add_products(products, brand, "Luxury Beauty (10%)")
        time.sleep(random.uniform(1.5, 3))

    # ── STEP 2: Trend-matched searches from TrendEntry categories ──
    for trend in trends[:15]:
        keyword         = trend.get("keyword", "")
        niche           = trend.get("niche") or trend.get("category", "beauty")
        source_category = trend.get("source_category", "")
        if not keyword:
            continue
        products = search_products(keyword, category=niche, max_results=per_trend)
        _add_products(products, keyword, source_category)
        time.sleep(random.uniform(2, 4))

    return all_products


def discover_evergreen_products(per_query: int = 3) -> list[dict]:
    """Search for evergreen high-commission beauty products."""
    evergreen_queries = [
        "best skincare serum amazon",
        "vitamin c serum face amazon",
        "retinol cream amazon best seller",
        "hyaluronic acid moisturizer amazon",
        "niacinamide serum amazon",
    ]
    all_products = []
    seen_asins = set()

    for query in evergreen_queries[:3]:
        products = search_products(query, category="beauty", max_results=per_query)
        for p in products:
            asin = p.get("asin", "")
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
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
]

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
