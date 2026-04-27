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
    Pinterest's live search autocomplete endpoint — no auth needed, real-time search intent.
    """
    results = []
    results.extend(_pinterest_live_autocomplete())
    logger.info(f"Pinterest autocomplete total: {len(results)} keywords")
    return results


def _pinterest_live_autocomplete() -> list[dict]:
    """
    Hit Pinterest's public autocomplete endpoint — the same dropdown that appears
    when you type in Pinterest search. No login, no API key, completely free.
    Returns what people are actively searching RIGHT NOW.
    """
    results = []
    seen = set()

    for niche, seeds in NICHE_SEEDS.items():
        for seed in seeds:  # all seeds — endpoint is fast and free
            try:
                resp = requests.get(
                    "https://www.pinterest.com/api/v3/search/completions/",
                    params={"q": seed},
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        "Accept": "application/json",
                        "Referer": "https://www.pinterest.com/",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=8,
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                completions = (
                    data.get("data", {}).get("completions", []) or
                    data.get("completions", []) or
                    data.get("items", [])
                )

                for i, item in enumerate(completions[:10]):
                    # Response can be a string or a dict with a "query" key
                    if isinstance(item, str):
                        kw = item.strip()
                    elif isinstance(item, dict):
                        kw = (item.get("query") or item.get("display") or item.get("term") or "").strip()
                    else:
                        continue

                    if not kw or kw.lower() in seen:
                        continue
                    seen.add(kw.lower())

                    # Position 0 = most searched. Score decays by position.
                    score = 90 - (i * 5)
                    results.append({
                        "keyword": kw,
                        "niche": niche,
                        "score": score,
                        "monthly_change": None,
                        "yearly_change": None,
                        "source": "pinterest_live_autocomplete",
                        "seed": seed,
                    })

            except Exception as e:
                logger.debug(f"Live autocomplete failed for '{seed}': {e}")
                continue

    logger.info(f"Pinterest live autocomplete: {len(results)} keywords")
    return results


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
    if any(w in t for w in ["home", "decor", "room", "bedroom", "candle", "cozy", "aesthetic", "wall art", "pillow", "vase", "mirror", "kitchen", "shelf", "rug", "furniture"]):
        return "home_decor"
    if any(w in t for w in ["massage", "massager", "recovery", "muscle", "pain relief", "wellness", "supplement", "collagen", "vitamin", "self care", "sunscreen", "tanning", "spf", "glow up", "health", "fitness", "workout", "gym", "yoga", "protein", "relaxation", "stress relief"]):
        return "fitness"
    if any(w in t for w in ["nail", "makeup", "beauty", "skincare", "hair", "lash", "lip", "glow skin", "foundation", "mascara", "blush", "serum", "moisturizer", "toner"]):
        return "beauty"
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


def pick_best_keyword_for_product(product_name: str, niche: str, content_type: str = "evergreen") -> str:
    """
    Pick the best Pinterest trending keyword for a specific product.

    Strategy:
    - Pull top keywords from TrendCache for this niche
    - Score each keyword by how well it matches the product (word overlap)
    - Seasonal products get seasonal keywords, trending products get high-score keywords
    - Always prioritize buying intent over pure trend score
    - Falls back to a generated buying-intent keyword if no good match found

    Returns a single keyword string ready to use in pin title/description/hashtags.
    """
    try:
        from app.models import TrendCache

        # Pull top 20 cached keywords for this niche
        rows = (
            TrendCache.query
            .filter_by(category=niche)
            .order_by(TrendCache.score.desc())
            .limit(20)
            .all()
        )

        if rows:
            product_words = set(product_name.lower().split())

            # Score each keyword: trend score + word overlap with product name
            scored = []
            for row in rows:
                kw = row.keyword.lower()
                kw_words = set(kw.split())
                overlap = len(product_words & kw_words)
                # Weight: overlap matters more than raw trend score for relevance
                relevance = overlap * 2 + (row.score or 0) * 0.01
                scored.append((row.keyword, relevance, row.score or 0))

            scored.sort(key=lambda x: x[1], reverse=True)

            # For trending products: pick highest trend score keyword
            if content_type == "trending":
                scored.sort(key=lambda x: x[2], reverse=True)
                return scored[0][0]

            # For seasonal: prefer keywords that have seasonal terms
            if content_type == "seasonal":
                season_terms = {"summer", "winter", "fall", "spring", "holiday",
                                "christmas", "halloween", "back to school", "new year"}
                seasonal_hits = [s for s in scored if any(t in s[0].lower() for t in season_terms)]
                if seasonal_hits:
                    return seasonal_hits[0][0]

            # For evergreen (or fallback): pick best relevance match
            if scored[0][1] > 0:  # has some relevance
                return scored[0][0]

    except Exception as e:
        logger.error(f"pick_best_keyword_for_product failed: {e}")

    # Fallback: generate a buying-intent keyword from product name + niche
    buying_intent_templates = {
        "beauty":     f"{product_name.split()[0].lower()} amazon beauty finds",
        "home_decor": f"aesthetic home decor amazon finds",
        "fitness":    f"wellness amazon finds self care",
    }
    return buying_intent_templates.get(niche, f"amazon {niche} finds 2026")


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
