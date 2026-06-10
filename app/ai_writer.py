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
Products in the collage:
{products_str}
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


def generate_ideogram_prompt(
    product_names: list,
    niche: str,
    theme: str,
    subtitle: str,
) -> Optional[str]:
    """
    Use Claude to generate a product-specific Ideogram image prompt
    following the Pin Perfect Pro formula.
    """
    from config import Config

    niche_aesthetics = {
        "beauty": {
            "bg": "soft blush pink background",
            "palette": "blush pink, nude, white, rose gold",
            "style": "feminine luxury beauty editorial, soft studio lighting",
            "example_products": "glossy lip gloss, skincare serum, press-on nail kit, lash serum",
        },
        "home_decor": {
            "bg": "clean white background",
            "palette": "black, gold, brass, clear acrylic",
            "style": "glam home decor editorial, aspirational interior styling",
            "example_products": "gold chandelier, black velvet ottoman, gold bar cart, marble tray",
        },
        "fitness": {
            "bg": "clean white background",
            "palette": "white, sage green, soft mint",
            "style": "clean girl wellness aesthetic, minimal aspirational",
            "example_products": "collagen supplement jar, insulated water bottle, sunscreen stick, resistance bands",
        },
    }

    cfg = niche_aesthetics.get(niche, niche_aesthetics["beauty"])
    products_str = ", ".join(product_names[:6]) if product_names else cfg["example_products"]

    prompt = f"""You are a Pinterest pin image prompt expert replicating Pin Perfect Pro quality.
Generate an Ideogram image generation prompt for a Pinterest pin.

Products to feature: {products_str}
Niche: {niche}
Pin theme text: {theme}
Subtitle: {subtitle}

Visual style requirements:
- Background: {cfg['bg']}
- Color palette: {cfg['palette']} ONLY — strict cohesion, all products match
- Style: {cfg['style']}
- Layout: floating product images with transparent backgrounds arranged naturally overlapping like a curated mood board (NOT a grid)
- Products fill the upper two-thirds of the image
- Each product rendered photorealistically with soft studio lighting and natural shadows
- At the top center: small elegant spaced uppercase brand label "AURA GIRL ESSENTIALS"
- In the lower third: large elegant mixed-case serif font theme text "{theme}"
- Below theme text in small italic: "{subtitle}"
- Bottom center: dark rounded pill-shaped button with white text "shop here ♥"
- High-end magazine editorial feel — products are the hero, text is elegant and understated
- Vertical 2:3 portrait format, scroll-stopping Pinterest aesthetic
- Photorealistic, not AI-looking. No watermarks. No borders.

Write ONLY the image generation prompt as plain text (no JSON, no labels, no explanation).
Make it vivid, specific, and mention every visual element. 150-250 words."""

    try:
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system="You write vivid, specific image generation prompts for Pinterest pins. Output only the prompt text, nothing else.",
            messages=[{"role": "user", "content": prompt}],
        )
        result = message.content[0].text.strip()
        logger.info(f"Ideogram prompt generated ({len(result)} chars)")
        return result
    except Exception as e:
        logger.error(f"Ideogram prompt generation failed: {e}")
        return None


def generate_pin_perfect_pro(
    product_names: list,
    niche: str,
    trend_keyword: str,
    shop_url: str,
    board_name: str = "",
) -> dict:
    """
    Generate a full Pin Perfect Pro output for a set of products and trending keyword.
    Returns:
      {
        "title": "...",
        "description": "...",
        "hashtags": "tag1, tag2, ...",
        "alt_text": "...",
        "board_name": "...",
        "image_prompt": "...",   # ready for Ideogram
        "theme": "...",          # ALL CAPS theme text for image
        "subtitle": "...",
      }
    """
    from config import Config

    niche_context = {
        "beauty": "beauty, skincare, nails, makeup, and self-care products on Amazon",
        "home_decor": "glam home decor, furniture, and interior styling finds on Amazon",
        "fitness": "wellness, fitness, and self-care products on Amazon",
    }
    context = niche_context.get(niche, niche_context["beauty"])
    products_str = ", ".join(product_names[:6]) if product_names else "top Amazon finds"

    niche_image_style = {
        "beauty": "soft blush pink background, blush/nude/white/rose gold color palette, feminine luxury editorial, floating product arrangement, soft studio lighting",
        "home_decor": "clean white background, strict black and gold palette, glam interior editorial, products overlapping like a mood board",
        "fitness": "clean white background, sage green and white palette, clean girl wellness aesthetic, minimal aspirational layout",
    }.get(niche, "soft blush pink background, feminine luxury editorial")

    niche_boards = {
        "beauty": "Beauty Finds & Skincare",
        "home_decor": "Glam Home Decor Ideas",
        "fitness": "Wellness & Self Care Essentials",
    }
    default_board = niche_boards.get(niche, "Beauty Finds & Skincare")

    prompt = f"""You are writing Pinterest content for "Aura Girl Essentials", an Amazon affiliate brand targeting women who love affordable aesthetic finds.

You MUST follow the Pinterest Pin Copy Formula below — this is what drives clicks and saves on Pinterest.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE PINTEREST PIN COPY FORMULA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TITLE = Primary Keyword + Benefit + Curiosity/Specificity
  • Start with the exact keyword (what someone is searching for)
  • Add what they'll GET (outcome, not feature)
  • Add a number, year, or specific angle to boost credibility
  • 60-100 characters. Include 2026 or 2027 for freshness.
  • Example: "Best Chemical Exfoliants 2026 — Smoother Skin in Days"

DESCRIPTION = 4 parts in order:
  1. PRIMARY KEYWORD + SUPPORTING KEYWORDS naturally woven in (searchable)
  2. CLEAR BENEFIT — what will they get? Focus on outcomes/transformation
  3. EXPANDED CONTEXT — why these specific products, what makes them worth it
  4. SOFT CTA — Pinterest is discovery-based, keep it light
     Use: "Save this for later →" or "Tap to shop →" or "Get the full list →" then add: {shop_url}
  • Total: 150-250 characters. Conversational, not salesy.

HASHTAGS = 10-15 tags, mix of:
  • 1-2 broad discovery (#amazonfinds, #amazonskincare)
  • 2-3 keyword-specific (based on the primary keyword)
  • 2-3 niche/transformation (#glowup, #skincareRoutine, #clearskin)
  • NO generic filler: #weeklyfinds #mostloved #productfaves

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXAMPLE 1 — Beauty/Skincare:
Keyword: chemical exfoliant for smooth skin
Products: Paula's Choice BHA liquid exfoliant
{{
  "title": "Best Chemical Exfoliant for Smooth Skin 2026 — This One Actually Works",
  "description": "Searching for a chemical exfoliant that clears texture and minimizes pores? Paula's Choice BHA is a cult favorite for a reason — one swipe and your skin looks visibly smoother. Save this for later → {shop_url}",
  "hashtags": "amazonfinds, chemicalexfoliant, bhaserum, smoothskin, porescleaned, skincareAmazon, glowup, exfoliatingtoner, clearTexture, skincareroutine, affordableskincare, amazonskincare",
  "alt_text": "Woman with glowing clear skin holding Paula's Choice BHA liquid exfoliant bottle",
  "board_name": "Skincare Finds & Glow Up Routines",
  "theme": "NEW SKIN",
  "subtitle": "on Amazon",
  "benefits": ["Zero Texture", "Pores Clear", "Instant Glow"],
  "image_prompt": "Pinterest pin, vertical 2:3 portrait, soft warm background. Woman with visibly glowing dewy skin holding a Paula's Choice BHA Liquid Exfoliant bottle — white cylindrical bottle with black label reading SKIN PERFECTING 2% BHA Liquid Exfoliant. Lifestyle editorial feel, soft natural light, minimal bathroom setting. Large bold black headline NEW SKIN at top. Bottom white band with 3 centered lines: Zero Texture / Pores Clear / Instant Glow. Dark rounded pill button: Shop on Amazon. Small AURA GIRL ESSENTIALS label at very top."
}}

EXAMPLE 2 — Home Decor:
Keyword: glam home decor on a budget
Products: gold arc floor lamp, velvet ottoman
{{
  "title": "Glam Home Decor on a Budget 2026 — Amazon Finds That Look Expensive",
  "description": "Love the glam aesthetic but don't want to overspend? These Amazon home decor finds — gold lamps, velvet ottomans — look designer without the price tag. Tap to shop → {shop_url}",
  "hashtags": "amazonhome, glamhomedecor, budgethomedecor, affordabledecor, homedecor2026, goldhomedecor, amazonfinds, homeaesthetic, livingroominspo, homerefresh, interiordesign, velvetdecor",
  "alt_text": "Glam home decor collection with gold floor lamp and black velvet ottoman styled in an aspirational living room",
  "board_name": "Glam Home Decor Ideas",
  "theme": "ELEVATED",
  "subtitle": "for less",
  "benefits": ["Looks Expensive", "Ships Fast", "Budget Win"],
  "image_prompt": "Pinterest pin, vertical 2:3 portrait, clean white background. Gold arc floor lamp and black velvet ottoman with gold legs styled together in an aspirational minimal living room. Strict black and gold palette. Photorealistic studio lighting. Large bold ELEVATED headline at top. Bottom white band 3 lines: Looks Expensive / Ships Fast / Budget Win. Dark rounded pill: Shop on Amazon. AURA GIRL ESSENTIALS label at very top."
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOW GENERATE FOR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Keyword: {trend_keyword}
Products: {products_str}
Niche: {niche} ({context})
Shop URL: {shop_url}
Default board if unsure: {default_board}
Image style: {niche_image_style}

STRICT RULES:
- THEME: 1-3 words ALL CAPS. Think about what makes THESE SPECIFIC PRODUCTS unique — one result they're famous for that others aren't. Base the theme on that. NEVER reuse themes across products — each must have its OWN hook.
- BENEFITS: exactly 3, MAX 2 WORDS EACH — no exceptions. They appear as 3 separate centered lines. Short enough to read instantly.
- IMAGE PROMPT — follow these rules exactly based on niche:
  BEAUTY: Clean white or light beige background. Product hero centered, no people. Add texture swipe if it's a cream/liquid. Add water droplets if hydrating. Bold clean sans-serif headline. Describe the product's EXACT colors and packaging from the reference.
  HOME DECOR: Full lifestyle room scene — sofa, candles, plants, rugs, wall art. Product styled IN the room. Warm ambient tones (cream, beige, wood). Serif or mixed font headline. The room scene is essential — never plain white background for home decor.
  FITNESS: Fresh ingredients around the product (citrus, berries, greens) matching the product flavor/benefit. Or a woman using the product in a wellness setting. Bold heavy headline. Bright, clean, energizing.
  ALWAYS: Match the pin's color palette to the product's actual packaging colors. Include "AURA GIRL ESSENTIALS" small text at very top. Headline at top, product in middle, 3 benefit lines below product, pill CTA at bottom.

Respond ONLY with valid JSON:
{{
  "title": "...",
  "description": "...",
  "hashtags": "tag1, tag2, ...",
  "alt_text": "...",
  "board_name": "...",
  "theme": "...",
  "subtitle": "...",
  "benefits": ["Word Word", "Word Word", "Word Word"],
  "image_prompt": "..."
}}"""

    try:
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system="You are an expert Pinterest content creator. You follow formulas exactly and write copy that drives clicks. Always respond with valid JSON only — no markdown, no explanation.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if not raw:
            logger.error(f"Pin Perfect Pro: Claude returned empty response for keyword='{trend_keyword}', products={product_names}")
            return {}
        # Strip markdown code fences if Claude wrapped the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        logger.info(f"Pin Perfect Pro content generated for keyword: {trend_keyword}")

        # Parse benefits — expect a list of 3 short strings
        raw_benefits = data.get("benefits", [])
        if isinstance(raw_benefits, list):
            benefits = [str(b).strip() for b in raw_benefits[:3] if b]
        else:
            benefits = []

        return {
            "title":        str(data.get("title", "")).strip()[:100],
            "description":  str(data.get("description", "")).strip()[:500],
            "hashtags":     str(data.get("hashtags", "")).strip(),
            "alt_text":     str(data.get("alt_text", "")).strip()[:500],
            "board_name":   str(data.get("board_name", board_name)).strip(),
            "theme":        str(data.get("theme", "")).strip().upper()[:30],
            "subtitle":     str(data.get("subtitle", "on Amazon")).strip()[:30],
            "benefits":     benefits,
            "image_prompt": str(data.get("image_prompt", "")).strip(),
        }
    except json.JSONDecodeError as e:
        logger.error(f"Pin Perfect Pro returned invalid JSON: {e} | raw={raw[:200] if 'raw' in dir() else 'N/A'}")
        return {}
    except Exception as e:
        logger.error(f"Pin Perfect Pro generation failed: {e}", exc_info=True)
        return {}


def _parse_hashtags(raw) -> list:
    if isinstance(raw, str):
        return [h.strip().lstrip("#") for h in raw.split(",") if h.strip()][:10]
    if isinstance(raw, list):
        return [str(h).strip().lstrip("#") for h in raw if h][:10]
    return []
