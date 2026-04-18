"""
Seasonal awareness for Pinterest content strategy.

Pinterest content should be posted 2-3 months AHEAD of the actual season.
This module automatically calculates the target season and returns
relevant keywords, themes, and search queries.

April   → Summer (June/July/August)
May     → Summer + Back to School
June    → Back to School + Early Fall
July    → Fall + Halloween
August  → Fall + Thanksgiving + Halloween
September → Christmas + Winter Holiday
October → Christmas + New Year
November → Valentine's Day + Spring
December → Valentine's Day + Spring
January → Spring + Easter
February → Summer (early planning)
March   → Summer
"""

from datetime import datetime, timezone


# Maps current month → target season content
SEASONAL_MAP = {
    1:  {"season": "Spring",    "label": "spring",      "months_ahead": "March–April"},
    2:  {"season": "Summer",    "label": "summer",      "months_ahead": "May–June"},
    3:  {"season": "Summer",    "label": "summer",      "months_ahead": "June–July"},
    4:  {"season": "Summer",    "label": "summer",      "months_ahead": "June–August"},
    5:  {"season": "Back to School + Fall", "label": "fall", "months_ahead": "August–September"},
    6:  {"season": "Fall",      "label": "fall",        "months_ahead": "September–October"},
    7:  {"season": "Fall + Halloween", "label": "fall", "months_ahead": "October"},
    8:  {"season": "Thanksgiving + Holiday", "label": "holiday", "months_ahead": "November"},
    9:  {"season": "Christmas + Winter", "label": "christmas", "months_ahead": "December"},
    10: {"season": "Christmas + New Year", "label": "christmas", "months_ahead": "December–January"},
    11: {"season": "Valentine's Day + Spring", "label": "valentines", "months_ahead": "February–March"},
    12: {"season": "Valentine's Day + Spring", "label": "valentines", "months_ahead": "February–March"},
}

# Seasonal keywords per niche per season
SEASONAL_KEYWORDS = {
    "summer": {
        "beauty": [
            "summer nails 2026", "summer makeup looks", "beach nails",
            "summer skincare routine", "summer glow products", "tanning drops",
            "sunscreen amazon", "waterproof makeup summer", "summer self care",
        ],
        "home_decor": [
            "summer home decor", "beach aesthetic room", "summer bedroom decor",
            "outdoor entertaining decor", "summer candles", "bright home aesthetic 2026",
        ],
        "fitness": [
            "summer body supplements", "sunscreen spf amazon", "tanning oil amazon",
            "summer wellness routine", "hydration supplements", "collagen summer glow",
        ],
    },
    "fall": {
        "beauty": [
            "fall nails 2026", "autumn nail colors", "fall makeup trends",
            "fall skincare routine", "cozy girl makeup", "fall nail inspo",
        ],
        "home_decor": [
            "fall home decor amazon", "cozy fall aesthetic", "autumn room decor",
            "fall candles amazon", "pumpkin decor aesthetic", "cozy bedroom fall",
        ],
        "fitness": [
            "fall wellness routine", "immune support supplements amazon",
            "cozy self care fall", "fall glow supplements",
        ],
    },
    "christmas": {
        "beauty": [
            "christmas nails 2026", "holiday makeup looks", "gift sets beauty amazon",
            "winter nail ideas", "holiday glam makeup", "christmas nail inspo",
        ],
        "home_decor": [
            "christmas home decor amazon", "holiday aesthetic decor",
            "cozy christmas room", "holiday candles amazon", "christmas aesthetic 2026",
        ],
        "fitness": [
            "holiday gift sets wellness", "self care gift sets amazon",
            "winter glow supplements", "holiday self care routine",
        ],
    },
    "valentines": {
        "beauty": [
            "valentines day nails", "pink nails valentine", "valentines makeup look",
            "galentines beauty gifts", "valentines gift sets beauty",
        ],
        "home_decor": [
            "valentines day decor amazon", "pink aesthetic room decor",
            "galentines party decor", "pink home aesthetic",
        ],
        "fitness": [
            "valentines self care gifts", "galentines wellness gifts amazon",
            "self love supplements", "pink self care amazon",
        ],
    },
    "spring": {
        "beauty": [
            "spring nails 2026", "spring makeup trends", "spring skincare routine",
            "easter nails pastel", "spring glow products", "floral nail ideas",
        ],
        "home_decor": [
            "spring home decor amazon", "spring room refresh", "floral decor amazon",
            "pastel aesthetic room", "spring candles amazon",
        ],
        "fitness": [
            "spring wellness routine", "spring glow supplements",
            "detox supplements spring", "spring self care amazon",
        ],
    },
    "holiday": {
        "beauty": [
            "holiday gift sets beauty", "thanksgiving nails", "holiday makeup",
            "gift ideas for her beauty", "thanksgiving nail inspo",
        ],
        "home_decor": [
            "thanksgiving decor amazon", "fall holiday home decor",
            "friendsgiving table decor", "cozy holiday aesthetic",
        ],
        "fitness": [
            "holiday wellness gifts", "thanksgiving self care",
            "immune support holiday", "gift sets wellness amazon",
        ],
    },
}

# Seasonal Amazon search queries per niche
SEASONAL_SEARCH_QUERIES = {
    "summer": {
        "beauty": [
            ("summer nails press on amazon", "beauty"),
            ("sunscreen spf amazon 2026", "fitness"),
            ("tanning oil drops amazon", "fitness"),
            ("summer glow skincare amazon", "beauty"),
        ],
        "home_decor": [
            ("summer home decor amazon", "home_decor"),
            ("beach aesthetic decor amazon", "home_decor"),
        ],
        "fitness": [
            ("collagen supplement summer glow", "fitness"),
            ("hydration supplement amazon", "fitness"),
        ],
    },
    "fall": {
        "beauty": [
            ("fall nail sets amazon", "beauty"),
            ("autumn makeup amazon", "beauty"),
        ],
        "home_decor": [
            ("fall candles amazon", "home_decor"),
            ("cozy fall decor amazon", "home_decor"),
        ],
        "fitness": [
            ("immune support supplements amazon", "fitness"),
            ("fall self care amazon", "fitness"),
        ],
    },
    "christmas": {
        "beauty": [
            ("christmas nail sets amazon", "beauty"),
            ("holiday makeup gift set amazon", "beauty"),
        ],
        "home_decor": [
            ("christmas decor amazon affordable", "home_decor"),
            ("holiday candles amazon", "home_decor"),
        ],
        "fitness": [
            ("self care gift set amazon", "fitness"),
            ("holiday wellness gifts amazon", "fitness"),
        ],
    },
    "valentines": {
        "beauty": [
            ("valentines nails amazon", "beauty"),
            ("pink makeup set amazon", "beauty"),
        ],
        "home_decor": [
            ("pink aesthetic decor amazon", "home_decor"),
            ("valentines decor amazon", "home_decor"),
        ],
        "fitness": [
            ("self love gift set amazon", "fitness"),
            ("galentines wellness amazon", "fitness"),
        ],
    },
    "spring": {
        "beauty": [
            ("spring nail sets amazon", "beauty"),
            ("spring skincare amazon", "beauty"),
        ],
        "home_decor": [
            ("spring home decor amazon", "home_decor"),
            ("floral decor amazon", "home_decor"),
        ],
        "fitness": [
            ("spring glow supplements amazon", "fitness"),
            ("detox tea amazon", "fitness"),
        ],
    },
    "holiday": {
        "beauty": [
            ("thanksgiving nails amazon", "beauty"),
            ("holiday gift set beauty amazon", "beauty"),
        ],
        "home_decor": [
            ("thanksgiving decor amazon", "home_decor"),
            ("fall holiday candles amazon", "home_decor"),
        ],
        "fitness": [
            ("holiday wellness gift set", "fitness"),
            ("immune boost supplement amazon", "fitness"),
        ],
    },
}


def get_current_season() -> dict:
    """
    Returns the season your content should target RIGHT NOW based on today's date.
    Pinterest strategy: post 2-3 months ahead of the actual season.
    """
    month = datetime.now(timezone.utc).month
    return SEASONAL_MAP[month]


def get_seasonal_keywords(niche: str = None) -> list[str]:
    """
    Returns trending seasonal keywords for the target season.
    Optionally filter by niche (beauty, home_decor, fitness).
    """
    season_info = get_current_season()
    label = season_info["label"]
    season_data = SEASONAL_KEYWORDS.get(label, SEASONAL_KEYWORDS["summer"])

    if niche and niche in season_data:
        return season_data[niche]

    # Return all niches combined
    all_keywords = []
    for kw_list in season_data.values():
        all_keywords.extend(kw_list)
    return all_keywords


def get_seasonal_search_queries() -> list[tuple]:
    """
    Returns Amazon search queries tuned to the current target season.
    Each item is (query_string, category).
    """
    season_info = get_current_season()
    label = season_info["label"]
    season_data = SEASONAL_SEARCH_QUERIES.get(label, SEASONAL_SEARCH_QUERIES["summer"])

    queries = []
    for niche_queries in season_data.values():
        queries.extend(niche_queries)
    return queries


def get_season_context_for_claude() -> str:
    """
    Returns a short string to inject into Claude's prompt so it writes
    season-appropriate copy without being told manually.
    """
    season_info = get_current_season()
    return (
        f"Target season: {season_info['season']} "
        f"(posting now for {season_info['months_ahead']}). "
        f"Write copy that feels timely and ahead of the curve for this upcoming season."
    )
