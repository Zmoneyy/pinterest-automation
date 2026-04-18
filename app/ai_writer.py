"""
Claude API integration for generating Pinterest roundup/collage pin content.
Produces editorial titles, descriptions, and hashtags in the Jackie Aina style.
"""
import json
import logging
import random
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert Pinterest content creator specialising in affiliate roundup posts
in the style of Jackie Aina — editorial, aspirational, warm, never salesy.
Each pin features a curated collection of 5-8 products under a single theme.
Always respond with valid JSON only. No markdown, no extra text."""

# Roundup theme templates — Claude picks and personalises one
THEME_TEMPLATES = [
    "Weekly Favs",
    "Most Loved",
    "Currently Obsessed",
    "New Home Finds",
    "This Week's Picks",
    "Most Loved on Amazon",
    "Weekly Favs on Amazon",
    "Editor's Picks",
    "Can't Stop Buying These",
    "Amazon Haul",
    "Beauty Faves",
    "Home Refresh",
    "Cozy Season Finds",
    "Gift Ideas She'll Love",
    "Under $50 Finds",
    "Trending Right Now",
]

SUBTITLE_OPTIONS = [
    "on Amazon",
    "from Amazon",
    "on Benable",
    "this week",
    "right now",
]

CTA_OPTIONS = [
    "shop here \u2764\ufe0f",
    "click here \u2764\ufe0f",
    "links in bio \u2764\ufe0f",
    "shop now \u2764\ufe0f",
    "tap to shop \u2764\ufe0f",
]


def generate_roundup_content(
    products: list,
    trend_keyword: str,
    benable_url: str,
    theme_hint: Optional[str] = None,
) -> dict:
    """
    Generate a complete roundup pin content for a collage featuring multiple products.

    Returns:
        {
          "theme":       "WEEKLY FAVS",        # all-caps title shown on the image
          "subtitle":    "on Amazon",           # smaller text below the ornament
          "title":       "Weekly Favs on Amazon – Beauty Edition",  # Pinterest pin title
          "description": "...",
          "hashtags":    ["amazonfinds", ...],
          "cta_text":    "shop here ♥",
        }
    """
    from config import Config

    if not Config.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — using template content.")
        return _template_roundup(products, trend_keyword, benable_url, theme_hint)

    product_names = [p.name for p in products[:8]]

    # Get keyword-first title suggestion from keyword research engine
    try:
        from app.keyword_research import get_keyword_driven_title_prompt
        # Infer niche from products
        categories = [p.category for p in products[:8] if hasattr(p, "category") and p.category]
        niche = max(set(categories), key=categories.count) if categories else "beauty"
        title_hint = get_keyword_driven_title_prompt(trend_keyword, niche)
    except Exception:
        title_hint = None

    prompt = _build_roundup_prompt(product_names, trend_keyword, benable_url, theme_hint, title_hint)

    try:
        client  = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw  = message.content[0].text.strip()
        data = json.loads(raw)

        theme       = str(data.get("theme", "Weekly Favs")).strip().upper()[:40]
        subtitle    = str(data.get("subtitle", "on Amazon")).strip()[:30]
        title       = str(data.get("title", theme)).strip()[:100]
        description = str(data.get("description", "")).strip()[:250]
        hashtags    = _parse_hashtags(data.get("hashtags", []))[:4]
        cta_text    = str(data.get("cta_text", "shop here \u2764\ufe0f")).strip()[:30]

        if not title or not description:
            raise ValueError("Claude returned empty title or description.")

        logger.info(f"Claude roundup content generated (theme: {theme})")
        return {
            "theme":       theme,
            "subtitle":    subtitle,
            "title":       title,
            "description": description,
            "hashtags":    hashtags,
            "cta_text":    cta_text,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Claude returned invalid JSON: {e}")
        return _template_roundup(products, trend_keyword, benable_url, theme_hint)
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return _template_roundup(products, trend_keyword, benable_url, theme_hint)
    except Exception as e:
        logger.error(f"Roundup content generation failed: {e}", exc_info=True)
        return _template_roundup(products, trend_keyword, benable_url, theme_hint)


def _build_roundup_prompt(
    product_names: list,
    trend_keyword: str,
    benable_url: str,
    theme_hint: Optional[str],
    title_hint: Optional[str] = None,
) -> str:
    theme_suggestion = (
        f'Suggested theme: "{theme_hint}".' if theme_hint
        else f"Pick the most fitting theme from these options: {', '.join(random.sample(THEME_TEMPLATES, 6))}."
    )

    products_str = "\n".join(f"- {n}" for n in product_names)

    from app.seasonal import get_season_context_for_claude
    season_context = get_season_context_for_claude()

    title_guidance = (
        f'Title inspiration (rewrite this in your own words, keyword-first): "{title_hint}"'
        if title_hint
        else "title: 60-100 chars, catchy and specific to the trend, keyword-first, do NOT list product names"
    )

    return f"""Create Pinterest pin content for a roundup collage. The products are all related to: {trend_keyword}

{theme_suggestion}

Trending keyword: {trend_keyword}
Affiliate link: {benable_url}
{season_context}

Requirements:

TITLE ({title_guidance}):
- Must start with the keyword or close variation — keyword-first
- Include the year (e.g. "2026") to signal freshness
- 60-100 chars
- Example format: "Summer Nail Sets for 2026 — Best Finds on Amazon Right Now"

THEME (text shown on the image):
- 1-3 words ALL CAPS, transformation-focused not feature-focused
- Focus on how it makes you feel or look, not what it is
- Examples: "GLOW UP", "SUMMER NAILS", "COZY VIBES", "REFRESH YOUR SPACE"

SUBTITLE:
- 2-4 words (e.g. "on Amazon", "this week", "for 2026")

DESCRIPTION — follow this 3-part formula exactly:
1. Keyword-rich sentence: "This pin is about [keyword-rich phrase including trend_keyword and variations]"
2. Benefit sentence: explain WHY these products are worth it (transformation, value, quality)
3. Soft CTA: "Visit the link to shop +" or "Click the link to see the full list +"
- Total: 180-250 chars. End with: {benable_url}
- Example: "This pin is about the best summer nail sets on Amazon for 2026. Affordable press-on designs that actually last all week. Visit the link to shop + {benable_url}"

HASHTAGS: exactly 3-4
- 1 broad: #amazonfinds or #amazonnails or #amazonhome
- 1 trend-specific: based on "{trend_keyword}" (e.g. #{trend_keyword.replace(' ', '')})
- 1 niche/product-type specific
- NO generic tags: #weeklyfinds #mostloved #productfaves #shoppingfinds

CTA TEXT: 3-5 words for image button (e.g. "shop the list ♥")

Respond with ONLY this JSON:
{{
  "theme": "SUMMER NAILS",
  "subtitle": "on Amazon",
  "title": "...",
  "description": "...",
  "hashtags": ["tag1", "tag2", "tag3"],
  "cta_text": "shop the list ♥"
}}"""


def _template_roundup(
    products: list,
    trend_keyword: str,
    benable_url: str,
    theme_hint: Optional[str],
) -> dict:
    """Fallback template content when Claude is unavailable."""
    theme    = (theme_hint or random.choice(THEME_TEMPLATES)).upper()
    subtitle = random.choice(SUBTITLE_OPTIONS)
    cta_text = random.choice(CTA_OPTIONS)

    description = (
        f"This pin is about the best {trend_keyword} finds on Amazon for 2026. "
        f"Affordable, aesthetic, and actually worth it. "
        f"Visit the link to shop + {benable_url}"
    )

    keyword_tag = trend_keyword.replace(" ", "").lower()
    hashtags = [
        "amazonfinds",
        keyword_tag,
        keyword_tag + "amazon",
        "affordablefinds",
    ]

    return {
        "theme":       theme,
        "subtitle":    subtitle,
        "title":       f"{theme.title()} — {subtitle.title()} ({trend_keyword.title()})",
        "description": description,
        "hashtags":    hashtags[:10],
        "cta_text":    cta_text,
    }


def analyze_trends_for_brand(trends: list, brand_name: str, benable_url: str) -> dict:
    """
    Use Claude to analyze Pinterest trends and return pin opportunities for the brand.
    trends: list of {keyword, weekly_change, monthly_change, yearly_change, score}
    """
    from config import Config

    if not Config.ANTHROPIC_API_KEY:
        return _template_trend_analysis(trends, brand_name)

    trends_text = "\n".join(
        f"- {t['keyword']} (monthly: +{t.get('monthly_change','?')}%, score: {t.get('score',0):.0f})"
        for t in trends[:20]
    )

    prompt = f"""You are a Pinterest content strategist for "{brand_name}", an Amazon affiliate brand
targeting women who love affordable aesthetic finds. The affiliate collection is at {benable_url}.

Here are the top trending Pinterest searches right now:
{trends_text}

Analyze these and return JSON with:
- top_opportunities: 5 best trends that match Amazon-purchasable products for our brand
- pin_ideas: 5 specific pin ideas (title + theme), each tied to a trending keyword
- product_categories: list of specific product types to add (e.g. "gel nail starter kits", "press-on nails")

Respond with ONLY this JSON:
{{
  "top_opportunities": [
    {{"trend": "spring nails", "reason": "...", "monthly_change": "200%"}}
  ],
  "pin_ideas": [
    {{"trend": "spring nails", "title": "Spring Nail Inspo You Can Actually Get on Amazon", "theme": "SPRING NAILS"}}
  ],
  "product_categories": ["gel nail starter kits", "press-on nails spring colors"]
}}"""

    try:
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system="You are an expert Pinterest content strategist. Always respond with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Trend analysis failed: {e}")
        return _template_trend_analysis(trends, brand_name)


def _template_trend_analysis(trends: list, brand_name: str) -> dict:
    top = trends[:5]
    return {
        "top_opportunities": [
            {"trend": t["keyword"], "reason": "High search volume", "monthly_change": str(t.get("monthly_change", "N/A"))}
            for t in top
        ],
        "pin_ideas": [
            {"trend": t["keyword"], "title": f"Best {t['keyword'].title()} Finds on Amazon", "theme": t["keyword"].upper()[:20]}
            for t in top
        ],
        "product_categories": [t["keyword"] for t in top[:8]],
    }


def generate_upload_pin_copy(niche: str, keyword: str = "") -> dict:
    """
    Generate Pinterest copy for a manually uploaded pin image.
    Returns title, description, and hashtags based on niche + keyword.
    """
    from config import Config

    niche_context = {
        "beauty": "beauty, nails, skincare, makeup, and self-care products on Amazon",
        "home_decor": "glam home decor, furniture, and interior styling finds on Amazon",
        "fitness": "wellness, fitness, and self-care products on Amazon",
    }

    context = niche_context.get(niche, niche_context["beauty"])
    keyword_line = f"The pin is focused on this keyword/topic: {keyword}." if keyword else ""
    benable_url = Config.BENABLE_URL

    prompt = f"""You are a Pinterest expert writing copy for an affiliate pin for the brand "Aura Girl Essentials".
The pin features {context}.
{keyword_line}

Write Pinterest copy following the Money Making Pin Formula:
1. TITLE: Keyword-first, include the year (2026), max 8 words, mixed case (not all caps)
2. DESCRIPTION: 3 parts — (a) keyword-rich sentence about what's in the pin, (b) benefit to the viewer, (c) soft CTA ending with this Benable link: {benable_url}
3. HASHTAGS: 10-15 relevant Pinterest hashtags (no # symbol, comma separated)

Respond with ONLY this JSON:
{{
  "title": "...",
  "description": "...",
  "hashtags": "amazonfinds, beautyfaves, ..."
}}"""

    try:
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system="You are a Pinterest content expert. Always respond with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(message.content[0].text.strip())
        return {
            "title": data.get("title", "Amazon Finds You'll Love 2026"),
            "description": data.get("description", ""),
            "hashtags": data.get("hashtags", "amazonfinds, auragirlfinds"),
        }
    except Exception as e:
        logger.error(f"Upload pin copy generation failed: {e}")
        keyword_title = keyword.title() if keyword else "Amazon Finds"
        return {
            "title": f"{keyword_title} You Need in 2026",
            "description": f"Obsessed with these {context}! Perfect for anyone who loves affordable, aesthetic finds. Shop all links here: {benable_url}",
            "hashtags": "amazonfinds, auragirlfinds, affordablefinds, pinterestfinds, amazonfavorites",
        }


def _parse_hashtags(raw) -> list:
    if isinstance(raw, str):
        return [h.strip().lstrip("#") for h in raw.split(",") if h.strip()][:10]
    if isinstance(raw, list):
        return [str(h).strip().lstrip("#") for h in raw if h][:10]
    return []
