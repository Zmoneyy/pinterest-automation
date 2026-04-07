"""
Daily automation scheduler jobs.
- run_daily_pin_generation: Fetches trends, picks products, generates pins (runs at 9 AM UTC)
- schedule_approved_pins: Posts approved pins that are due (runs every 15 min)
"""
import json
import logging
import random
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

IMAGE_STYLES = ["lifestyle", "flat_lay", "product_hero", "aesthetic_room", "outdoor"]

CATEGORY_KEYWORD_MAP = {
    "home_decor": ["home_decor", "general"],
    "kitchen": ["kitchen", "general"],
    "office": ["office", "general"],
    "fashion": ["fashion", "general"],
    "beauty": ["beauty", "general"],
    "fitness": ["fitness", "general"],
    "travel": ["travel", "general"],
    "garden": ["garden", "general"],
    "pets": ["pets", "general"],
    "tech": ["tech", "general"],
    "art": ["art", "diy", "general"],
}


def run_daily_pin_generation():
    """
    Main daily job: fetch trends, pick products, generate images + content,
    and create pending Pin records for human approval.
    Targets 3 new pins per run.
    """
    from app import db
    from app.ai_writer import generate_pin_content
    from app.imagen_api import generate_pin_image
    from app.models import Pin, Product, TrendCache
    from app.pinterest_api import get_trending_keywords

    logger.info("=== Starting daily pin generation ===")

    # 1. Fetch trending keywords and cache them
    trends = get_trending_keywords()
    if trends:
        _cache_trends(trends, db, TrendCache)

    # 2. Get all active products
    active_products = Product.query.filter_by(is_active=True).all()
    if not active_products:
        logger.warning("No active products found. Skipping pin generation.")
        return

    # 3. Pick up to 3 products (prefer variety, avoid recently-pinned ones)
    products_to_pin = _select_products(active_products, count=3)
    logger.info(f"Selected {len(products_to_pin)} products for today's pins.")

    pins_created = 0
    for product in products_to_pin:
        try:
            # Pick a relevant trending keyword for this product
            trend_keyword = _pick_trend_for_product(product.category, trends)

            # Pick a random image style
            style = random.choice(IMAGE_STYLES)

            # Generate image with Imagen
            logger.info(f"Generating image for '{product.name}' (style: {style})...")
            image_path = generate_pin_image(
                prompt=f"{trend_keyword} inspired, featuring {product.name}",
                product_name=product.name,
                style=style,
            )

            # Determine pin status based on image generation success
            pin_status = Pin.STATUS_PENDING
            if not image_path:
                logger.warning(f"Image generation failed for '{product.name}'. Marking needs_image.")
                pin_status = Pin.STATUS_NEEDS_IMAGE

            # Generate content with Claude
            logger.info(f"Generating content for '{product.name}'...")
            content = generate_pin_content(
                product_name=product.name,
                trend_keyword=trend_keyword,
                category=product.category,
                benable_url=product.benable_url,
            )

            # Create Pin record
            pin = Pin(
                product_id=product.id,
                title=content["title"],
                description=content["description"],
                hashtags=json.dumps(content.get("hashtags", [])),
                image_path=image_path,
                image_url=None,  # Will be set when posted
                status=pin_status,
                trend_keyword=trend_keyword,
                style_variant=content.get("style", style),
            )
            db.session.add(pin)
            db.session.commit()

            pins_created += 1
            logger.info(f"Created pin #{pin.id} for '{product.name}' [{pin_status}]")

        except Exception as e:
            logger.error(f"Failed to generate pin for '{product.name}': {e}", exc_info=True)
            db.session.rollback()
            continue

    logger.info(f"=== Daily pin generation complete: {pins_created} pins created ===")


def schedule_approved_pins():
    """
    Check for approved pins with a scheduled_for time that has passed,
    and post them to Pinterest.
    Also posts approved pins without a schedule (immediate posting).
    """
    from datetime import timedelta

    from app import db
    from app.models import Pin
    from app.pinterest_api import post_pin

    now = datetime.now(timezone.utc)
    logger.info("Checking for pins ready to post...")

    # Find approved pins that are scheduled and due
    due_pins = Pin.query.filter(
        Pin.status == Pin.STATUS_APPROVED,
        Pin.scheduled_for <= now,
    ).all()

    # Also find approved pins with no schedule set (post immediately)
    unscheduled_approved = Pin.query.filter(
        Pin.status == Pin.STATUS_APPROVED,
        Pin.scheduled_for.is_(None),
    ).all()

    pins_to_post = due_pins + unscheduled_approved

    if not pins_to_post:
        logger.info("No pins ready to post.")
        return

    logger.info(f"Found {len(pins_to_post)} pins ready to post.")

    for pin in pins_to_post:
        try:
            _post_single_pin(pin, db, post_pin, now)
        except Exception as e:
            logger.error(f"Failed to post pin #{pin.id}: {e}", exc_info=True)
            db.session.rollback()


def _post_single_pin(pin, db, post_pin_fn, now):
    """Post a single pin to Pinterest and update its status."""
    from app.imagen_api import image_path_to_url

    product = pin.product
    if not product:
        logger.error(f"Pin #{pin.id} has no associated product. Skipping.")
        return

    # Determine the image URL to use
    image_url = pin.image_url
    if not image_url and pin.image_path:
        # We need a publicly accessible URL — for Cloud Run, this would be a GCS URL.
        # Here we use the Flask serve route as a fallback.
        from config import Config
        base_url = f"http://localhost:{Config.PORT}"
        image_url = image_path_to_url(pin.image_path, base_url)

    if not image_url:
        logger.error(f"Pin #{pin.id} has no image URL. Cannot post.")
        return

    # Build full description with hashtags
    hashtags = pin.hashtags_list()
    hashtag_str = " ".join(f"#{h}" for h in hashtags) if hashtags else ""
    full_description = pin.description
    if hashtag_str:
        full_description = f"{full_description}\n\n{hashtag_str}"

    # Post to Pinterest
    result = post_pin_fn(
        title=pin.title,
        description=full_description,
        image_url=image_url,
        link=product.benable_url,
        alt_text=f"{product.name} - {pin.trend_keyword or ''}".strip(" -"),
    )

    # Update pin record
    pin.status = Pin.STATUS_POSTED
    pin.posted_at = now
    pin.pinterest_pin_id = result.get("id", "")
    pin.image_url = image_url
    db.session.commit()

    logger.info(f"Pin #{pin.id} posted to Pinterest as '{result.get('id')}' ✓")


def _select_products(products: list, count: int = 3) -> list:
    """
    Select products to generate pins for today.
    Tries to pick products that haven't been pinned recently.
    Falls back to random selection.
    """
    from app.models import Pin

    # Find recently posted product IDs (last 7 days)
    from datetime import timedelta
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent_product_ids = {
        p.product_id
        for p in Pin.query.filter(
            Pin.posted_at >= recent_cutoff,
            Pin.status == Pin.STATUS_POSTED,
        ).all()
    }

    # Prefer products not recently posted
    fresh_products = [p for p in products if p.id not in recent_product_ids]
    stale_products = [p for p in products if p.id in recent_product_ids]

    pool = fresh_products if fresh_products else stale_products
    selected = random.sample(pool, min(count, len(pool)))

    # If we still need more, top up from stale
    if len(selected) < count and stale_products:
        remaining = [p for p in stale_products if p not in selected]
        selected += random.sample(remaining, min(count - len(selected), len(remaining)))

    return selected


def _pick_trend_for_product(category: str, trends: list[dict]) -> str:
    """Pick a trending keyword most relevant to the product's category."""
    if not trends:
        return "trending finds"

    # Filter to matching category trends
    category_match = CATEGORY_KEYWORD_MAP.get(category, ["general"])
    relevant = [t for t in trends if t.get("category") in category_match]

    if relevant:
        # Sort by score and pick from top 5 randomly
        relevant.sort(key=lambda x: x.get("score", 0), reverse=True)
        top = relevant[:5]
        return random.choice(top)["keyword"]

    # Fall back to any trend
    top = sorted(trends, key=lambda x: x.get("score", 0), reverse=True)[:5]
    return random.choice(top)["keyword"] if top else "lifestyle finds"


def _cache_trends(trends: list[dict], db, TrendCache):
    """Store fetched trends in the database cache."""
    try:
        # Clear old cache
        TrendCache.query.delete()

        for trend in trends:
            cached = TrendCache(
                keyword=trend["keyword"],
                category=trend.get("category", "general"),
                score=trend.get("score", 0),
            )
            db.session.add(cached)

        db.session.commit()
        logger.info(f"Cached {len(trends)} trend keywords to database.")
    except Exception as e:
        logger.error(f"Failed to cache trends: {e}")
        db.session.rollback()
