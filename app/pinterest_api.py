"""
Pinterest API v5 integration.
Docs: https://developers.pinterest.com/docs/api/v5/
"""
import logging
import time
import urllib.parse
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PINTEREST_API_BASE = "https://api.pinterest.com/v5"
PINTEREST_AUTH_URL = "https://www.pinterest.com/oauth/"
PINTEREST_TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"

# Category → Pinterest interest mapping for trend queries
CATEGORY_INTERESTS = {
    "home_decor": "home_decor",
    "kitchen": "food_drinks",
    "office": "education",
    "fashion": "fashion",
    "beauty": "beauty",
    "fitness": "health_fitness",
    "travel": "travel_places",
    "garden": "gardening",
    "pets": "animals",
    "tech": "science",
    "art": "art",
    "diy": "diy_crafts",
}


def _get_access_token() -> Optional[str]:
    """Get access token from config or Settings table."""
    try:
        from app.models import Setting

        stored = Setting.get("pinterest_access_token")
        if stored:
            return stored
    except Exception:
        pass

    from config import Config

    return Config.PINTEREST_ACCESS_TOKEN or None


def _headers(token: Optional[str] = None) -> dict:
    token = token or _get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _handle_rate_limit(response: requests.Response) -> bool:
    """Return True if we were rate-limited and slept, False otherwise."""
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        logger.warning(f"Pinterest API rate limited. Retrying after {retry_after}s.")
        time.sleep(retry_after)
        return True
    return False


def get_trending_keywords(region: str = "US", limit: int = 50) -> list[dict]:
    """
    Fetch trending keywords. Tries Pinterest Trends API first, falls back to
    SerpAPI Google Trends, then hardcoded evergreen keywords.
    Returns list of dicts: [{keyword, score, category, monthly_change}, ...]
    """
    token = _get_access_token()
    if token:
        result = _get_pinterest_trends(token, region, limit)
        if result:
            return result

    logger.warning("Pinterest trends API failed — using evergreen fallback.")
    return _fallback_trends()


def _get_pinterest_trends(token: str, region: str, limit: int) -> list[dict]:
    """Fetch trends from Pinterest official Trends API v5."""
    # Correct endpoint: /trends/keywords/{region}/top/{trend_type}
    url = f"{PINTEREST_API_BASE}/trends/keywords/{region}/top/growing"
    params = {"limit": min(limit, 50)}

    try:
        resp = requests.get(url, headers=_headers(token), params=params, timeout=15)

        if _handle_rate_limit(resp):
            resp = requests.get(url, headers=_headers(token), params=params, timeout=15)

        if resp.status_code == 401:
            logger.error("Pinterest token invalid or expired.")
            return []

        if resp.status_code != 200:
            logger.error(f"Pinterest trends API error {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        trends = []
        for item in data.get("trends", []):
            kw = item.get("keyword") or item.get("normalized_keyword", "")
            if not kw:
                continue
            ts = item.get("time_series", [])
            # pct_growth_mom from time series if available
            monthly = item.get("pct_growth_mom", item.get("growth_rate", 0))
            trends.append({
                "keyword": kw,
                "score": float(monthly or 0),
                "category": _guess_category(kw),
                "monthly_change": monthly,
                "weekly_change": item.get("pct_growth_wow", 0),
                "source": "pinterest",
            })
        logger.info(f"Fetched {len(trends)} trends from Pinterest API.")
        return trends

    except requests.RequestException as e:
        logger.error(f"Pinterest trends request failed: {e}")
        return []


def _is_brand_relevant(keyword: str) -> bool:
    """Check if a keyword is relevant to our brand (home, beauty, fashion, lifestyle)."""
    kw = keyword.lower()
    brand_signals = [
        "amazon", "find", "haul", "aesthetic", "cozy", "decor", "home",
        "beauty", "skincare", "makeup", "hair", "nail", "fashion", "outfit",
        "style", "kitchen", "organiz", "desk", "room", "spring", "summer",
        "fall", "winter", "gift", "under $", "affordable", "budget", "diy",
        "trending", "must have", "favorite", "weekly", "routine",
    ]
    return any(s in kw for s in brand_signals)


def _guess_category(keyword: str) -> str:
    """Heuristic to assign a category to a trending keyword."""
    kw = keyword.lower()
    mapping = [
        (["home", "decor", "room", "interior", "cozy", "aesthetic"], "home_decor"),
        (["kitchen", "cook", "recipe", "food", "coffee", "bake"], "kitchen"),
        (["office", "desk", "work", "study", "organize"], "office"),
        (["fashion", "outfit", "style", "clothing", "wear", "dress"], "fashion"),
        (["beauty", "skincare", "makeup", "hair", "nail"], "beauty"),
        (["fitness", "workout", "gym", "yoga", "health", "wellness", "supplement", "collagen", "vitamin", "glow", "spf", "sunscreen", "tanning", "self care", "selfcare"], "fitness"),
        (["travel", "vacation", "trip", "adventure", "explore"], "travel"),
        (["garden", "plant", "outdoor", "nature", "flower"], "garden"),
        (["pet", "dog", "cat", "animal"], "pets"),
        (["tech", "gadget", "digital", "app"], "tech"),
        (["art", "paint", "draw", "creative", "craft", "diy"], "art"),
    ]
    for keywords, category in mapping:
        if any(k in kw for k in keywords):
            return category
    return "general"


def _fallback_trends() -> list[dict]:
    """Return evergreen fallback keywords when API is unavailable."""
    return [
        {"keyword": "cozy home aesthetic", "score": 0.9, "category": "home_decor"},
        {"keyword": "minimalist living room", "score": 0.85, "category": "home_decor"},
        {"keyword": "coffee morning routine", "score": 0.8, "category": "kitchen"},
        {"keyword": "work from home setup", "score": 0.75, "category": "office"},
        {"keyword": "self care sunday", "score": 0.7, "category": "beauty"},
        {"keyword": "healthy meal prep", "score": 0.7, "category": "kitchen"},
        {"keyword": "spring home refresh", "score": 0.65, "category": "home_decor"},
        {"keyword": "desk organization ideas", "score": 0.65, "category": "office"},
        {"keyword": "aesthetic bedroom ideas", "score": 0.6, "category": "home_decor"},
        {"keyword": "gift ideas for her", "score": 0.6, "category": "general"},
        {"keyword": "amazon must haves 2025", "score": 0.55, "category": "general"},
        {"keyword": "home office decor", "score": 0.55, "category": "office"},
    ]


def post_pin(
    title: str,
    description: str,
    image_url: str,
    link: str,
    board_id: Optional[str] = None,
    alt_text: Optional[str] = None,
    publish_date=None,
) -> dict:
    """
    Post (or schedule) a pin to Pinterest directly via API v5.
    publish_date: datetime (UTC) to schedule the pin — None means post immediately.
    Returns the created pin data dict or raises on failure.
    """
    from config import Config

    token = _get_access_token()
    if not token:
        raise ValueError("No Pinterest access token configured.")

    board_id = board_id or Config.PINTEREST_BOARD_ID
    if not board_id:
        raise ValueError("No Pinterest board ID configured.")

    url = f"{PINTEREST_API_BASE}/pins"
    payload = {
        "title": title[:100],
        "description": description[:500],
        "link": link,
        "board_id": board_id,
        "media_source": {
            "source_type": "image_url",
            "url": image_url,
        },
    }
    if alt_text:
        payload["alt_text"] = alt_text[:500]
    if publish_date:
        # Pinterest expects ISO 8601 UTC string e.g. "2026-04-25T00:00:00Z"
        if hasattr(publish_date, "strftime"):
            payload["publish_date"] = publish_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            payload["publish_date"] = str(publish_date)

    try:
        resp = requests.post(url, headers=_headers(token), json=payload, timeout=30)

        if _handle_rate_limit(resp):
            resp = requests.post(url, headers=_headers(token), json=payload, timeout=30)

        if resp.status_code not in (200, 201):
            logger.error(f"Pinterest post_pin error {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()

        data = resp.json()
        logger.info(f"Pin posted successfully: {data.get('id')}")
        return data

    except requests.RequestException as e:
        logger.error(f"Pinterest post_pin request failed: {e}")
        raise


def get_boards() -> list[dict]:
    """List the authenticated user's boards."""
    token = _get_access_token()
    if not token:
        logger.warning("No Pinterest token for get_boards.")
        return []

    url = f"{PINTEREST_API_BASE}/boards"
    try:
        resp = requests.get(url, headers=_headers(token), params={"page_size": 25}, timeout=15)

        if _handle_rate_limit(resp):
            resp = requests.get(url, headers=_headers(token), params={"page_size": 25}, timeout=15)

        if resp.status_code != 200:
            logger.error(f"Pinterest get_boards error {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        boards = []
        for board in data.get("items", []):
            boards.append(
                {
                    "id": board.get("id"),
                    "name": board.get("name"),
                    "url": board.get("url"),
                    "pin_count": board.get("pin_count", 0),
                }
            )
        return boards

    except requests.RequestException as e:
        logger.error(f"Pinterest get_boards request failed: {e}")
        return []


def get_access_token_url(redirect_uri: str, state: str = "state") -> str:
    """Generate the Pinterest OAuth authorization URL."""
    from config import Config

    params = {
        "client_id": Config.PINTEREST_APP_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "boards:read,boards:write,pins:read,pins:write,user_accounts:read",
        "state": state,
    }
    return f"{PINTEREST_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """
    Exchange an OAuth authorization code for an access token.
    Returns token data dict with 'access_token', 'refresh_token', etc.
    """
    import base64

    from config import Config

    credentials = f"{Config.PINTEREST_APP_ID}:{Config.PINTEREST_APP_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        resp = requests.post(PINTEREST_TOKEN_URL, headers=headers, data=payload, timeout=15)

        if resp.status_code != 200:
            logger.error(f"Pinterest token exchange error {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()

        data = resp.json()
        logger.info("Pinterest access token obtained successfully.")
        return data

    except requests.RequestException as e:
        logger.error(f"Pinterest token exchange request failed: {e}")
        raise


def get_user_info() -> dict:
    """Fetch the authenticated Pinterest user's info."""
    token = _get_access_token()
    if not token:
        return {}

    try:
        resp = requests.get(
            f"{PINTEREST_API_BASE}/user_account",
            headers=_headers(token),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return {}
    except requests.RequestException:
        return {}
