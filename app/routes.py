"""
Flask routes: auth, dashboard, products, API, Pinterest OAuth.
Updated for collage/roundup pins (Pin.products is now a list, not a single FK).
"""
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from app import db
from app.models import Pin, Product, ProductCandidate, Setting, TrendCache

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


# ── Auth helpers ──────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("main.login"))
        return f(*args, **kwargs)
    return decorated


# ── Auth routes ───────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return redirect(url_for("main.dashboard"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    from config import Config
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if not Config.DASHBOARD_PASSWORD or password == Config.DASHBOARD_PASSWORD:
            session["logged_in"] = True
            session.permanent   = True
            return redirect(url_for("main.dashboard"))
        error = "Incorrect password. Please try again."
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ── Static image serving ──────────────────────────────────────────────────

@bp.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory("/tmp/generated_images", filename)


# ── Dashboard ─────────────────────────────────────────────────────────────

@bp.route("/dashboard")
@login_required
def dashboard():
    status_filter = request.args.get("status", "pending")

    pending_pins = (
        Pin.query.filter(Pin.status.in_([Pin.STATUS_PENDING, Pin.STATUS_NEEDS_IMAGE]))
        .order_by(Pin.created_at.desc()).all()
    )
    approved_pins = (
        Pin.query.filter_by(status=Pin.STATUS_APPROVED)
        .order_by(Pin.scheduled_for.asc().nulls_last(), Pin.created_at.desc()).all()
    )
    posted_pins = (
        Pin.query.filter_by(status=Pin.STATUS_POSTED)
        .order_by(Pin.posted_at.desc()).limit(30).all()
    )
    rejected_pins = (
        Pin.query.filter_by(status=Pin.STATUS_REJECTED)
        .order_by(Pin.created_at.desc()).limit(20).all()
    )

    return render_template(
        "dashboard.html",
        pending_pins=pending_pins,
        approved_pins=approved_pins,
        posted_pins=posted_pins,
        rejected_pins=rejected_pins,
        active_tab=status_filter,
        now=datetime.now(timezone.utc),
    )


@bp.route("/pin/<int:pin_id>/approve", methods=["POST"])
@login_required
def approve_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    scheduled_str = request.form.get("scheduled_for", "").strip()
    if scheduled_str:
        try:
            scheduled_for = datetime.fromisoformat(scheduled_str)
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
            pin.scheduled_for = scheduled_for
        except ValueError:
            pin.scheduled_for = None
    else:
        pin.scheduled_for = None

    pin.status = Pin.STATUS_APPROVED
    db.session.commit()
    logger.info(f"Pin #{pin_id} approved (scheduled: {pin.scheduled_for})")
    return redirect(url_for("main.dashboard"))


@bp.route("/pin/<int:pin_id>/reject", methods=["POST"])
@login_required
def reject_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    pin.status = Pin.STATUS_REJECTED
    db.session.commit()
    return redirect(url_for("main.dashboard"))


@bp.route("/pin/<int:pin_id>/swap", methods=["POST"])
@login_required
def swap_pin(pin_id):
    """
    Regenerate the collage with a fresh selection of products.
    Keeps the same trend keyword but picks a new random product set.
    """
    import random as rnd

    from app.ai_writer import generate_roundup_content
    from app.imagen_api import generate_collage_image
    from config import Config

    pin = Pin.query.get_or_404(pin_id)
    active_products = Product.query.filter_by(is_active=True).all()

    if not active_products:
        return redirect(url_for("main.dashboard"))

    count = rnd.randint(
        min(5, len(active_products)),
        min(8, len(active_products)),
    )
    new_products = rnd.sample(active_products, count)

    try:
        content = generate_roundup_content(
            products=new_products,
            trend_keyword=pin.trend_keyword or "amazon finds",
            benable_url=Config.BENABLE_URL or "https://benable.com",
        )

        image_path = generate_collage_image(
            products=new_products,
            theme=content["theme"],
            subtitle=content.get("subtitle", "on Amazon"),
            brand_name=Config.BRAND_NAME or "",
            cta_text=content.get("cta_text", "shop here \u2764\ufe0f"),
        )

        is_url = image_path and image_path.startswith("http")
        pin.theme        = content["theme"]
        pin.title        = content["title"]
        pin.description  = content["description"]
        pin.hashtags     = json.dumps(content.get("hashtags", []))
        pin.products     = new_products
        pin.status       = Pin.STATUS_PENDING if image_path else Pin.STATUS_NEEDS_IMAGE
        pin.image_path   = None if is_url else image_path
        pin.image_url    = image_path if is_url else None
        pin.scheduled_for = None

        db.session.commit()
        logger.info(f"Pin #{pin_id} swapped with {len(new_products)} new products.")

    except Exception as e:
        logger.error(f"Swap failed for pin #{pin_id}: {e}", exc_info=True)
        db.session.rollback()

    return redirect(url_for("main.dashboard"))


@bp.route("/pins/approve_all", methods=["POST"])
@login_required
def approve_all_pending():
    pending = Pin.query.filter(
        Pin.status.in_([Pin.STATUS_PENDING, Pin.STATUS_NEEDS_IMAGE])
    ).all()
    for pin in pending:
        pin.status = Pin.STATUS_APPROVED
    db.session.commit()
    logger.info(f"Bulk approved {len(pending)} pins.")
    return redirect(url_for("main.dashboard"))


@bp.route("/pins/clear-pending", methods=["POST"])
def clear_pending_pins():
    """Delete all pending pins in bulk."""
    pending = Pin.query.filter(
        Pin.status.in_([Pin.STATUS_PENDING, Pin.STATUS_NEEDS_IMAGE])
    ).all()
    count = len(pending)
    for pin in pending:
        db.session.delete(pin)
    db.session.commit()
    logger.info(f"Bulk deleted {count} pending pins.")
    return redirect(url_for("main.dashboard"))


# ── Products ──────────────────────────────────────────────────────────────

VALID_CATEGORIES = [
    "home_decor", "kitchen", "office", "fashion", "beauty",
    "fitness", "travel", "garden", "pets", "tech", "art", "general",
]


@bp.route("/products")
@login_required
def products():
    all_products = Product.query.order_by(Product.added_at.desc()).all()
    return render_template("products.html", products=all_products, categories=VALID_CATEGORIES)


@bp.route("/products/add", methods=["POST"])
@login_required
def add_product():
    name        = request.form.get("name", "").strip()
    amazon_url  = request.form.get("amazon_url", "").strip()
    benable_url = request.form.get("benable_url", "").strip()
    image_url   = request.form.get("image_url", "").strip()
    category    = request.form.get("category", "general").strip()
    price       = request.form.get("price", "").strip()

    if not name or not amazon_url or not benable_url:
        return redirect(url_for("main.products") + "?error=missing_fields")

    if category not in VALID_CATEGORIES:
        category = "general"

    product = Product(
        name=name,
        amazon_url=amazon_url,
        benable_url=benable_url,
        image_url=image_url or None,
        category=category,
        price=price or None,
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    logger.info(f"Added product: {name}")
    return redirect(url_for("main.products"))


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@login_required
def toggle_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_active = not product.is_active
    db.session.commit()
    return redirect(url_for("main.products"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    if product.pins:
        product.is_active = False
    else:
        db.session.delete(product)
    db.session.commit()
    return redirect(url_for("main.products"))


# ── Product discovery (Amazon PA API) ────────────────────────────────────

@bp.route("/products/queue")
@login_required
def product_queue():
    pending   = ProductCandidate.query.filter_by(status=ProductCandidate.STATUS_PENDING).order_by(ProductCandidate.discovered_at.desc()).all()
    approved  = ProductCandidate.query.filter_by(status=ProductCandidate.STATUS_APPROVED).order_by(ProductCandidate.discovered_at.desc()).limit(20).all()
    rejected  = ProductCandidate.query.filter_by(status=ProductCandidate.STATUS_REJECTED).order_by(ProductCandidate.discovered_at.desc()).limit(20).all()
    return render_template("approval_queue.html", pending=pending, approved=approved, rejected=rejected)


@bp.route("/products/discover", methods=["POST"])
@login_required
def discover_products():
    """Search Amazon for products based on top saved trends and add to approval queue."""
    from app.amazon_api import discover_products_for_trends
    from config import Config

    if not Config.SERP_API_KEY:
        return redirect(url_for("main.product_queue") + "?error=no_amazon_credentials")

    # Allow manual keyword search from the form
    manual_keyword = request.form.get("keyword", "").strip()
    if manual_keyword:
        trend_dicts = [{"keyword": manual_keyword, "category": "general"}]
    else:
        # Use top 5 saved trends
        top_trends = TrendCache.query.order_by(TrendCache.score.desc()).limit(5).all()
        if not top_trends:
            return redirect(url_for("main.product_queue") + "?error=no_trends")
        trend_dicts = [{"keyword": t.keyword, "category": t.category} for t in top_trends]

    candidates  = discover_products_for_trends(trend_dicts, per_trend=5)

    added = 0
    for c in candidates:
        # Skip if we already have this ASIN in queue or active products
        if c.get("asin"):
            already = ProductCandidate.query.filter_by(asin=c["asin"]).first()
            if not already:
                already = Product.query.filter(Product.amazon_url.contains(c["asin"])).first()
            if already:
                continue
        else:
            # No ASIN — deduplicate by name
            already = ProductCandidate.query.filter_by(name=c["name"]).first()
            if not already:
                already = Product.query.filter_by(name=c["name"]).first()
            if already:
                continue

        db.session.add(ProductCandidate(
            name=c["name"],
            asin=c.get("asin"),
            amazon_url=c["amazon_url"],
            category=c.get("category", "general"),
            image_url=c.get("image_url"),
            price=c.get("price"),
            trend_keyword=c.get("trend_keyword"),
            status=ProductCandidate.STATUS_PENDING,
        ))
        added += 1

    db.session.commit()
    logger.info(f"Product discovery: added {added} new candidates to approval queue")
    return redirect(url_for("main.product_queue") + f"?added={added}")


@bp.route("/products/queue/<int:candidate_id>/approve", methods=["POST"])
@login_required
def approve_candidate(candidate_id):
    from config import Config
    candidate = ProductCandidate.query.get_or_404(candidate_id)

    product = Product(
        name=candidate.name,
        amazon_url=candidate.amazon_url,
        benable_url=Config.BENABLE_URL or "https://benable.com",
        category=candidate.category or "general",
        image_url=candidate.image_url,
        price=candidate.price,
        is_active=True,
    )
    db.session.add(product)
    candidate.status = ProductCandidate.STATUS_APPROVED
    db.session.commit()
    return redirect(url_for("main.product_queue"))


@bp.route("/products/queue/<int:candidate_id>/reject", methods=["POST"])
@login_required
def reject_candidate(candidate_id):
    candidate = ProductCandidate.query.get_or_404(candidate_id)
    candidate.status = ProductCandidate.STATUS_REJECTED
    db.session.commit()
    return redirect(url_for("main.product_queue"))


@bp.route("/products/queue/<int:candidate_id>/undo", methods=["POST"])
@login_required
def undo_candidate(candidate_id):
    """Undo an approval — remove the Product record and put candidate back to pending."""
    candidate = ProductCandidate.query.get_or_404(candidate_id)
    if candidate.asin:
        product = Product.query.filter(Product.amazon_url.contains(candidate.asin)).first()
        if product:
            db.session.delete(product)
    candidate.status = ProductCandidate.STATUS_PENDING
    db.session.commit()
    return redirect(url_for("main.product_queue"))


@bp.route("/products/queue/approve-all", methods=["POST"])
@login_required
def approve_all_candidates():
    from config import Config
    pending = ProductCandidate.query.filter_by(status=ProductCandidate.STATUS_PENDING).all()
    for candidate in pending:
        product = Product(
            name=candidate.name,
            amazon_url=candidate.amazon_url,
            benable_url=Config.BENABLE_URL or "https://benable.com",
            category=candidate.category or "general",
            image_url=candidate.image_url,
            price=candidate.price,
            is_active=True,
        )
        db.session.add(product)
        candidate.status = ProductCandidate.STATUS_APPROVED
    db.session.commit()
    return redirect(url_for("main.product_queue"))


# ── Setup wizard ──────────────────────────────────────────────────────────

@bp.route("/setup")
@login_required
def setup():
    from config import Config
    config_status = Config.is_configured()

    pinterest_user = None
    try:
        from app.pinterest_api import get_user_info
        pinterest_user = get_user_info()
    except Exception:
        pass

    boards = []
    try:
        from app.pinterest_api import get_boards
        boards = get_boards()
    except Exception:
        pass

    trend_count  = TrendCache.query.count()
    latest_trend = TrendCache.query.order_by(TrendCache.cached_at.desc()).first()

    # Pinterest session cookie status
    cookie_status = {"status": "missing", "message": "No cookie stored"}
    try:
        from app.pinterest_trends_scraper import check_cookie_status
        cookie_status = check_cookie_status()
    except Exception:
        pass

    stored_cookie = Setting.get("pinterest_session_cookie", "")

    return render_template(
        "setup.html",
        config_status=config_status,
        pinterest_user=pinterest_user,
        boards=boards,
        trend_count=trend_count,
        latest_trend=latest_trend,
        cookie_status=cookie_status,
        stored_cookie=stored_cookie,
    )


# ── Pinterest session cookie ──────────────────────────────────────────────

@bp.route("/setup/pinterest-cookie", methods=["POST"])
@login_required
def save_pinterest_cookie():
    cookie = request.form.get("pinterest_session_cookie", "").strip()
    if cookie:
        Setting.set("pinterest_session_cookie", cookie)
        logger.info("Pinterest session cookie updated.")
    return redirect(url_for("main.setup"))


@bp.route("/api/shopping-trends")
@login_required
def api_shopping_trends():
    """Return Pinterest Shopping Trends (product categories ranked by outbound clicks)."""
    try:
        from app.pinterest_trends_scraper import _get_session_cookies, HEADERS, PINTEREST_TRENDS_URL
        import requests as _requests, json as _json, datetime as _dt

        cookies = _get_session_cookies()
        if not cookies:
            return jsonify({"ok": False, "error": "No cookie stored"})

        params = {
            "source_url": "/shopping/?country=US",
            "data": _json.dumps({
                "options": {"url": "/ads/v4/trends/shopping/product_categories", "data": {}},
                "context": {}
            }),
            "_": str(int(_dt.datetime.now().timestamp() * 1000)),
        }

        resp = _requests.get(PINTEREST_TRENDS_URL, headers=HEADERS, cookies=cookies, params=params, timeout=15)
        raw = resp.json()
        resource_data = raw.get("resource_response", {}).get("data")
        return jsonify({"ok": True, "status": resp.status_code, "type": type(resource_data).__name__, "data": resource_data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/refresh-trends", methods=["POST"])
@login_required
def refresh_trends():
    try:
        from app.pinterest_trends_scraper import fetch_pinterest_trends
        trends = fetch_pinterest_trends()
        if trends:
            return jsonify({"ok": True, "count": len(trends), "message": f"Fetched {len(trends)} trend keywords from Pinterest."})
        return jsonify({"ok": False, "message": "No trends returned — cookie may be expired."})
    except Exception as e:
        logger.error(f"Trend refresh failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


# ── API endpoints ─────────────────────────────────────────────────────────

@bp.route("/api/pins")
@login_required
def api_pins():
    status = request.args.get("status")
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    query = Pin.query.order_by(Pin.created_at.desc())
    if status:
        query = query.filter_by(status=status)

    pins = query.offset(offset).limit(limit).all()
    return jsonify({"pins": [p.to_dict() for p in pins], "total": query.count()})


@bp.route("/api/create-pin", methods=["POST"])
@login_required
def api_create_pin():
    """Create a single themed pin from user-chosen theme, category, and keyword."""
    try:
        from app.ai_writer import generate_roundup_content
        from app.imagen_api import generate_collage_image
        from app.models import Pin
        from config import Config

        data     = request.get_json() or {}
        theme    = data.get("theme", "").strip() or None
        category = data.get("category", "").strip() or None
        keyword  = data.get("keyword", "").strip() or None

        # Pull approved products filtered by category
        query = Product.query.filter_by(is_active=True)
        if category:
            query = query.filter_by(category=category)
        products = query.all()

        if len(products) < 3:
            # Fall back to all products if not enough in category
            products = Product.query.filter_by(is_active=True).all()
            if len(products) < 3:
                return jsonify({"ok": False, "error": f"Not enough approved products. Need at least 3, have {len(products)}."}), 400

        import random
        count    = random.randint(min(5, len(products)), min(8, len(products)))
        selected = random.sample(products, count)

        trend_keyword = keyword or (theme or "lifestyle finds")

        content = generate_roundup_content(
            products=selected,
            trend_keyword=trend_keyword,
            benable_url=Config.BENABLE_URL or "https://benable.com",
            theme_hint=theme,
        )

        image_path = generate_collage_image(
            products=selected,
            theme=content["theme"],
            subtitle=content.get("subtitle", "on Amazon"),
            brand_name=Config.BRAND_NAME or "",
            cta_text=content.get("cta_text", "shop here \u2764\ufe0f"),
        )

        import json as _json
        is_url   = image_path and image_path.startswith("http")
        pin      = Pin(
            theme=content["theme"],
            title=content["title"],
            description=content["description"],
            hashtags=_json.dumps(content.get("hashtags", [])),
            image_path=None if is_url else image_path,
            image_url=image_path if is_url else None,
            status=Pin.STATUS_PENDING,
            trend_keyword=trend_keyword,
            style_variant="roundup_collage",
        )
        pin.products = selected
        db.session.add(pin)
        db.session.commit()

        logger.info(f"Custom pin created: '{content['theme']}' (category={category}, keyword={keyword})")
        return jsonify({"ok": True, "pin_id": pin.id, "theme": content["theme"]})

    except Exception as e:
        logger.error(f"Custom pin creation failed: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/trigger", methods=["POST"])
@login_required
def api_trigger():
    try:
        from app.scheduler import run_daily_pin_generation
        run_daily_pin_generation()
        return jsonify({"ok": True, "message": "Pin generation complete."})
    except Exception as e:
        logger.error(f"Trigger failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/upload-pin")
@login_required
def upload_pin():
    from config import Config
    return render_template(
        "upload_pin.html",
        benable_url=Config.BENABLE_URL,
        pinterest_boards=[],  # populated via JS from Pinterest API once connected
    )


@bp.route("/upload-pin/generate-copy", methods=["POST"])
@login_required
def upload_pin_generate_copy():
    try:
        data    = request.get_json()
        niche   = data.get("niche", "beauty")
        keyword = data.get("keyword", "")
        from app.ai_writer import generate_upload_pin_copy
        result = generate_upload_pin_copy(niche, keyword)
        return jsonify({"ok": True, **result})
    except Exception as e:
        logger.error(f"Copy generation failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/upload-pin/publish", methods=["POST"])
@login_required
def upload_pin_publish():
    try:
        import base64
        import requests as req
        from config import Config

        data        = request.get_json()
        image_b64   = data.get("image_base64", "")
        title       = data.get("title", "")
        description = data.get("description", "")
        board_name  = data.get("board_name", "")
        link        = data.get("link", Config.BENABLE_URL_BEAUTY)

        if not Config.PINTEREST_ACCESS_TOKEN:
            return jsonify({"ok": False, "error": "Pinterest not connected yet. API approval still pending."}), 400

        # Strip data URL prefix and decode
        if "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]
        image_bytes = base64.b64decode(image_b64)

        headers = {"Authorization": f"Bearer {Config.PINTEREST_ACCESS_TOKEN}"}

        # Step 1: Upload image to Pinterest media
        upload_resp = req.post(
            "https://api.pinterest.com/v5/media",
            headers=headers,
            json={"media_type": "image"},
            timeout=30,
        )
        upload_resp.raise_for_status()
        upload_data = upload_resp.json()
        media_id    = upload_data["media_id"]
        upload_url  = upload_data["upload_url"]
        upload_params = upload_data.get("upload_parameters", {})

        # Step 2: PUT image bytes to S3 upload URL
        files = {k: (None, v) for k, v in upload_params.items()}
        files["file"] = ("pin.jpg", image_bytes, "image/jpeg")
        s3_resp = req.post(upload_url, files=files, timeout=60)
        s3_resp.raise_for_status()

        # Step 3: Create pin
        board_id = Config.PINTEREST_BOARD_ID
        pin_resp = req.post(
            "https://api.pinterest.com/v5/pins",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "board_id": board_id,
                "title": title,
                "description": description,
                "link": link,
                "media_source": {
                    "source_type": "media_id",
                    "media_id": media_id,
                },
            },
            timeout=30,
        )
        pin_resp.raise_for_status()
        return jsonify({"ok": True, "pin_id": pin_resp.json().get("id")})

    except Exception as e:
        logger.error(f"Pinterest publish failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/post_due", methods=["POST"])
@login_required
def api_post_due():
    try:
        from app.scheduler import schedule_approved_pins
        schedule_approved_pins()
        return jsonify({"ok": True, "message": "Posted due pins."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/stats")
@login_required
def api_stats():
    return jsonify({
        "pending":         Pin.query.filter(Pin.status.in_([Pin.STATUS_PENDING, Pin.STATUS_NEEDS_IMAGE])).count(),
        "approved":        Pin.query.filter_by(status=Pin.STATUS_APPROVED).count(),
        "posted":          Pin.query.filter_by(status=Pin.STATUS_POSTED).count(),
        "rejected":        Pin.query.filter_by(status=Pin.STATUS_REJECTED).count(),
        "total_products":  Product.query.count(),
        "active_products": Product.query.filter_by(is_active=True).count(),
    })


# ── Pinterest OAuth ───────────────────────────────────────────────────────

@bp.route("/pinterest/connect")
@login_required
def pinterest_connect():
    from config import Config
    if not Config.PINTEREST_APP_ID:
        return redirect(url_for("main.setup") + "?error=no_pinterest_app")

    state = secrets.token_urlsafe(16)
    session["pinterest_oauth_state"] = state
    redirect_uri = url_for("main.pinterest_callback", _external=True)
    from app.pinterest_api import get_access_token_url
    return redirect(get_access_token_url(redirect_uri=redirect_uri, state=state))


@bp.route("/pinterest/callback")
@login_required
def pinterest_callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return redirect(url_for("main.setup") + "?error=pinterest_denied")

    expected = session.pop("pinterest_oauth_state", None)
    if not expected or state != expected:
        return redirect(url_for("main.setup") + "?error=state_mismatch")

    if not code:
        return redirect(url_for("main.setup") + "?error=no_code")

    try:
        from app.pinterest_api import exchange_code_for_token
        redirect_uri = url_for("main.pinterest_callback", _external=True)
        token_data   = exchange_code_for_token(code=code, redirect_uri=redirect_uri)

        if token_data.get("access_token"):
            Setting.set("pinterest_access_token", token_data["access_token"])
        if token_data.get("refresh_token"):
            Setting.set("pinterest_refresh_token", token_data["refresh_token"])

        return redirect(url_for("main.setup") + "?success=pinterest_connected")
    except Exception as e:
        logger.error(f"Token exchange failed: {e}", exc_info=True)
        return redirect(url_for("main.setup") + "?error=token_exchange_failed")


# ── Trends ───────────────────────────────────────────────────────────────

import csv
import io as _io


def _guess_category(keyword: str) -> str:
    kw = keyword.lower()
    if any(w in kw for w in ["nail", "manicure", "pedicure", "polish"]):
        return "beauty"
    if any(w in kw for w in ["outfit", "fashion", "style", "dress", "clothes", "wear", "y2k"]):
        return "fashion"
    if any(w in kw for w in ["home", "decor", "room", "bedroom", "kitchen", "desk", "office"]):
        return "home_decor"
    if any(w in kw for w in ["hair", "skin", "makeup", "beauty", "glow", "highlight"]):
        return "beauty"
    if any(w in kw for w in ["tech", "electronic", "gadget", "phone", "charger"]):
        return "tech"
    return "general"


@bp.route("/trends")
@login_required
def trends():
    cached = TrendCache.query.order_by(TrendCache.score.desc(), TrendCache.cached_at.desc()).limit(50).all()
    return render_template("trends.html", trends=cached, analysis=None)


@bp.route("/trends/upload", methods=["POST"])
@login_required
def trends_upload():
    from app.ai_writer import analyze_trends_for_brand
    from config import Config

    files = request.files.getlist("csv_files")
    if not files or all(f.filename == "" for f in files):
        return redirect(url_for("main.trends") + "?error=no_files")

    all_trends = {}

    for f in files:
        if not f.filename:
            continue
        content = f.read().decode("utf-8-sig", errors="replace")
        reader = csv.reader(_io.StringIO(content))

        header_found = False
        for row in reader:
            if not row:
                continue
            if row[0].strip() == "Rank":
                header_found = True
                continue
            if header_found and row[0].strip().isdigit():
                if len(row) < 5:
                    continue
                keyword = row[1].strip().lower()
                if not keyword:
                    continue
                try:
                    def _pct(s):
                        return s.replace("%", "").replace("+", "").replace(",", "").strip()
                    weekly  = _pct(row[2])
                    monthly = _pct(row[3])
                    yearly  = _pct(row[4])
                    # latest score = last non-empty column
                    score = 0.0
                    for cell in reversed(row[5:]):
                        if cell.strip():
                            score = float(cell.strip())
                            break
                    if keyword not in all_trends or score > all_trends[keyword]["score"]:
                        all_trends[keyword] = {
                            "keyword": keyword,
                            "weekly_change": weekly,
                            "monthly_change": monthly,
                            "yearly_change": yearly,
                            "score": score,
                        }
                except (ValueError, IndexError):
                    continue

    if not all_trends:
        return redirect(url_for("main.trends") + "?error=parse_failed")

    sorted_trends = sorted(all_trends.values(), key=lambda x: x["score"], reverse=True)[:50]

    analysis = None
    try:
        analysis = analyze_trends_for_brand(
            trends=sorted_trends[:20],
            brand_name=Config.BRAND_NAME or "Aura Girl Essentials",
            benable_url=Config.BENABLE_URL or "https://benable.com",
        )
    except Exception as e:
        logger.error(f"Trend analysis failed: {e}")

    TrendCache.query.delete()
    for t in sorted_trends:
        db.session.add(TrendCache(
            keyword=t["keyword"],
            category=_guess_category(t["keyword"]),
            score=t["score"],
        ))
    db.session.commit()

    cached = TrendCache.query.order_by(TrendCache.score.desc()).limit(50).all()
    return render_template("trends.html", trends=cached, analysis=analysis)


# ── Health check ──────────────────────────────────────────────────────────

@bp.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})
