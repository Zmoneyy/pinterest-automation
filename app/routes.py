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

        pin.theme        = content["theme"]
        pin.title        = content["title"]
        pin.description  = content["description"]
        pin.hashtags     = json.dumps(content.get("hashtags", []))
        pin.products     = new_products
        pin.status       = Pin.STATUS_PENDING if image_path else Pin.STATUS_NEEDS_IMAGE
        if image_path:
            pin.image_path = image_path
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

    return render_template(
        "setup.html",
        config_status=config_status,
        pinterest_user=pinterest_user,
        boards=boards,
        trend_count=trend_count,
        latest_trend=latest_trend,
    )


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


@bp.route("/api/trigger", methods=["POST"])
@login_required
def api_trigger():
    try:
        from app.scheduler import run_daily_pin_generation
        run_daily_pin_generation()
        return jsonify({"ok": True, "message": "Pin generation triggered."})
    except Exception as e:
        logger.error(f"Trigger failed: {e}", exc_info=True)
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
