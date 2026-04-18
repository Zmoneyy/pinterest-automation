"""
Scheduler jobs:
  run_daily_pin_generation  — runs daily at 9 AM UTC
  schedule_approved_pins    — runs every 15 min, posts approved pins that are due
"""
import json
import logging
import random
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MIN_PRODUCTS_PER_PIN = 5
MAX_PRODUCTS_PER_PIN = 8
PINS_PER_DAY = 3


def run_daily_pin_generation():
    """
    Generate 3 collage-style roundup pins per day.
    Each pin features 5-8 curated products under a themed headline.
    """
    from app import db
    from app.ai_writer import generate_roundup_content
    from app.imagen_api import generate_collage_image
    from app.models import Pin, Product, ProductCandidate, TrendCache
    from app.pinterest_api import get_trending_keywords
    from config import Config

    logger.info("=== Daily pin generation started ===")

    # 1. Run full keyword research (autocomplete + trends + seasonal) → caches to TrendCache
    try:
        from app.keyword_research import run_keyword_research
        run_keyword_research()
        logger.info("Keyword research complete.")
    except Exception as e:
        logger.error(f"Keyword research failed (non-fatal): {e}", exc_info=True)

    # 2. Fetch trending keywords — Pinterest session scraper first, then fallback
    from app.pinterest_trends_scraper import fetch_pinterest_trends
    trends = fetch_pinterest_trends()
    if not trends:
        logger.info("Pinterest session scrape empty — falling back to Pinterest API / SerpAPI.")
        trends = get_trending_keywords()
    if trends:
        _cache_trends(trends, db, TrendCache)

    # 2. Auto-discover new products (trending + evergreen) into approval queue
    _auto_discover_products(db, ProductCandidate, trends)

    # 3. Pull all active products, grouped by category
    all_products = Product.query.filter_by(is_active=True).all()
    if len(all_products) < 3:
        logger.warning(
            f"Only {len(all_products)} active products. Need at least 3. Skipping generation."
        )
        return

    # Group products by the 3 core niches
    CORE_NICHES = ["beauty", "home_decor", "fitness"]
    by_category: dict = {}
    for p in all_products:
        cat = p.category if p.category in CORE_NICHES else "beauty"
        by_category.setdefault(cat, []).append(p)

    # Only use categories with enough products for a pin
    viable_categories = [
        (cat, by_category[cat]) for cat in CORE_NICHES
        if cat in by_category and len(by_category[cat]) >= MIN_PRODUCTS_PER_PIN
    ]

    # Fall back to all products if no single category has enough
    if not viable_categories:
        logger.warning("No niche has 5+ products — using all products.")
        viable_categories = [("mixed", all_products)]

    pins_created = 0
    for i in range(PINS_PER_DAY):
        try:
            # Rotate through viable categories
            category, category_products = viable_categories[i % len(viable_categories)]
            _generate_one_collage_pin(i, category_products, trends, db, Pin,
                                       generate_roundup_content, generate_collage_image, Config)
            pins_created += 1
        except Exception as e:
            logger.error(f"Pin generation #{i + 1} failed: {e}", exc_info=True)
            db.session.rollback()

    logger.info(f"=== Daily generation complete: {pins_created}/{PINS_PER_DAY} pins created ===")


def _generate_one_collage_pin(
    index: int,
    all_products: list,
    trends: list,
    db,
    Pin,
    generate_roundup_content,
    generate_collage_image,
    Config,
):
    """Generate a single collage pin featuring 5-8 randomly selected products."""
    # How many products for this pin
    count = random.randint(
        min(MIN_PRODUCTS_PER_PIN, len(all_products)),
        min(MAX_PRODUCTS_PER_PIN, len(all_products)),
    )
    products = random.sample(all_products, count)

    # Pick a trending keyword relevant to the product mix
    trend_keyword = _pick_trend_keyword(products, trends)
    logger.info(
        f"Pin {index + 1}: {count} products, trend='{trend_keyword}'"
    )

    # Generate content (theme title, subtitle, description, hashtags, CTA)
    content = generate_roundup_content(
        products=products,
        trend_keyword=trend_keyword,
        benable_url=Config.BENABLE_URL or "https://benable.com",
    )

    # Generate collage image
    image_path = generate_collage_image(
        products=products,
        theme=content["theme"],
        subtitle=content.get("subtitle", "on Amazon"),
        brand_name=Config.BRAND_NAME or "",
        cta_text=content.get("cta_text", "shop here \u2764\ufe0f"),
    )

    # generate_collage_image returns a GCS URL or local path
    is_url = image_path and image_path.startswith("http")
    pin_status = Pin.STATUS_PENDING if image_path else Pin.STATUS_NEEDS_IMAGE

    pin = Pin(
        theme=content["theme"],
        title=content["title"],
        description=content["description"],
        hashtags=json.dumps(content.get("hashtags", [])),
        image_path=None if is_url else image_path,
        image_url=image_path if is_url else None,
        status=pin_status,
        trend_keyword=trend_keyword,
        style_variant="roundup_collage",
    )
    pin.products = products
    db.session.add(pin)
    db.session.commit()

    logger.info(
        f"  → Pin #{pin.id} created: '{pin.theme}' [{pin_status}] "
        f"({len(products)} products)"
    )


def schedule_approved_pins():
    """Post approved pins whose scheduled_for time has arrived (or immediately if unscheduled)."""
    from app import db
    from app.models import Pin
    from app.pinterest_api import post_pin

    now = datetime.now(timezone.utc)

    due_pins = Pin.query.filter(
        Pin.status == Pin.STATUS_APPROVED,
        Pin.scheduled_for <= now,
    ).all()

    immediate_pins = Pin.query.filter(
        Pin.status == Pin.STATUS_APPROVED,
        Pin.scheduled_for.is_(None),
    ).all()

    to_post = due_pins + immediate_pins
    if not to_post:
        return

    logger.info(f"Posting {len(to_post)} approved pins...")
    for pin in to_post:
        try:
            _post_pin(pin, db, post_pin, now)
        except Exception as e:
            logger.error(f"Failed to post pin #{pin.id}: {e}", exc_info=True)
            db.session.rollback()


def _post_pin(pin, db, post_pin_fn, now):
    """Post a single pin to Pinterest and update DB status."""
    from app.imagen_api import image_path_to_url
    from config import Config

    image_url = pin.image_url
    if not image_url and pin.image_path:
        base_url  = f"http://localhost:{Config.PORT}"
        image_url = image_path_to_url(pin.image_path, base_url)

    if not image_url:
        logger.error(f"Pin #{pin.id} has no image URL — skipping.")
        return

    # Build description with hashtags
    hashtag_str  = " ".join(f"#{h}" for h in pin.hashtags_list())
    full_desc    = pin.description
    if hashtag_str:
        full_desc = f"{full_desc}\n\n{hashtag_str}"

    # For collage pins link to the main Benable page (multiple products)
    link = Config.BENABLE_URL or "https://benable.com"

    result = post_pin_fn(
        title=pin.title,
        description=full_desc,
        image_url=image_url,
        link=link,
        alt_text=f"{pin.theme} — curated finds",
    )

    pin.status          = Pin.STATUS_POSTED
    pin.posted_at       = now
    pin.pinterest_pin_id = result.get("id", "")
    pin.image_url       = image_url
    db.session.commit()
    logger.info(f"Pin #{pin.id} posted ✓  (pinterest id: {pin.pinterest_pin_id})")


def _pick_trend_keyword(products: list, trends: list) -> str:
    """
    Pick the best trending keyword for the product mix.
    Priority: keyword research cache (TrendCache) → session trends → fallback.
    """
    # Determine dominant category from products
    cat_counts: dict = {}
    for p in products:
        cat_counts[p.category] = cat_counts.get(p.category, 0) + 1
    dominant_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "beauty"

    # 1. Try keyword research cache first (highest quality — real Pinterest searches)
    try:
        from app.keyword_research import get_top_keywords_for_niche
        cached = get_top_keywords_for_niche(dominant_cat, limit=10)
        if cached:
            return random.choice(cached[:5])
    except Exception:
        pass

    # 2. Fall back to session/API trends list
    if not trends:
        return "amazon finds"

    category_map = {
        "home_decor": ["home_decor", "general"],
        "kitchen":    ["kitchen", "general"],
        "office":     ["office", "general"],
        "fashion":    ["fashion", "general"],
        "beauty":     ["beauty", "general"],
        "fitness":    ["fitness", "general"],
        "travel":     ["travel", "general"],
        "garden":     ["garden", "general"],
        "pets":       ["pets", "general"],
        "tech":       ["tech", "general"],
        "art":        ["art", "diy", "general"],
    }
    target_cats = category_map.get(dominant_cat, ["general"])
    relevant    = [t for t in trends if t.get("category") in target_cats]
    pool        = relevant[:5] or sorted(trends, key=lambda x: x.get("score", 0), reverse=True)[:5]

    return random.choice(pool)["keyword"] if pool else "lifestyle finds"


def _auto_discover_products(db, ProductCandidate, trends: list):
    """
    Auto-discover products daily: trending keywords + evergreen categories.
    Adds new candidates to approval queue (user still approves before they go into pins).
    """
    try:
        from app.amazon_api import discover_evergreen_products, discover_products_for_trends

        all_candidates = []

        # Trending products (top 3 trends only to save API calls)
        if trends:
            top_trends = sorted(trends, key=lambda x: x.get("score", 0), reverse=True)[:3]
            trend_candidates = discover_products_for_trends(top_trends, per_trend=3)
            all_candidates.extend(trend_candidates)

        # Evergreen products (rotates through all categories)
        evergreen = discover_evergreen_products(per_query=3)
        all_candidates.extend(evergreen)

        added = 0
        for c in all_candidates:
            asin = c.get("asin")
            if asin:
                exists = ProductCandidate.query.filter_by(asin=asin).first()
                if not exists:
                    from app.models import Product
                    exists = Product.query.filter(Product.amazon_url.contains(asin)).first()
            else:
                exists = ProductCandidate.query.filter_by(name=c["name"]).first()

            if exists:
                continue

            db.session.add(ProductCandidate(
                name=c["name"],
                asin=asin,
                amazon_url=c["amazon_url"],
                category=c.get("category", "general"),
                image_url=c.get("image_url"),
                price=c.get("price"),
                trend_keyword=c.get("trend_keyword"),
                status=ProductCandidate.STATUS_PENDING,
            ))
            added += 1

        db.session.commit()
        logger.info(f"Auto-discovery: added {added} new products to approval queue.")
    except Exception as e:
        logger.error(f"Auto product discovery failed: {e}", exc_info=True)
        try:
            db.session.rollback()
        except Exception:
            pass


def _cache_trends(trends: list, db, TrendCache):
    try:
        TrendCache.query.delete()
        for t in trends:
            db.session.add(TrendCache(
                keyword=t["keyword"],
                category=t.get("category", "general"),
                score=t.get("score", 0),
            ))
        db.session.commit()
        logger.info(f"Cached {len(trends)} trends.")
    except Exception as e:
        logger.error(f"Trend caching failed: {e}")
        db.session.rollback()
