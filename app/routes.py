"""
Flask routes: auth, dashboard, products, API, Pinterest OAuth.
"""
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from app import db
from app.models import Pin, Product, Setting, TrendCache

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("main.login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@bp.route("/")
def index():
    return redirect(url_for("main.dashboard"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    from config import Config

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if password and password == Config.DASHBOARD_PASSWORD:
            session["logged_in"] = True
            session.permanent = True
            return redirect(url_for("main.dashboard"))
        elif not Config.DASHBOARD_PASSWORD:
            # No password set — allow access with a warning
            session["logged_in"] = True
            return redirect(url_for("main.dashboard"))
        else:
            error = "Incorrect password. Please try again."

    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ---------------------------------------------------------------------------
# Static image serving (for locally generated images)
# ---------------------------------------------------------------------------

@bp.route("/images/<path:filename>")
def serve_image(filename):
    image_dir = "/tmp/generated_images"
    return send_from_directory(image_dir, filename)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route("/dashboard")
@login_required
def dashboard():
    status_filter = request.args.get("status", "pending")

    pending_pins = (
        Pin.query.filter_by(status=Pin.STATUS_PENDING)
        .order_by(Pin.created_at.desc())
        .all()
    )
    needs_image_pins = (
        Pin.query.filter_by(status=Pin.STATUS_NEEDS_IMAGE)
        .order_by(Pin.created_at.desc())
        .all()
    )
    approved_pins = (
        Pin.query.filter_by(status=Pin.STATUS_APPROVED)
        .order_by(Pin.scheduled_for.asc().nulls_last(), Pin.created_at.desc())
        .all()
    )
    rejected_pins = (
        Pin.query.filter_by(status=Pin.STATUS_REJECTED)
        .order_by(Pin.created_at.desc())
        .limit(20)
        .all()
    )
    posted_pins = (
        Pin.query.filter_by(status=Pin.STATUS_POSTED)
        .order_by(Pin.posted_at.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "dashboard.html",
        pending_pins=pending_pins,
        needs_image_pins=needs_image_pins,
        approved_pins=approved_pins,
        rejected_pins=rejected_pins,
        posted_pins=posted_pins,
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
            # Expect ISO datetime string from datetime-local input
            scheduled_for = datetime.fromisoformat(scheduled_str)
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
            pin.scheduled_for = scheduled_for
        except ValueError:
            logger.warning(f"Invalid scheduled_for format: {scheduled_str}")
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
    logger.info(f"Pin #{pin_id} rejected.")
    return redirect(url_for("main.dashboard"))


@bp.route("/pin/<int:pin_id>/swap", methods=["POST"])
@login_required
def swap_pin(pin_id):
    """Regenerate this pin with a different product or style."""
    import random

    from app.ai_writer import generate_pin_content
    from app.imagen_api import generate_pin_image
    from app.pinterest_api import get_trending_keywords

    pin = Pin.query.get_or_404(pin_id)

    swap_type = request.form.get("swap_type", "product")  # 'product' or 'style'
    active_products = Product.query.filter_by(is_active=True).all()

    if swap_type == "style" or len(active_products) <= 1:
        # Same product, different style
        product = pin.product
        styles = ["lifestyle", "flat_lay", "product_hero", "aesthetic_room", "outdoor"]
        current_style = pin.style_variant or "lifestyle"
        new_style = random.choice([s for s in styles if s != current_style])
    else:
        # Different product
        other_products = [p for p in active_products if p.id != pin.product_id]
        if not other_products:
            other_products = active_products
        product = random.choice(other_products)
        new_style = random.choice(["lifestyle", "flat_lay", "product_hero", "aesthetic_room", "outdoor"])

    try:
        # Get a trending keyword
        trends = get_trending_keywords()
        trend_keyword = pin.trend_keyword or "lifestyle finds"
        if trends:
            relevant = [t for t in trends if t.get("category") in [product.category, "general"]]
            if relevant:
                trend_keyword = random.choice(relevant[:5])["keyword"]

        # Generate new image
        new_image_path = generate_pin_image(
            prompt=f"{trend_keyword} inspired, featuring {product.name}",
            product_name=product.name,
            style=new_style,
        )

        # Generate new content
        content = generate_pin_content(
            product_name=product.name,
            trend_keyword=trend_keyword,
            category=product.category,
            benable_url=product.benable_url,
        )

        # Update pin
        pin.product_id = product.id
        pin.title = content["title"]
        pin.description = content["description"]
        pin.hashtags = json.dumps(content.get("hashtags", []))
        pin.trend_keyword = trend_keyword
        pin.style_variant = content.get("style", new_style)
        pin.status = Pin.STATUS_PENDING if new_image_path else Pin.STATUS_NEEDS_IMAGE
        if new_image_path:
            pin.image_path = new_image_path
        pin.scheduled_for = None

        db.session.commit()
        logger.info(f"Pin #{pin_id} swapped to product '{product.name}' style '{new_style}'")

    except Exception as e:
        logger.error(f"Swap failed for pin #{pin_id}: {e}", exc_info=True)
        db.session.rollback()

    return redirect(url_for("main.dashboard"))


@bp.route("/pin/<int:pin_id>/bulk_approve", methods=["POST"])
@login_required
def bulk_approve(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    pin.status = Pin.STATUS_APPROVED
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/pins/approve_all", methods=["POST"])
@login_required
def approve_all_pending():
    """Approve all currently pending pins."""
    pending = Pin.query.filter_by(status=Pin.STATUS_PENDING).all()
    for pin in pending:
        pin.status = Pin.STATUS_APPROVED
    db.session.commit()
    logger.info(f"Bulk approved {len(pending)} pins.")
    return redirect(url_for("main.dashboard"))


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

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
    name = request.form.get("name", "").strip()
    amazon_url = request.form.get("amazon_url", "").strip()
    benable_url = request.form.get("benable_url", "").strip()
    category = request.form.get("category", "general").strip()
    price = request.form.get("price", "").strip()

    if not name or not amazon_url or not benable_url:
        return redirect(url_for("main.products") + "?error=missing_fields")

    if category not in VALID_CATEGORIES:
        category = "general"

    product = Product(
        name=name,
        amazon_url=amazon_url,
        benable_url=benable_url,
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
    logger.info(f"Product #{product_id} '{product.name}' is_active={product.is_active}")
    return redirect(url_for("main.products"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    # Don't delete if it has pins — just deactivate
    if product.pins:
        product.is_active = False
        db.session.commit()
    else:
        db.session.delete(product)
        db.session.commit()
    return redirect(url_for("main.products"))


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------

@bp.route("/setup")
@login_required
def setup():
    from config import Config

    config_status = Config.is_configured()

    # Check Pinterest connection
    pinterest_user = None
    try:
        from app.pinterest_api import get_user_info
        pinterest_user = get_user_info()
    except Exception:
        pass

    # Get boards
    boards = []
    try:
        from app.pinterest_api import get_boards
        boards = get_boards()
    except Exception:
        pass

    # Get trend cache info
    trend_count = TrendCache.query.count()
    latest_trend = TrendCache.query.order_by(TrendCache.cached_at.desc()).first()

    return render_template(
        "setup.html",
        config_status=config_status,
        pinterest_user=pinterest_user,
        boards=boards,
        trend_count=trend_count,
        latest_trend=latest_trend,
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@bp.route("/api/pins")
@login_required
def api_pins():
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    query = Pin.query.order_by(Pin.created_at.desc())
    if status:
        query = query.filter_by(status=status)

    pins = query.offset(offset).limit(limit).all()
    return jsonify({"pins": [p.to_dict() for p in pins], "total": query.count()})


@bp.route("/api/trigger", methods=["POST"])
@login_required
def api_trigger():
    """Manually trigger pin generation."""
    try:
        from app.scheduler import run_daily_pin_generation
        run_daily_pin_generation()
        return jsonify({"ok": True, "message": "Pin generation triggered successfully."})
    except Exception as e:
        logger.error(f"Manual trigger failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/post_due", methods=["POST"])
@login_required
def api_post_due():
    """Manually trigger posting of due approved pins."""
    try:
        from app.scheduler import schedule_approved_pins
        schedule_approved_pins()
        return jsonify({"ok": True, "message": "Checked and posted due pins."})
    except Exception as e:
        logger.error(f"Manual post trigger failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/stats")
@login_required
def api_stats():
    """Return pin statistics."""
    stats = {
        "pending": Pin.query.filter_by(status=Pin.STATUS_PENDING).count(),
        "approved": Pin.query.filter_by(status=Pin.STATUS_APPROVED).count(),
        "posted": Pin.query.filter_by(status=Pin.STATUS_POSTED).count(),
        "rejected": Pin.query.filter_by(status=Pin.STATUS_REJECTED).count(),
        "needs_image": Pin.query.filter_by(status=Pin.STATUS_NEEDS_IMAGE).count(),
        "total_products": Product.query.count(),
        "active_products": Product.query.filter_by(is_active=True).count(),
    }
    return jsonify(stats)


# ---------------------------------------------------------------------------
# Pinterest OAuth
# ---------------------------------------------------------------------------

@bp.route("/pinterest/connect")
@login_required
def pinterest_connect():
    """Start Pinterest OAuth flow."""
    from config import Config

    if not Config.PINTEREST_APP_ID:
        return redirect(url_for("main.setup") + "?error=no_pinterest_app")

    state = secrets.token_urlsafe(16)
    session["pinterest_oauth_state"] = state

    redirect_uri = url_for("main.pinterest_callback", _external=True)
    from app.pinterest_api import get_access_token_url
    auth_url = get_access_token_url(redirect_uri=redirect_uri, state=state)

    return redirect(auth_url)


@bp.route("/pinterest/callback")
@login_required
def pinterest_callback():
    """Handle Pinterest OAuth callback."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        logger.error(f"Pinterest OAuth error: {error}")
        return redirect(url_for("main.setup") + f"?error=pinterest_denied")

    # Verify state
    expected_state = session.pop("pinterest_oauth_state", None)
    if not expected_state or state != expected_state:
        logger.error("Pinterest OAuth state mismatch.")
        return redirect(url_for("main.setup") + "?error=state_mismatch")

    if not code:
        return redirect(url_for("main.setup") + "?error=no_code")

    try:
        from app.pinterest_api import exchange_code_for_token
        redirect_uri = url_for("main.pinterest_callback", _external=True)
        token_data = exchange_code_for_token(code=code, redirect_uri=redirect_uri)

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if access_token:
            Setting.set("pinterest_access_token", access_token)
        if refresh_token:
            Setting.set("pinterest_refresh_token", refresh_token)

        logger.info("Pinterest account connected successfully.")
        return redirect(url_for("main.setup") + "?success=pinterest_connected")

    except Exception as e:
        logger.error(f"Pinterest token exchange failed: {e}", exc_info=True)
        return redirect(url_for("main.setup") + "?error=token_exchange_failed")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@bp.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})
