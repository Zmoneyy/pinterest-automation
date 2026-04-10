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

    prompt = _build_roundup_prompt(product_names, trend_keyword, benable_url, theme_hint)

    try:
        client  = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw  = message.content[0].text.strip()
        data = json.loads(raw)

        theme       = str(data.get("theme", "Weekly Favs")).strip().upper()[:40]
        subtitle    = str(data.get("subtitle", "on Amazon")).strip()[:30]
        title       = str(data.get("title", theme)).strip()[:100]
        description = str(data.get("description", "")).strip()[:500]
        hashtags    = _parse_hashtags(data.get("hashtags", []))
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
) -> str:
    theme_suggestion = (
        f'Suggested theme: "{theme_hint}".' if theme_hint
        else f"Pick the most fitting theme from these options: {', '.join(random.sample(THEME_TEMPLATES, 6))}."
    )

    products_str = "\n".join(f"- {n}" for n in product_names)

    return f"""Create Pinterest pin content for a roundup collage featuring these products:

{products_str}

Trending keyword to weave in: {trend_keyword}
Affiliate collection link: {benable_url}

{theme_suggestion}

Requirements:
- theme: 1-3 words ALL CAPS (shown huge on image, e.g. "WEEKLY FAVS", "MOST LOVED")
- subtitle: 2-4 words shown smaller below ornament (e.g. "on Amazon", "this week")
- title: Pinterest pin title, 60-100 chars, catchy, includes the theme naturally
- description: 200-350 chars, warm and personal, naturally includes {benable_url}, ends with a soft CTA
- hashtags: 7-10 as a list, mix broad (#amazonfinds) and specific (#{trend_keyword.replace(' ', '')})
- cta_text: 3-5 words for the pill button on the image (e.g. "shop here ♥")

Respond with ONLY this JSON:
{{
  "theme": "WEEKLY FAVS",
  "subtitle": "on Amazon",
  "title": "...",
  "description": "...",
  "hashtags": ["tag1", "tag2"],
  "cta_text": "shop here ♥"
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

    names_preview = ", ".join(p.name for p in products[:3])
    description = (
        f"Rounding up this week's most-loved finds — {names_preview} and more. "
        f"These are the things I keep reaching for! "
        f"All links are on my Benable page: {benable_url} \u2764\ufe0f"
    )

    keyword_tag = trend_keyword.replace(" ", "").lower()
    hashtags = [
        "amazonfinds", "weeklyfinds", "mostloved", "productfaves",
        "shoppingfinds", "musthaves", keyword_tag, "benablelinks",
        "affiliatelinks", "roundup",
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
            model="claude-3-5-haiku-20241022",
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


def _parse_hashtags(raw) -> list:
    if isinstance(raw, str):
        return [h.strip().lstrip("#") for h in raw.split(",") if h.strip()][:10]
    if isinstance(raw, list):
        return [str(h).strip().lstrip("#") for h in raw if h][:10]
    return []
