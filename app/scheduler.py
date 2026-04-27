"""
Scheduler jobs:
  run_daily_pin_generation  — runs daily at 9 AM UTC
  schedule_approved_pins    — runs every 15 min, posts approved pins via Blotato

Flow (fully automated — no product pre-approval needed):
  1. Find trending Pinterest keywords per niche
  2. For each pin slot: pick keyword → search Amazon → fetch real product images
  3. Generate Pin Perfect Pro content (Claude) + pin image (Ideogram via fal.ai)
  4. Save pin as "pending" in dashboard → user approves/rejects
  5. On approval: products activate on shop pages + pin posts to Pinterest via Blotato
"""
import json
import logging
import random
import re
import uuid
import io
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

PINS_PER_DAY = 3   # 3 pins/day — safe for affiliate accounts

# One pin per niche per day
DAILY_NICHES = ["beauty", "home_decor", "fitness"]

# Daily content mix: 1 evergreen + 1 seasonal + 1 trending
# This ensures consistent income (evergreen), seasonal relevance, and trend momentum
DAILY_CONTENT_MIX = ["evergreen", "seasonal", "trending"]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN JOBS
# ══════════════════════════════════════════════════════════════════════════════

def run_daily_pin_generation():
    """
    Fully automated daily pin generation.
    Finds trending keywords → searches Amazon → fetches real product images
    → generates Ideogram pin → saves as pending for user approval.
    No pre-approved products required.
    """
    from app import db
    from app.models import Pin, TrendCache
    from config import Config

    logger.info("=== Daily pin generation started ===")

    # 1. Run keyword research (fills TrendCache)
    try:
        from app.keyword_research import run_keyword_research
        run_keyword_research()
    except Exception as e:
        logger.warning(f"Keyword research failed (non-fatal): {e}")

    # 2. Get trending keywords
    trends = _fetch_trends()
    if trends:
        _cache_trends(trends, db, TrendCache)

    # 3. Generate one pin per niche, rotating content types daily
    # Mix: today's niches paired with content types so every day has variety
    pins_created = 0
    today_idx = datetime.now(timezone.utc).weekday()  # 0=Mon … 6=Sun
    # Rotate content type assignment per niche so no niche always gets the same type
    for i, niche in enumerate(DAILY_NICHES):
        content_type = DAILY_CONTENT_MIX[(today_idx + i) % len(DAILY_CONTENT_MIX)]
        try:
            keyword = _pick_keyword_for_niche(niche, trends, content_type=content_type)
            logger.info(f"Pin {i+1}/{PINS_PER_DAY}: niche={niche}, type={content_type}, keyword='{keyword}'")
            success = _generate_pin_for_keyword(niche, keyword, db, Pin, Config, content_type=content_type)
            if success:
                pins_created += 1
        except Exception as e:
            logger.error(f"Pin generation for {niche} failed: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass

    logger.info(f"=== Daily generation complete: {pins_created}/{PINS_PER_DAY} pins created ===")


def schedule_approved_pins():
    """Post approved pins whose scheduled_for time has arrived (or immediately if unscheduled)."""
    from app import db
    from app.models import Pin

    now = datetime.now(timezone.utc)

    due = Pin.query.filter(
        Pin.status == Pin.STATUS_APPROVED,
        Pin.scheduled_for <= now,
    ).all()
    immediate = Pin.query.filter(
        Pin.status == Pin.STATUS_APPROVED,
        Pin.scheduled_for.is_(None),
    ).all()

    to_post = due + immediate
    if not to_post:
        return

    logger.info(f"Posting {len(to_post)} approved pins via Pinterest API…")
    for pin in to_post:
        try:
            _post_pin_pinterest(pin, db, now)
        except Exception as e:
            logger.error(f"Failed to post pin #{pin.id}: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# PIN GENERATION PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def _generate_pin_for_keyword(niche: str, keyword: str, db, Pin, Config, content_type: str = "evergreen") -> bool:
    """
    End-to-end pin generation for one keyword/niche:
      1. Search Amazon for top products
      2. Fetch real product images → GCS
      3. Generate Pin Perfect Pro content (Claude)
      4. Generate pin image (Ideogram Remix with real product images)
      5. Save Pin + Products to DB (pending)
    """
    from app.amazon_api import search_products
    from app.ai_writer import generate_pin_perfect_pro
    from app.imagen_api import generate_editorial_pin, generate_pin_perfect_pro_image
    from app.models import Product

    shop_url = Config.benable_url_for_niche(niche)

    # ── Step 1: Search Amazon for top products ────────────────────────────
    amazon_products = search_products(keyword, category=niche, max_results=4)
    if not amazon_products:
        logger.warning(f"No Amazon products found for '{keyword}' — skipping.")
        return False

    logger.info(f"Found {len(amazon_products)} products for '{keyword}'")

    # ── Step 2: Fetch real product images → GCS ───────────────────────────
    product_image_urls = []
    product_names = []
    fetched_products = []  # [{name, asin, amazon_url, image_url, price, category}]

    for p in amazon_products[:4]:
        name = p.get("name", "")
        asin = p.get("asin", "")
        img_url = p.get("image_url")

        if img_url:
            gcs_url = _download_and_upload_to_gcs(img_url, asin)
            if gcs_url:
                product_image_urls.append(gcs_url)
                p["gcs_image_url"] = gcs_url
            else:
                p["gcs_image_url"] = img_url  # use original if GCS fails
        else:
            p["gcs_image_url"] = None

        product_names.append(name)
        fetched_products.append(p)

    if not product_names:
        logger.warning(f"No product names available for '{keyword}' — skipping.")
        return False

    # ── Step 3: Generate Pin Perfect Pro content (Claude) ─────────────────
    ppp_result = generate_pin_perfect_pro(
        product_names=product_names,
        niche=niche,
        trend_keyword=keyword,
        shop_url=shop_url,
    )
    if not ppp_result or not ppp_result.get("title"):
        logger.error(f"Pin Perfect Pro content generation failed for '{keyword}'")
        return False

    logger.info(f"Pin Perfect Pro content generated: '{ppp_result['title']}'")

    # ── Step 4: Generate pin image (Ideogram Remix with real product images) ─
    image_url = None
    theme    = ppp_result.get("theme", keyword.upper()[:20])
    subtitle = ppp_result.get("subtitle", "on Amazon")

    if product_image_urls:
        # Real product photos → gpt-image-2 editorial pin (actual product, no catfishing)
        image_url = generate_editorial_pin(
            product_image_urls=product_image_urls,
            theme=theme,
            subtitle=subtitle,
            niche=niche,
            benefits=ppp_result.get("benefits") or [],
            product_name=product_names[0] if product_names else "",
        )

    if not image_url and ppp_result.get("image_prompt"):
        # Fallback: AI text-to-image when no real product images available
        image_url = generate_pin_perfect_pro_image(ppp_result["image_prompt"])

    pin_status = Pin.STATUS_PENDING if image_url else Pin.STATUS_NEEDS_IMAGE
    logger.info(f"Image generated: {image_url or 'FAILED'}")

    # ── Step 5: Save Products + Pin to DB ────────────────────────────────
    # Save products as inactive — they activate when the pin is approved
    product_records = []
    affiliate_tag = "auragirlcreat-20"
    for p in fetched_products:
        asin = p.get("asin", "")
        base_url = p.get("amazon_url", "")
        if asin and "tag=" not in base_url:
            base_url = f"https://www.amazon.com/dp/{asin}?tag={affiliate_tag}"

        # Don't duplicate products already in DB
        existing = None
        if asin:
            from app.models import Product as ProductModel
            existing = ProductModel.query.filter(
                ProductModel.amazon_url.contains(asin)
            ).first()

        if existing:
            product_records.append(existing)
        else:
            product = Product(
                name=p.get("name", "")[:255],
                amazon_url=base_url,
                benable_url=shop_url,
                category=niche,
                image_url=p.get("gcs_image_url") or p.get("image_url"),
                price=p.get("price"),
                is_active=False,  # inactive until pin is approved
                content_type=content_type,
            )
            db.session.add(product)
            db.session.flush()  # get the ID
            product_records.append(product)

    # Build hashtags string
    hashtags_raw = ppp_result.get("hashtags", "")
    if isinstance(hashtags_raw, str):
        hashtag_list = [h.strip().lstrip("#") for h in hashtags_raw.split(",") if h.strip()]
    else:
        hashtag_list = hashtags_raw

    pin = Pin(
        theme=ppp_result.get("theme", keyword.upper()[:30]),
        title=ppp_result.get("title", "")[:255],
        description=ppp_result.get("description", ""),
        hashtags=json.dumps(hashtag_list),
        image_url=image_url,
        status=pin_status,
        trend_keyword=keyword,
        style_variant="pin_perfect_pro",
        board_name=ppp_result.get("board_name", ""),
        alt_text=ppp_result.get("alt_text", ""),
        shop_url=shop_url,  # updated to /shop/pin/<id> after commit
    )
    pin.products = product_records
    db.session.add(pin)
    db.session.flush()  # get pin.id before commit

    # Update shop_url to the pin-specific landing page
    pin.shop_url = f"https://auragirlessentials.com/shop/pin/{pin.id}"
    db.session.commit()

    logger.info(
        f"  → Pin #{pin.id} created: '{pin.title[:50]}' "
        f"[{pin_status}] board='{pin.board_name}'"
    )
    return True


def _download_and_upload_to_gcs(image_url: str, identifier: str = "") -> Optional[str]:
    """Download a product image and upload to GCS. Returns GCS URL or None."""
    import requests as req
    GCS_BUCKET = "pinterest-automation-images-814656203168"
    GCS_BASE_URL = f"https://storage.googleapis.com/{GCS_BUCKET}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.amazon.com/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        resp = req.get(image_url, headers=headers, timeout=15)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "image/jpeg")
        ext = "jpg" if "jpeg" in content_type or "jpg" in image_url.lower() else "png"

        from google.cloud import storage as gcs_lib
        gcs_client = gcs_lib.Client()
        bucket = gcs_client.bucket(GCS_BUCKET)
        blob_name = f"product-refs/{identifier}_{uuid.uuid4().hex[:8]}.{ext}"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(resp.content, content_type=content_type)
        return f"{GCS_BASE_URL}/{blob_name}"

    except Exception as e:
        logger.warning(f"Could not fetch/upload product image {image_url}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# POSTING VIA PINTEREST API DIRECTLY
# ══════════════════════════════════════════════════════════════════════════════

# Peak posting times in UTC (7 PM, 8 PM, 9 PM EST = midnight, 1 AM, 2 AM UTC)
# Pinterest traffic peaks 8–11 PM EST — we spread pins across that window
PEAK_HOURS_UTC = [0, 1, 2]   # midnight, 1 AM, 2 AM UTC = 8, 9, 10 PM EST


def _next_peak_slot(now: datetime) -> datetime:
    """Return the next available peak posting time (8–10 PM EST = 0–2 AM UTC)."""
    from app.models import Pin

    # Try each peak hour today and tomorrow
    for day_offset in range(2):
        for hour in PEAK_HOURS_UTC:
            candidate = now.replace(
                hour=hour, minute=0, second=0, microsecond=0
            ) + timedelta(days=day_offset)
            if candidate <= now:
                continue
            # Check if a pin is already scheduled for that slot (within 30 min window)
            window_start = candidate - timedelta(minutes=15)
            window_end   = candidate + timedelta(minutes=15)
            conflict = Pin.query.filter(
                Pin.status.in_([Pin.STATUS_APPROVED, Pin.STATUS_POSTED]),
                Pin.scheduled_for >= window_start,
                Pin.scheduled_for <= window_end,
            ).first()
            if not conflict:
                return candidate

    # Fallback: 25 hours from now
    return now + timedelta(hours=25)


def _post_pin_pinterest(pin, db, now):
    """Post a pin to Pinterest directly via Pinterest API v5 and update DB status."""
    from app.models import Pin
    from app import pinterest_api

    if not pin.image_url:
        logger.error(f"Pin #{pin.id} has no image URL — cannot post.")
        return

    # Build full description with hashtags
    hashtag_str = " ".join(f"#{h}" for h in pin.hashtags_list())
    full_desc = pin.description or ""
    if hashtag_str:
        full_desc = f"{full_desc}\n\n{hashtag_str}"

    # Get board ID
    from config import Config
    board_name = pin.board_name or ""
    board_id = Config.PINTEREST_BOARDS.get(board_name)
    if not board_id:
        niche_boards = {
            "beauty":     Config.PINTEREST_BOARDS.get("Beauty Finds & Skincare"),
            "home_decor": Config.PINTEREST_BOARDS.get("Glam Home Decor Ideas"),
            "fitness":    Config.PINTEREST_BOARDS.get("Wellness & Self Care Essentials"),
        }
        categories = [p.category for p in pin.products if p.category]
        niche = max(set(categories), key=categories.count) if categories else "beauty"
        board_id = niche_boards.get(niche, Config.PINTEREST_BOARDS.get("Beauty Finds & Skincare"))

    if not board_id:
        logger.error(f"Pin #{pin.id}: no board ID found.")
        return

    link = pin.shop_url or Config.benable_url_for_niche("beauty")

    # Schedule for next peak slot if no schedule set
    publish_at = pin.scheduled_for or _next_peak_slot(now)

    try:
        result = pinterest_api.post_pin(
            title=pin.title or "",
            description=full_desc,
            image_url=pin.image_url,
            link=link,
            board_id=board_id,
            alt_text=pin.alt_text or "",
            publish_date=publish_at,
        )
        pin.status = Pin.STATUS_POSTED
        pin.posted_at = now
        pin.scheduled_for = publish_at
        pin.pinterest_pin_id = result.get("id", "")
        db.session.commit()
        logger.info(f"Pin #{pin.id} posted via Pinterest API ✓  board={board_id}  scheduled={publish_at.isoformat()}")
    except Exception as e:
        logger.error(f"Pinterest API post failed for pin #{pin.id}: {e}", exc_info=True)
        raise


# ══════════════════════════════════════════════════════════════════════════════
# KEYWORD HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_trends() -> list:
    try:
        from app.pinterest_trends_scraper import fetch_pinterest_trends
        trends = fetch_pinterest_trends()
        if trends:
            return trends
    except Exception as e:
        logger.warning(f"Pinterest scraper failed: {e}")

    try:
        from app.pinterest_api import get_trending_keywords
        return get_trending_keywords()
    except Exception as e:
        logger.warning(f"Pinterest API trends failed: {e}")
        return []


def _pick_keyword_for_niche(niche: str, trends: list, product_name: str = "", content_type: str = "evergreen") -> str:
    """
    Pick the best Pinterest keyword for a niche + product combination.
    Uses product name for relevance matching against TrendCache.
    content_type: 'evergreen' | 'seasonal' | 'trending'
    """
    # Use smart product-aware picker if we have a product name
    if product_name:
        try:
            from app.keyword_research import pick_best_keyword_for_product
            kw = pick_best_keyword_for_product(product_name, niche, content_type)
            if kw:
                return kw
        except Exception as e:
            logger.warning(f"pick_best_keyword_for_product failed: {e}")

    # Fallback: pull from TrendCache by niche
    try:
        from app.keyword_research import get_top_keywords_for_niche
        cached = get_top_keywords_for_niche(niche, limit=10)
        if cached:
            return random.choice(cached[:5])
    except Exception:
        pass

    # Last resort: hardcoded buying-intent fallbacks
    fallbacks = {
        "beauty":     ["press on nails amazon 2026", "affordable skincare routine amazon", "lip gloss set amazon finds"],
        "home_decor": ["aesthetic home decor amazon finds", "cozy room decor ideas amazon", "glam home decor under 30"],
        "fitness":    ["self care products amazon finds", "wellness supplements amazon women", "collagen amazon glow up"],
    }
    return random.choice(fallbacks.get(niche, ["amazon finds 2026"]))


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
