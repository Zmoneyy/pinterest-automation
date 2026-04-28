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
    return f"https://www.amazon.com/dp/{asin}?tag={associate_tag}"


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
    Scrape Amazon search results page for a keyword.
    Extracts product cards: name, ASIN, price, image URL.
    """
    from bs4 import BeautifulSoup

    search_url = "https://www.amazon.com/s"
    params = {
        "k": keyword,
        "i": "aps",
        "ref": "nb_sb_noss",
    }

    # Polite delay to avoid rate limiting
    time.sleep(random.uniform(1.5, 3.0))

    resp = requests.get(search_url, params=params, headers=AMAZON_HEADERS, timeout=20)
    if not resp.ok:
        logger.warning(f"Amazon search returned {resp.status_code} for '{keyword}'")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    # Amazon search result cards
    cards = soup.select('[data-component-type="s-search-result"]')

    for card in cards:
        if len(results) >= max_results:
            break
        try:
            # ASIN
            asin = card.get("data-asin", "").strip()
            if not asin or len(asin) != 10:
                continue

            # Product name
            name_tag = card.select_one("h2 a span") or card.select_one(".a-size-medium") or card.select_one(".a-size-base-plus")
            name = name_tag.get_text(strip=True) if name_tag else ""
            if not name or len(name) < 5:
                continue

            # Skip sponsored results if name looks generic
            if any(w in name.lower() for w in ["sponsored", "advertisement"]):
                continue

            # Price
            price = ""
            price_tag = card.select_one(".a-price .a-offscreen") or card.select_one(".a-price-whole")
            if price_tag:
                price = price_tag.get_text(strip=True).replace("$", "").strip()
                # Clean "14.9914.99" doubled prices
                if price:
                    try:
                        price = str(round(float(re.search(r"[\d.]+", price).group()), 2))
                    except Exception:
                        pass

            # Only keep products $15+ — under $15 beauty commission not worth promoting
            try:
                if not price or float(price) < 15:
                    continue
            except Exception:
                continue  # skip if price unparseable

            # Product image
            image_url = ""
            img_tag = card.select_one("img.s-image") or card.select_one(".s-product-image-container img")
            if img_tag:
                image_url = img_tag.get("src", "") or img_tag.get("data-src", "")

            # Rating — prefer higher rated products
            rating = 0.0
            rating_tag = card.select_one(".a-icon-star-small .a-icon-alt") or card.select_one("[aria-label*='out of 5']")
            if rating_tag:
                try:
                    rating = float(re.search(r"[\d.]+", rating_tag.get_text() or rating_tag.get("aria-label", "0")).group())
                except Exception:
                    pass

            # Review count — skip products with very few reviews
            reviews = 0
            review_tag = card.select_one(".a-size-base.s-underline-text")
            if review_tag:
                try:
                    reviews = int(re.sub(r"[^\d]", "", review_tag.get_text()))
                except Exception:
                    pass

            # Skip products with fewer than 50 reviews (too new/unproven)
            if reviews > 0 and reviews < 50:
                continue

            results.append({
                "name": name[:200],
                "asin": asin,
                "amazon_url": f"https://www.amazon.com/dp/{asin}",
                "image_url": image_url,
                "price": price,
                "rating": rating,
                "reviews": reviews,
            })

        except Exception as e:
            logger.debug(f"Error parsing Amazon card: {e}")
            continue

    # Sort by rating × log(reviews) — proven popular products first
    import math
    results.sort(
        key=lambda r: (r.get("rating", 0) * math.log(max(r.get("reviews", 1), 1))),
        reverse=True,
    )

    return results[:max_results]


def discover_products_for_trends(trends: list[dict], per_trend: int = 3) -> list[dict]:
    """
    Given a list of trend dicts (from TrendCache), search Amazon for each
    and return product candidates.
    """
    all_products = []
    seen_asins = set()

    for trend in trends[:5]:  # limit to top 5 trends to avoid hammering Amazon
        keyword = trend.get("keyword", "")
        niche = trend.get("niche", "beauty")
        if not keyword:
            continue

        products = search_products(keyword, category=niche, max_results=per_trend)
        for p in products:
            asin = p.get("asin", "")
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
                p["trend_keyword"] = keyword
                all_products.append(p)

        time.sleep(random.uniform(2, 4))  # polite delay between searches

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


def _guess_category(name: str) -> str:
    """Guess niche from product name."""
    n = name.lower()
    if any(w in n for w in ["nail", "makeup", "serum", "moisturizer", "cleanser", "toner", "mask", "lash", "lip", "foundation", "concealer", "blush", "skincare", "retinol", "vitamin c", "niacinamide", "spf", "sunscreen"]):
        return "beauty"
    if any(w in n for w in ["home", "decor", "candle", "vase", "throw", "blanket", "rug", "lamp", "shelf", "organizer", "pillow", "frame", "wall art"]):
        return "home_decor"
    if any(w in n for w in ["supplement", "collagen", "protein", "vitamin", "probiotic", "massage", "foam roller", "yoga", "workout", "wellness", "glow up"]):
        return "fitness"
    return "beauty"
