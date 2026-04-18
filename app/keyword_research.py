"""
Keyword Research Engine for Pinterest affiliate content strategy.

Mimics what a Pinterest expert does manually:
1. Search each niche in Pinterest trends → pull top keywords by growth %
2. Pull Pinterest search autocomplete suggestions (what people actually type)
3. Layer in seasonal keywords for the target season
4. Rank everything by monthly + yearly growth
5. Feed ranked keywords into pin generation as the starting point

Result: Every pin title, description, and hashtag starts from a real
keyword people are searching on Pinterest right now.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# The 3 core niches and their Pinterest search seed terms
NICHE_SEEDS = {
    "beauty": [
        "nails", "nail ideas", "skincare", "makeup", "hair",
        "press on nails", "lip gloss", "lash", "glow skin",
    ],
    "home_decor": [
        "home decor", "room decor", "aesthetic room", "cozy home",
        "candles", "wall art", "bedroom ideas", "home aesthetic",
    ],
    "fitness": [
        "self care", "wellness", "glow up", "supplements",
        "sunscreen", "tanning", "healthy routine", "beauty supplements",
    ],
}

SERPAPI_PINTEREST_URL = "https://serpapi.com/search"
PINTEREST_TRENDS_URL = "https://trends.pinterest.com/resource/ApiResource/get/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://trends.pinterest.com/",
    "x-pinterest-appstate": "active",
}


def _rank_score(kw: dict) -> float:
    """
    Pinterest masterclass ranking logic:
    - Yearly change positive = good. With a "plus" (>=100% growth) = even better.
    - Monthly change positive = additional signal.
    - If yearly/monthly are unknown (None), use base score only — don't penalise.
    - If yearly change is negative → already filtered out before this runs.
    """
    yearly  = kw.get("yearly_change")
    monthly = kw.get("monthly_change")
    base    = float(kw.get("score", 0))

    score = base

    # Yearly change: positive is required, "plus" (very high growth) is bonus
    if yearly is not None and yearly > 0:
        score += min(yearly * 0.4, 40)   # growth bonus, capped at +40
        if yearly >= 100:                 # "plus" indicator — strongly trending
            score += 25

    # Monthly change: positive adds confidence
    if monthly is not None and monthly > 0:
        score += min(monthly * 0.2, 20)  # monthly bonus, capped at +20

    return score


def run_keyword_research() -> list[dict]:
    """
    Main entry point. Runs full keyword research across all 3 niches.
    Returns ranked list of keyword dicts ready to feed into pin generation.
    """
    from app.seasonal import get_seasonal_keywords, get_current_season

    season_info = get_current_season()
    logger.info(f"Running keyword research (target season: {season_info['season']})")

    all_keywords = []

    # 1. Pinterest autocomplete keywords via SerpAPI
    autocomplete_keywords = _get_pinterest_autocomplete_keywords()
    all_keywords.extend(autocomplete_keywords)

    # 2. Pinterest trending keywords via session cookie
    trend_keywords = _get_pinterest_trend_keywords()
    all_keywords.extend(trend_keywords)

    # 3. Seasonal keywords
    for niche in ["beauty", "home_decor", "fitness"]:
        seasonal = get_seasonal_keywords(niche)
        for kw in seasonal:
            all_keywords.append({
                "keyword": kw,
                "niche": niche,
                "score": 80,  # high priority — seasonal
                "monthly_change": None,
                "yearly_change": None,
                "source": "seasonal",
            })

    # Deduplicate by keyword text
    seen = set()
    unique = []
    for kw in all_keywords:
        key = kw["keyword"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(kw)

    # Enrich top candidates with real Pinterest growth data (yearly + monthly %)
    # This is the data shown on trends.pinterest.com — exactly what the masterclass says to check
    try:
        from app.pinterest_trends_scraper import enrich_keywords_with_growth
        # Pre-sort by base score so we enrich the most promising keywords first
        unique.sort(key=lambda x: x.get("score", 0), reverse=True)
        unique = enrich_keywords_with_growth(unique, max_keywords=25)
    except Exception as e:
        logger.warning(f"Growth enrichment skipped: {e}")

    # Filter out keywords with known negative yearly change (declining = skip)
    unique = [kw for kw in unique if kw.get("yearly_change") is None or kw["yearly_change"] >= 0]

    # Rank using Pinterest masterclass priority:
    #   1. Yearly change positive first (required signal)
    #   2. Yearly change "plus" = strongly growing (>=100%) → extra weight
    #   3. Monthly change positive → additional boost
    #   4. Base score (source quality / position) as tiebreaker
    ranked = sorted(unique, key=_rank_score, reverse=True)

    logger.info(f"Keyword research complete: {len(ranked)} unique keywords found.")

    # Cache to DB
    _cache_keywords(ranked)

    return ranked


def _get_pinterest_autocomplete_keywords() -> list[dict]:
    """
    Use SerpAPI Pinterest engine to get autocomplete suggestions
    for each niche seed term — these are exactly what people type
    in the Pinterest search bar.
    """
    try:
        from config import Config
        if not Config.SERP_API_KEY:
            return []

        results = []
        for niche, seeds in NICHE_SEEDS.items():
            for seed in seeds[:3]:  # top 3 seeds per niche to save API calls
                try:
                    resp = requests.get(
                        SERPAPI_PINTEREST_URL,
                        params={
                            "engine": "pinterest",
                            "q": seed,
                            "api_key": Config.SERP_API_KEY,
                        },
                        timeout=15,
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()

                    # Extract pins and their titles as keyword signals
                    pins = data.get("pins", [])
                    for pin in pins[:10]:
                        title = pin.get("title", "") or pin.get("description", "")
                        if title and len(title) > 5:
                            results.append({
                                "keyword": title[:100].strip(),
                                "niche": niche,
                                "score": 60,
                                "monthly_change": None,
                                "yearly_change": None,
                                "source": "pinterest_autocomplete",
                                "seed": seed,
                            })

                    # Also grab related terms if available
                    related = data.get("related_terms", [])
                    for term in related[:5]:
                        if isinstance(term, str) and term:
                            results.append({
                                "keyword": term.strip(),
                                "niche": niche,
                                "score": 70,  # higher — directly related
                                "monthly_change": None,
                                "yearly_change": None,
                                "source": "pinterest_related",
                                "seed": seed,
                            })

                except Exception as e:
                    logger.error(f"Pinterest autocomplete failed for '{seed}': {e}")
                    continue

        logger.info(f"Pinterest autocomplete: {len(results)} keywords from SerpAPI.")
        return results

    except Exception as e:
        logger.error(f"Pinterest autocomplete fetch failed: {e}")
        return []


def _get_pinterest_trend_keywords() -> list[dict]:
    """
    Pull editorial trending keywords from Pinterest via session cookie.
    These are Pinterest's own curated trend collections with real search data.
    """
    try:
        from app.pinterest_trends_scraper import _get_session_cookies, _fetch_editorial_trends

        cookies = _get_session_cookies()
        if not cookies:
            return []

        editorial = _fetch_editorial_trends(cookies, "US")
        results = []

        for i, item in enumerate(editorial):
            title = item.get("title", "")
            body = item.get("body", "")
            us_keywords = item.get("keywords", {}).get("US", [])
            is_published = item.get("is_published", False)

            if not is_published:
                continue

            # Score based on position (first = most trending)
            base_score = max(100 - (i * 8), 20)

            for j, kw in enumerate(us_keywords):
                niche = _guess_niche(kw + " " + title)
                results.append({
                    "keyword": kw,
                    "niche": niche,
                    "score": base_score - j,
                    "monthly_change": base_score,
                    "yearly_change": None,
                    "trend_title": title,
                    "trend_description": body,
                    "source": "pinterest_trends",
                })

        logger.info(f"Pinterest trends: {len(results)} keywords from session cookie.")
        return results

    except Exception as e:
        logger.error(f"Pinterest trend keywords failed: {e}")
        return []


def _guess_niche(text: str) -> str:
    """Guess which of the 3 niches a keyword belongs to."""
    t = text.lower()
    if any(w in t for w in ["nail", "makeup", "beauty", "skincare", "hair", "lash", "lip", "glow skin", "foundation", "mascara", "blush"]):
        return "beauty"
    if any(w in t for w in ["home", "decor", "room", "bedroom", "candle", "cozy", "aesthetic", "wall art", "pillow", "vase", "mirror"]):
        return "home_decor"
    if any(w in t for w in ["wellness", "supplement", "collagen", "vitamin", "self care", "sunscreen", "tanning", "spf", "glow up", "health", "fitness"]):
        return "fitness"
    return "beauty"  # default to beauty


def _cache_keywords(keywords: list):
    """Cache keyword research results in TrendCache table."""
    try:
        from app import db
        from app.models import TrendCache

        TrendCache.query.delete()
        for kw in keywords[:100]:  # store top 100
            db.session.add(TrendCache(
                keyword=kw["keyword"],
                category=kw.get("niche", "beauty"),
                score=float(kw.get("score", 0)),
            ))
        db.session.commit()
        logger.info(f"Cached {min(len(keywords), 100)} keywords to TrendCache.")
    except Exception as e:
        logger.error(f"Keyword cache failed: {e}")
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass


def get_top_keywords_for_niche(niche: str, limit: int = 10) -> list[str]:
    """
    Return top keyword strings for a specific niche from the cache.
    Used by pin generation to pick the best keyword to build a pin around.
    """
    try:
        from app.models import TrendCache
        rows = (
            TrendCache.query
            .filter_by(category=niche)
            .order_by(TrendCache.score.desc())
            .limit(limit)
            .all()
        )
        return [r.keyword for r in rows]
    except Exception as e:
        logger.error(f"get_top_keywords_for_niche failed: {e}")
        return []


def get_keyword_driven_title_prompt(keyword: str, niche: str) -> str:
    """
    Returns a title format hint for Claude based on the keyword.
    Follows Pinterest SEO best practice: keyword-first, specific, clickable.
    """
    templates = {
        "beauty": [
            f"The {keyword} products everyone is buying on Amazon right now",
            f"Best {keyword} finds on Amazon under $20",
            f"These {keyword} products are going viral for a reason",
            f"{keyword} that actually work — found on Amazon",
        ],
        "home_decor": [
            f"The {keyword} pieces making every room look expensive",
            f"Best {keyword} finds on Amazon right now",
            f"Your home needs these {keyword} finds from Amazon",
            f"{keyword} that look way more expensive than they are",
        ],
        "fitness": [
            f"The {keyword} products that are worth every penny",
            f"Best {keyword} finds on Amazon for your routine",
            f"These {keyword} products actually changed my routine",
            f"{keyword} that every girl needs in her routine",
        ],
    }
    import random
    options = templates.get(niche, templates["beauty"])
    return random.choice(options)
