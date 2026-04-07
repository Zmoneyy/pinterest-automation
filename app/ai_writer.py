"""
Claude API integration for generating Pinterest pin content.
Uses the anthropic library to produce titles, descriptions, and hashtags.
"""
import json
import logging
import random
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

STYLES = ["inspirational", "practical", "lifestyle", "gift_guide", "educational"]

SYSTEM_PROMPT = """You are an expert Pinterest content creator who specializes in affiliate marketing.
You write pin content that feels authentic, helpful, and lifestyle-focused — never spammy or clickbait-y.
Your content gets high engagement because it genuinely helps people discover products they'll love.
Always respond with valid JSON only, no markdown, no extra text."""


def generate_pin_content(
    product_name: str,
    trend_keyword: str,
    category: str,
    benable_url: str,
    style: Optional[str] = None,
) -> dict:
    """
    Generate pin title, description, and hashtags using Claude.

    Returns a dict with keys: title, description, hashtags (list), style
    Falls back to template content if Claude is unavailable.
    """
    from config import Config

    if not Config.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set. Using template pin content.")
        return _template_content(product_name, trend_keyword, category, benable_url, style)

    chosen_style = style or random.choice(STYLES)

    prompt = _build_prompt(product_name, trend_keyword, category, benable_url, chosen_style)

    try:
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

        message = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        data = json.loads(raw)

        # Validate and sanitize
        title = str(data.get("title", "")).strip()[:100]
        description = str(data.get("description", "")).strip()[:500]
        hashtags = data.get("hashtags", [])

        if isinstance(hashtags, str):
            hashtags = [h.strip().lstrip("#") for h in hashtags.split(",") if h.strip()]
        elif isinstance(hashtags, list):
            hashtags = [str(h).strip().lstrip("#") for h in hashtags if h]

        hashtags = hashtags[:10]

        if not title or not description:
            raise ValueError("Claude returned empty title or description.")

        logger.info(f"Claude generated pin content for '{product_name}' (style: {chosen_style})")
        return {
            "title": title,
            "description": description,
            "hashtags": hashtags,
            "style": chosen_style,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Claude returned invalid JSON: {e}. Raw: {raw[:200] if 'raw' in dir() else 'N/A'}")
        return _template_content(product_name, trend_keyword, category, benable_url, chosen_style)
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return _template_content(product_name, trend_keyword, category, benable_url, chosen_style)
    except Exception as e:
        logger.error(f"Unexpected error generating pin content: {e}", exc_info=True)
        return _template_content(product_name, trend_keyword, category, benable_url, chosen_style)


def generate_pin_content_variations(
    product_name: str,
    trend_keyword: str,
    category: str,
    benable_url: str,
    count: int = 3,
) -> list[dict]:
    """
    Generate multiple style variations of pin content for the same product.
    Returns a list of content dicts.
    """
    styles = random.sample(STYLES, min(count, len(STYLES)))
    variations = []

    for style in styles:
        content = generate_pin_content(
            product_name=product_name,
            trend_keyword=trend_keyword,
            category=category,
            benable_url=benable_url,
            style=style,
        )
        variations.append(content)

    return variations


def _build_prompt(
    product_name: str,
    trend_keyword: str,
    category: str,
    benable_url: str,
    style: str,
) -> str:
    style_instructions = {
        "inspirational": (
            "Write in an inspirational, aspirational tone. Focus on the lifestyle upgrade "
            "this product brings. Make the reader feel excited about transforming their space or routine."
        ),
        "practical": (
            "Write in a helpful, practical tone. Focus on the problem this product solves "
            "and its key benefits. Appeal to people who want smart, functional solutions."
        ),
        "lifestyle": (
            "Write in a warm, personal lifestyle tone as if a friend is recommending this. "
            "Paint a picture of how this fits beautifully into everyday life."
        ),
        "gift_guide": (
            "Write as a gift recommendation. Position this as a perfect gift idea, "
            "focusing on who would love it and why it makes a thoughtful present."
        ),
        "educational": (
            "Write in an informative, educational tone. Share a useful tip or insight "
            "related to the product and how it enhances daily life."
        ),
    }

    instruction = style_instructions.get(style, style_instructions["lifestyle"])

    return f"""Create Pinterest pin content for this product:

Product: {product_name}
Trending keyword to incorporate: {trend_keyword}
Category: {category}
Affiliate link: {benable_url}
Content style: {style}

Style instruction: {instruction}

Requirements:
- Title: Under 100 characters, catchy but not clickbait, can include the trend keyword naturally
- Description: 150-300 characters, naturally weave in the affiliate link {benable_url}, lifestyle-focused, ends with a subtle call to action
- Hashtags: 5-10 hashtags as a list, mix of broad (like #homedecor) and specific, no # symbol needed

Respond with ONLY this JSON format, no other text:
{{
  "title": "your title here",
  "description": "your description here including {benable_url}",
  "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
}}"""


def _template_content(
    product_name: str,
    trend_keyword: str,
    category: str,
    benable_url: str,
    style: Optional[str] = None,
) -> dict:
    """Generate template-based content when Claude API is unavailable."""
    templates = {
        "home_decor": {
            "title": f"{product_name} — The Home Upgrade You Need Right Now",
            "description": (
                f"Obsessed with this {product_name}! It's giving major {trend_keyword} vibes "
                f"and completely transformed my space. Grab it here: {benable_url} ✨"
            ),
            "hashtags": [
                "homedecor", "homeaesthetic", "cozyhome", "interiordesign",
                "homefinds", "amazonfinds", "homeinspo", trend_keyword.replace(" ", ""),
            ],
        },
        "kitchen": {
            "title": f"This {product_name} Changed My Morning Routine",
            "description": (
                f"If you love {trend_keyword}, you NEED this {product_name} in your life. "
                f"Such a game changer! Find it here: {benable_url} ☕"
            ),
            "hashtags": [
                "kitchenfinds", "kitchenessentials", "homekitchen", "cookinglife",
                "amazonkitchen", "kitchenaesthetic", trend_keyword.replace(" ", ""),
            ],
        },
        "office": {
            "title": f"Work From Home Upgrade: {product_name}",
            "description": (
                f"Elevate your {trend_keyword} with this amazing {product_name}. "
                f"My desk has never looked better! Shop here: {benable_url} 💻"
            ),
            "hashtags": [
                "homeoffice", "desksetup", "workfromhome", "officeaesthetic",
                "deskorganization", "productivity", trend_keyword.replace(" ", ""),
            ],
        },
    }

    category_template = templates.get(
        category,
        {
            "title": f"{product_name} — A Must-Have Find",
            "description": (
                f"Loving this {product_name} for {trend_keyword}! "
                f"It's such a great find — check it out: {benable_url} 🛍️"
            ),
            "hashtags": [
                "amazonfinds", "musthaves", "productreview", "shopping",
                "lifestyle", "favorites", trend_keyword.replace(" ", ""),
            ],
        },
    )

    return {
        "title": category_template["title"],
        "description": category_template["description"],
        "hashtags": category_template["hashtags"],
        "style": style or "lifestyle",
    }
