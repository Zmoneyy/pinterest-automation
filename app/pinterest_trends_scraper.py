"""
Pinterest Trends scraper using Pinterest's internal session-authenticated API.

How it works:
  - trends.pinterest.com loads data via internal ApiResource endpoints
  - These require a logged-in Pinterest session cookie (_pinterest_sess + csrftoken)
  - User pastes their cookie from DevTools → stored in Settings table
  - Cookie typically lasts 1-4 weeks before needing renewal

Data returned:
  - Editorial trend collections (e.g. "Cultivating whimsy") with keywords
  - Each trend has a title, body description, keywords, and category interests

Setup:
  1. Log into pinterest.com in Chrome
  2. Open DevTools → Network → Fetch/XHR → reload trends.pinterest.com
  3. Click any ApiResource request → Headers → copy cookie header value
  4. Paste into Setup page under "Pinterest Session Cookie"
"""

import json
import logging
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PINTEREST_TRENDS_URL = "https://trends.pinterest.com/resource/ApiResource/get/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://trends.pinterest.com/",
    "x-pinterest-appstate": "active",
    "x-pinterest-pws-handler": "trends/index.js",
}


def _get_session_cookies() -> Optional[dict]:
    """Load Pinterest session cookie from Settings table."""
    try:
        from app.models import Setting
        raw = Setting.get("pinterest_session_cookie")
        if not raw:
            return None
        return _parse_cookie_string(raw)
    except Exception as e:
        logger.error(f"Failed to load Pinterest session cookie: {e}")
        return None


def _parse_cookie_string(cookie_str: str) -> dict:
    """Parse a raw cookie header string into a dict."""
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            cookies[k.strip()] = v.strip()
    return cookies


def fetch_pinterest_trends(region: str = "US") -> list[dict]:
    """
    Fetch trending content from Pinterest's internal API.
    Returns list of dicts: [{keyword, title, description, category, score}, ...]
    Falls back to empty list if cookie is missing or expired.
    """
    cookies = _get_session_cookies()
    if not cookies:
        logger.warning("No Pinterest session cookie stored — skipping trends scrape.")
        return []

    # 1. Fetch editorial trend collections (curated trend stories)
    editorial = _fetch_editorial_trends(cookies, region)

    # 2. Flatten into keyword list with context
    trends = _flatten_editorial_to_keywords(editorial)

    if trends:
        logger.info(f"Fetched {len(trends)} Pinterest trend keywords via session scrape.")
        _cache_trends(trends)
    else:
        logger.warning("Pinterest trends scrape returned no data — cookie may be expired.")

    return trends


def _fetch_editorial_trends(cookies: dict, region: str) -> list[dict]:
    """Hit the editorial content endpoint and return raw trend items."""
    params = {
        "source_url": "/",
        "data": json.dumps({
            "options": {
                "url": f"/ads/v4/trends/editorial/content/{region}",
                "data": {}
            },
            "context": {}
        }),
        "_": str(int(datetime.now().timestamp() * 1000)),
    }

    try:
        resp = requests.get(
            PINTEREST_TRENDS_URL,
            headers=HEADERS,
            cookies=cookies,
            params=params,
            timeout=15,
        )

        if resp.status_code == 403:
            logger.error("Pinterest session cookie rejected (403) — needs renewal.")
            return []

        if resp.status_code != 200:
            logger.error(f"Pinterest trends scrape error {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        return data.get("resource_response", {}).get("data", [])

    except requests.RequestException as e:
        logger.error(f"Pinterest trends request failed: {e}")
        return []


def _flatten_editorial_to_keywords(editorial_items: list) -> list[dict]:
    """
    Convert editorial trend stories into keyword dicts for the app.
    Each story has a title + list of keywords + body description.
    """
    trends = []
    for i, item in enumerate(editorial_items):
        title = item.get("title", "")
        body = item.get("body", "")
        keywords_by_region = item.get("keywords", {})
        us_keywords = keywords_by_region.get("US", [])
        start_date = item.get("start_date", "")
        is_published = item.get("is_published", False)

        if not is_published or not us_keywords:
            continue

        # Score based on position (first = most prominent on Pinterest)
        base_score = max(100 - (i * 10), 10)

        for j, kw in enumerate(us_keywords):
            trends.append({
                "keyword": kw,
                "title": title,           # trend collection name e.g. "Cultivating whimsy"
                "description": body,      # Pinterest's editorial description (great for Claude)
                "score": base_score - j,
                "monthly_change": base_score,
                "weekly_change": 0,
                "category": _guess_category_from_keywords(us_keywords, title),
                "source": "pinterest_trends",
                "start_date": start_date,
            })

    return trends


def _guess_category_from_keywords(keywords: list, title: str) -> str:
    """Guess product category from trend keywords and title."""
    text = " ".join(keywords + [title]).lower()
    mapping = [
        (["nail", "makeup", "beauty", "skincare", "hair", "lash"], "beauty"),
        (["home", "decor", "room", "bedroom", "living", "cozy", "aesthetic", "whimsy"], "home_decor"),
        (["outfit", "fashion", "style", "clothing", "dress", "wear"], "fashion"),
        (["kitchen", "cook", "food", "coffee", "bake"], "kitchen"),
        (["office", "desk", "work", "study"], "office"),
        (["fitness", "gym", "yoga", "wellness", "health", "supplement", "collagen", "vitamin", "glow", "spf", "sunscreen", "tanning", "self care", "selfcare"], "fitness"),
        (["garden", "plant", "flower", "outdoor"], "garden"),
        (["pet", "dog", "cat"], "pets"),
        (["travel", "vacation", "trip"], "travel"),
        (["diy", "craft", "art", "paint"], "art"),
    ]
    for signals, category in mapping:
        if any(s in text for s in signals):
            return category
    return "general"


def _cache_trends(trends: list):
    """Cache fetched trends in the TrendCache table."""
    try:
        from app import db
        from app.models import TrendCache

        TrendCache.query.delete()
        for t in trends:
            db.session.add(TrendCache(
                keyword=t["keyword"],
                category=t.get("category", "general"),
                score=t.get("score", 0),
            ))
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to cache Pinterest trends: {e}")
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass


def get_trend_descriptions_for_claude() -> list[dict]:
    """
    Return enriched trend data for Claude to use in copywriting.
    Includes the editorial description (Pinterest's own trend narrative).
    """
    try:
        from app.models import Setting
        raw = Setting.get("pinterest_session_cookie")
        if raw:
            return fetch_pinterest_trends()
    except Exception:
        pass
    return []


def fetch_shopping_trends(region: str = "US") -> list[dict]:
    """
    Fetch Pinterest Shopping Trends — product categories ranked by outbound clicks.
    Returns list of dicts: [{rank, category_name, mom_growth, volume, ...}, ...]
    """
    cookies = _get_session_cookies()
    if not cookies:
        logger.warning("No Pinterest session cookie — skipping shopping trends fetch.")
        return []

    params = {
        "source_url": f"/shopping/?country={region}",
        "data": json.dumps({
            "options": {"url": "/ads/v4/trends/shopping/product_categories", "data": {}},
            "context": {}
        }),
        "_": str(int(datetime.now().timestamp() * 1000)),
    }

    try:
        resp = requests.get(
            PINTEREST_TRENDS_URL,
            headers=HEADERS,
            cookies=cookies,
            params=params,
            timeout=15,
        )

        if resp.status_code == 403:
            logger.error("Pinterest session cookie rejected (403) fetching shopping trends.")
            return []

        if resp.status_code != 200:
            logger.error(f"Shopping trends error {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        items = data.get("resource_response", {}).get("data", [])
        logger.info(f"Fetched {len(items)} shopping trend categories from Pinterest.")
        return items

    except requests.RequestException as e:
        logger.error(f"Shopping trends request failed: {e}")
        return []


def fetch_keyword_growth(keyword: str, region: str = "US") -> dict:
    """
    Fetch yearly and monthly growth % for a specific keyword from Pinterest Trends.
    This is the data shown on trends.pinterest.com when you search a keyword —
    the yearly_change and monthly_change percentages the masterclass says to check.

    Returns: {"yearly_change": float|None, "monthly_change": float|None}
    """
    cookies = _get_session_cookies()
    if not cookies:
        return {"yearly_change": None, "monthly_change": None}

    params = {
        "source_url": f"/trends/keyword/{keyword.replace(' ', '-')}",
        "data": json.dumps({
            "options": {
                "url": "/ads/v4/trends/keywords/search",
                "data": {
                    "keyword": keyword,
                    "region": region,
                    "trend_type": "monthly",
                }
            },
            "context": {}
        }),
        "_": str(int(datetime.now().timestamp() * 1000)),
    }

    try:
        resp = requests.get(
            PINTEREST_TRENDS_URL,
            headers=HEADERS,
            cookies=cookies,
            params=params,
            timeout=10,
        )
        if resp.status_code != 200:
            return {"yearly_change": None, "monthly_change": None}

        data = resp.json()
        trend_data = data.get("resource_response", {}).get("data", {})

        # Pinterest returns trend timeseries — extract growth metrics
        monthly_change = trend_data.get("mom_growth")   # month-over-month %
        yearly_change  = trend_data.get("yoy_growth")   # year-over-year %

        # Some endpoints return as a decimal (0.85 = +85%), normalise to int %
        if monthly_change is not None and abs(monthly_change) < 10:
            monthly_change = round(monthly_change * 100)
        if yearly_change is not None and abs(yearly_change) < 10:
            yearly_change = round(yearly_change * 100)

        return {
            "yearly_change":  yearly_change,
            "monthly_change": monthly_change,
        }

    except Exception as e:
        logger.debug(f"Keyword growth fetch failed for '{keyword}': {e}")
        return {"yearly_change": None, "monthly_change": None}


def enrich_keywords_with_growth(keywords: list[dict], max_keywords: int = 20) -> list[dict]:
    """
    For the top keywords, fetch their real yearly/monthly growth from Pinterest Trends
    and update the keyword dicts in-place. Skips keywords that already have growth data.
    Only fetches up to max_keywords to avoid rate limiting.
    """
    fetched = 0
    for kw in keywords:
        if fetched >= max_keywords:
            break
        # Skip if we already have real growth data
        if kw.get("yearly_change") is not None:
            continue
        growth = fetch_keyword_growth(kw["keyword"])
        kw["yearly_change"]  = growth["yearly_change"]
        kw["monthly_change"] = growth["monthly_change"]
        fetched += 1

    if fetched:
        logger.info(f"Enriched {fetched} keywords with Pinterest growth data.")
    return keywords


def check_cookie_status() -> dict:
    """Check if the stored Pinterest cookie is valid and working."""
    cookies = _get_session_cookies()
    if not cookies:
        return {"status": "missing", "message": "No cookie stored"}

    params = {
        "source_url": "/",
        "data": json.dumps({
            "options": {"url": "/ads/v4/trends/editorial/content/US", "data": {}},
            "context": {}
        }),
        "_": str(int(datetime.now().timestamp() * 1000)),
    }

    try:
        resp = requests.get(
            PINTEREST_TRENDS_URL,
            headers=HEADERS,
            cookies=cookies,
            params=params,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("resource_response", {}).get("data", [])
            return {
                "status": "valid",
                "message": f"Cookie working — {len(items)} trend collections found",
                "trend_count": len(items),
            }
        elif resp.status_code == 403:
            return {"status": "expired", "message": "Cookie expired — please refresh it"}
        else:
            return {"status": "error", "message": f"Unexpected status {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
