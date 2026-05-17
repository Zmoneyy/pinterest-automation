"""
Flask routes: auth, dashboard, products, API, Pinterest OAuth.
Updated for collage/roundup pins (Pin.products is now a list, not a single FK).
"""
import base64
import json
import logging
import os
import random
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

# Routes that are visible on the public domain (auragirlessentials.com)
PUBLIC_PATHS = ("/shop", "/privacy", "/health", "/")

# Rotating CTAs — kept fresh so pins don't all sound the same (better for algorithm)
PIN_CTAS = [
    "See why everyone's obsessed →",
    "You need this in your life →",
    "This is the one everyone's buying →",
    "Girls are going crazy for this →",
    "Don't sleep on this find →",
    "This is your sign to treat yourself →",
    "Already sold out once — grab it now →",
    "The hype is real →",
    "This one's worth every penny →",
    "Your future self will thank you →",
]

def _random_cta():
    return random.choice(PIN_CTAS)

def _cst_to_utc(dt_str: str):
    """Parse a naive datetime string entered in CST and return UTC datetime.
    CST = UTC-6. Handles both 'YYYY-MM-DDTHH:MM' and 'YYYY-MM-DD HH:MM' formats.
    """
    from datetime import timedelta
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", ""))
        if dt.tzinfo is None:
            dt = dt + timedelta(hours=6)  # CST → UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

PUBLIC_DOMAIN = "auragirlessentials.com"


@bp.before_request
def block_admin_on_public_domain():
    """
    auragirlessentials.com → only /shop routes are visible.
    Admin Cloud Run URL → requires HTTP Basic Auth before anything loads.
    """
    host = request.host.split(":")[0]

    # Public domain: block all non-shop routes
    if host == PUBLIC_DOMAIN:
        path = request.path
        if not any(path.startswith(p) for p in PUBLIC_PATHS):
            return "", 404
        return  # public domain: no basic auth needed

    # Admin URL: require HTTP Basic Auth as first gate
    # Skip for /shop paths (in case someone hits admin URL for shop pages)
    path = request.path
    if any(path.startswith(p) for p in PUBLIC_PATHS):
        return  # public paths never need basic auth

    admin_user = os.environ.get("ADMIN_BASIC_USER", "aura")
    admin_pass = os.environ.get("ADMIN_BASIC_PASS", "")

    if not admin_pass:
        return  # no basic auth configured — fall through to Flask login

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            user, pw = decoded.split(":", 1)
            if user == admin_user and pw == admin_pass:
                return  # ✅ basic auth passed
        except Exception:
            pass

    # Not authorized — show browser's native login prompt
    return (
        "Private — Authorized Access Only",
        401,
        {
            "WWW-Authenticate": 'Basic realm="Aura Girl Admin"',
            "Content-Type": "text/plain",
        },
    )


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
    host = request.host.split(":")[0]
    if host == PUBLIC_DOMAIN:
        return redirect(url_for("main.shop"))
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
    scheduled_pins = (
        Pin.query.filter_by(status=Pin.STATUS_SCHEDULED)
        .order_by(Pin.scheduled_for.asc()).all()
    )
    draft_pins = (
        Pin.query.filter_by(status=Pin.STATUS_DRAFT)
        .order_by(Pin.created_at.desc()).all()
    )

    from config import Config
    # Check Pinterest connection status for the warning banner
    pinterest_connected = bool(Config.is_configured().get("pinterest_token"))
    return render_template(
        "dashboard.html",
        pending_pins=pending_pins,
        approved_pins=approved_pins,
        posted_pins=posted_pins,
        rejected_pins=rejected_pins,
        scheduled_pins=scheduled_pins,
        draft_pins=draft_pins,
        scheduled_boards=list(Config.PINTEREST_BOARDS.keys()),
        active_tab=status_filter,
        now=datetime.now(timezone.utc),
        pinterest_connected=pinterest_connected,
    )


@bp.route("/pin/<int:pin_id>/delete", methods=["POST"])
@login_required
def delete_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    was_draft = pin.status == Pin.STATUS_DRAFT
    db.session.delete(pin)
    db.session.commit()
    return redirect(url_for("main.dashboard", status="draft" if was_draft else "scheduled"))


@bp.route("/pin/<int:pin_id>/schedule-draft", methods=["POST"])
@login_required
def schedule_draft_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    sched_str = request.form.get("scheduled_for", "").strip()
    pin.scheduled_for = _cst_to_utc(sched_str)
    pin.status = Pin.STATUS_SCHEDULED
    db.session.commit()
    return redirect(url_for("main.dashboard", status="scheduled"))


@bp.route("/pin/<int:pin_id>/edit-scheduled", methods=["POST"])
@login_required
def edit_scheduled_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    was_draft = pin.status == Pin.STATUS_DRAFT
    pin.title       = request.form.get("title", pin.title).strip()
    pin.description = request.form.get("description", pin.description).strip()
    pin.hashtags    = request.form.get("hashtags", pin.hashtags or "").strip()
    pin.alt_text    = request.form.get("alt_text", pin.alt_text or "").strip() or None
    pin.amazon_url  = request.form.get("amazon_url", "").strip() or None
    pin.board_name  = request.form.get("board_name", pin.board_name or "").strip() or None
    sched_str = request.form.get("scheduled_for", "").strip()
    if sched_str:
        pin.scheduled_for = _cst_to_utc(sched_str)
    db.session.commit()
    return redirect(url_for("main.dashboard", status="draft" if was_draft else "scheduled"))


@bp.route("/pin/<int:pin_id>/approve", methods=["POST"])
@login_required
def approve_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    scheduled_str = request.form.get("scheduled_for", "").strip()
    if scheduled_str:
        try:
            pin.scheduled_for = _cst_to_utc(scheduled_str)
        except ValueError:
            pin.scheduled_for = None
    else:
        pin.scheduled_for = None

    pin.status = Pin.STATUS_APPROVED

    # Activate all products linked to this pin → they appear on shop pages
    activated = 0
    for product in pin.products:
        if not product.is_active:
            product.is_active = True
            activated += 1

    db.session.commit()
    logger.info(f"Pin #{pin_id} approved — activated {activated} products on shop")
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


def _score_products_against_trends(products, trends):
    """
    Score each product against real Pinterest trend keywords from TrendCache.

    Scoring:
    - Trend keyword match in product name → up to 60 pts (weighted by trend score)
    - Commission rate (luxury_beauty 10% > beauty/home 3% > fitness 1%)
    - Price (higher price = more $ per sale at same rate)

    Also returns the matching trend keyword for display.
    """
    # Normalise trend keywords once
    # Each entry: (keyword_lower, trend_score_normalised_0_to_1)
    max_trend_score = max((t.score or 1 for t in trends), default=1) or 1
    trend_data = [
        (t.keyword.lower().strip(), (t.score or 0) / max_trend_score)
        for t in trends
        if t.keyword
    ]

    results = []
    for product in products:
        name = (product.name or "").lower()
        cat  = (product.category or "general").lower()
        try:
            price = float(str(product.price or "0").replace("$", "").replace(",", ""))
        except Exception:
            price = 0.0

        score = 0
        matched_trend = ""
        matched_trend_score = 0.0

        # ── 1. Pinterest trend match (real data) ──
        # Check if any trend keyword appears in the product name (or vice versa)
        for kw, t_score in trend_data:
            # Split trend keyword into words and check partial matches
            kw_words = kw.split()
            hit = (
                kw in name or                            # full keyword match
                any(w in name for w in kw_words if len(w) > 3)  # any significant word
            )
            if hit:
                pts = int(t_score * 60)  # up to 60 pts based on trend strength
                if pts > matched_trend_score:
                    matched_trend = kw
                    matched_trend_score = pts
        score += int(matched_trend_score)

        # ── 2. Commission rate ──
        if cat == "luxury_beauty":
            score += 30
        elif cat in ("beauty", "home_decor"):
            score += 18
        elif cat == "fitness":
            score += 8
        else:
            score += 10

        # ── 3. Price (higher → more $ per sale) ──
        if price >= 60:
            score += 22
        elif price >= 30:
            score += 14
        elif price >= 15:
            score += 7

        # ── Badge ──
        if matched_trend_score > 0:
            # Has a real trend signal
            if score >= 70:
                badge = "🔥 Trending Now"
                badge_style = "background:#fde8e8;color:#b91c1c;"
            elif score >= 45:
                badge = "📈 Rising"
                badge_style = "background:#fff3cd;color:#856404;"
            else:
                badge = "✨ On Trend"
                badge_style = "background:#d4f4e8;color:#1a7a4a;"
        else:
            badge = ""
            badge_style = ""

        product._rec_score = score
        product._rec_badge = badge
        product._rec_badge_style = badge_style
        product._rec_trend = matched_trend  # the actual Pinterest keyword that matched
        results.append(product)

    results.sort(key=lambda p: p._rec_score, reverse=True)
    return results


@bp.route("/products")
@login_required
def products():
    from app.models import ProductCandidate
    all_products = Product.query.order_by(Product.added_at.desc()).all()
    trends = TrendCache.query.order_by(TrendCache.score.desc()).all()

    if trends:
        all_products = _score_products_against_trends(all_products, trends)
        trend_keywords = [t.keyword for t in trends[:10]]  # top 10 for the banner
        trend_source = "pinterest"
    else:
        # No trends uploaded yet — just show products sorted by commission × price
        for p in all_products:
            cat = (p.category or "general").lower()
            try:
                price = float(str(p.price or "0").replace("$", "").replace(",", ""))
            except Exception:
                price = 0.0
            commission = {"luxury_beauty": 10, "beauty": 3, "home_decor": 3, "fitness": 1}.get(cat, 3)
            p._rec_score = commission * price
            p._rec_badge = ""
            p._rec_badge_style = ""
            p._rec_trend = ""
        all_products.sort(key=lambda p: p._rec_score, reverse=True)
        trend_keywords = []
        trend_source = "none"

    # 10% commission focus: only show luxury_beauty in library
    all_products = [p for p in all_products if (p.category or "").lower() == "luxury_beauty"]

    # Assign price tier to each product + count their pins
    TIERS = [
        {"key": "entry", "label": "Entry Luxury",  "range": "$30–$75",   "target": 12, "color": "#059669", "bg": "#d1fae5", "min": 30,  "max": 75},
        {"key": "mid",   "label": "Mid Luxury",    "range": "$75–$150",  "target": 12, "color": "#1d4ed8", "bg": "#dbeafe", "min": 75,  "max": 150},
        {"key": "high",  "label": "High Luxury",   "range": "$150+",     "target": 6,  "color": "#7c3aed", "bg": "#ede9fe", "min": 150, "max": 99999},
    ]

    def _tier(price_str):
        try:
            p = float(str(price_str or "0").replace("$", "").replace(",", ""))
            if p >= 150: return "high"
            if p >= 75:  return "mid"
            if p >= 30:  return "entry"
        except Exception:
            pass
        return None

    for p in all_products:
        p._tier      = _tier(p.price)
        p._pin_count = len(p.pins)  # pins this product has been used in

    # Tier summary for the strategy dashboard
    tier_stats = []
    for t in TIERS:
        tier_products = [p for p in all_products if p._tier == t["key"]]
        pins_made     = sum(p._pin_count for p in tier_products)
        tier_stats.append({**t, "products": len(tier_products), "pins_made": pins_made})

    # Pending candidates: only luxury_beauty
    pending_candidates = ProductCandidate.query.filter_by(
        status=ProductCandidate.STATUS_PENDING,
        category="luxury_beauty",
    ).order_by(ProductCandidate.discovered_at.desc()).all()

    # Tag pending candidates with their tier too
    for c in pending_candidates:
        c._tier = _tier(c.price)

    return render_template(
        "products.html",
        products=all_products,
        pending_candidates=pending_candidates,
        tier_stats=tier_stats,
        categories=VALID_CATEGORIES,
        trend_keywords=trend_keywords,
        trend_source=trend_source,
        trend_count=len(trends),
        discovering=_discovery_state["running"],
        discovery_state=_discovery_state,
    )


@bp.route("/products/import-url", methods=["POST"])
@login_required
def import_amazon_url():
    """Import a product directly from an Amazon URL — bypasses scraping."""
    from app.amazon_api import AMAZON_HEADERS
    from bs4 import BeautifulSoup
    import re as _re

    url = request.form.get("amazon_url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400

    # Extract ASIN from URL
    asin_match = _re.search(r"/dp/([A-Z0-9]{10})", url)
    asin = asin_match.group(1) if asin_match else None

    # Build clean affiliate URL
    from config import Config
    tag = Config.AMAZON_ASSOCIATE_TAG or "auragirlcreat-20"
    affiliate_url = f"https://www.amazon.com/dp/{asin}?tag={tag}&linkCode=ll1&language=en_US" if asin else url

    try:
        import time, random
        time.sleep(random.uniform(1, 2))
        resp = requests.get(url, headers=AMAZON_HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Product name
        name_tag = soup.select_one("#productTitle") or soup.select_one("#title")
        name = name_tag.get_text(strip=True) if name_tag else ""

        # Price
        price = ""
        for sel in ["#priceblock_ourprice", "#priceblock_dealprice", ".a-price .a-offscreen", "#price_inside_buybox"]:
            p = soup.select_one(sel)
            if p:
                price = p.get_text(strip=True).replace("$", "").strip()
                try:
                    price = str(round(float(_re.search(r"[\d.]+", price).group()), 2))
                    break
                except Exception:
                    price = ""

        # Image
        image_url = ""
        img = soup.select_one("#landingImage") or soup.select_one("#imgBlkFront")
        if img:
            image_url = img.get("src") or img.get("data-src") or ""

        if not name:
            return jsonify({"ok": False, "error": "Could not read product name — try adding manually below"}), 400

        # Save as ProductCandidate (pending approval)
        from app.models import ProductCandidate
        c = ProductCandidate(
            name=name[:255],
            asin=asin,
            amazon_url=affiliate_url,
            category="luxury_beauty",
            image_url=image_url or None,
            price=price or None,
            trend_keyword="Manual Import",
            status=ProductCandidate.STATUS_PENDING,
        )
        db.session.add(c)
        db.session.commit()
        return jsonify({"ok": True, "name": name, "price": price, "image_url": image_url, "id": c.id})

    except Exception as e:
        logger.error(f"import_amazon_url error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


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

def _price_float(price_str) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", price_str or "0") or 0)
    except Exception:
        return 0.0


@bp.route("/products/queue")
@login_required
def product_queue():
    # Queue is now merged into the Products page
    qs = request.query_string.decode()
    dest = url_for("main.products")
    if qs:
        dest += "?" + qs
    return redirect(dest)


# ── Background discovery state ──
_discovery_state = {
    "running": False,
    "added": 0,
    "done": 0,
    "total": 0,
    "current": "",
    "started_at": None,
}


def _run_discovery_background(app, trend_dicts=None, manual_keyword=None):
    """Search Amazon for luxury beauty products via SerpAPI and queue them as ProductCandidates."""
    import threading

    def _worker():
        global _discovery_state
        import random, time
        from app.amazon_api import _get_serpapi_key, search_products, _build_affiliate_url, _guess_category

        serpapi_key = _get_serpapi_key()

        if not serpapi_key:
            _discovery_state["running"] = False
            _discovery_state["current"] = "❌ SerpAPI key not configured — add it in Setup"
            return

        # Build search list from TrendEntry top products
        searches = []

        if manual_keyword:
            searches.append((manual_keyword, manual_keyword))
        elif trend_dicts:
            seen_q = set()
            for td in trend_dicts:
                q = td.get("keyword", "").strip()
                if q and q not in seen_q:
                    seen_q.add(q)
                    label = td.get("source_category", q)
                    searches.append((q, label))
        else:
            _discovery_state["running"] = False
            _discovery_state["current"] = "❌ No trend data — add products via the Trends tab first"
            return

        _discovery_state["running"]    = True
        _discovery_state["added"]      = 0
        _discovery_state["done"]       = 0
        _discovery_state["total"]      = len(searches)
        _discovery_state["started_at"] = datetime.now(timezone.utc).isoformat()

        with app.app_context():
            from app.models import ProductCandidate, Product, TrendEntry
            from app.amazon_api import is_luxury_beauty
            from config import Config
            associate_tag = Config.AMAZON_ASSOCIATE_TAG or "auragirlcreat-20"

            # Build category map from TrendEntry so we know which category each product belongs to
            entry_category_map = {}
            for entry in TrendEntry.query.all():
                for tp in entry.tp_list():
                    entry_category_map[tp.lower()] = entry.category

            for i, (query, label) in enumerate(searches):
                _discovery_state["current"] = f"🔍 Searching: {query[:50]}…"
                _discovery_state["done"]    = i + 1

                # Guess category from entry map, fall back to luxury_beauty
                cat = entry_category_map.get(query.lower(), "luxury_beauty")

                try:
                    products = search_products(query, category=cat, max_results=10)
                except Exception as e:
                    logger.error(f"SerpAPI search error for '{query}': {e}")
                    products = []

                # For brand-level searches (e.g. "Tatcha amazon"), Amazon often omits
                # the brand name from product titles. Trust the query instead of the title.
                query_is_luxury = is_luxury_beauty(query)

                for p in products:
                    asin = p.get("asin", "")
                    name = p.get("name", "")
                    if not name:
                        continue
                    if not query_is_luxury and not is_luxury_beauty(name):
                        continue  # only block if BOTH query and result name are non-luxury
                    # Filter out wholesale/pallet/bundle junk listings
                    name_lower = name.lower()
                    if any(w in name_lower for w in ["pallet", "units", "bundle lot", "wholesale", "returned", "damaged"]):
                        continue
                    # Skip if already seen (any status — including rejected, so rejects don't come back)
                    if asin and ProductCandidate.query.filter_by(asin=asin).first():
                        continue
                    if asin and Product.query.filter(Product.amazon_url.contains(asin)).first():
                        continue
                    if not asin and ProductCandidate.query.filter(
                        db.func.lower(ProductCandidate.name) == name.lower().strip()
                    ).first():
                        continue

                    amazon_url = p.get("amazon_url") or (
                        _build_affiliate_url(asin, associate_tag) if asin else ""
                    )
                    db.session.add(ProductCandidate(
                        name=name,
                        asin=asin,
                        amazon_url=amazon_url,
                        category=cat,
                        source_category=label,
                        image_url=p.get("image_url"),
                        price=p.get("price"),
                        trend_keyword=query,
                        status=ProductCandidate.STATUS_PENDING,
                    ))
                    _discovery_state["added"] += 1

                db.session.commit()
                time.sleep(random.uniform(0.5, 1.5))

        _discovery_state["running"] = False
        _discovery_state["current"] = f"✅ Done — {_discovery_state['added']} new products found"
        logger.info(f"Discovery complete: {_discovery_state['added']} products via SerpAPI")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


@bp.route("/products/discover", methods=["POST"])
@login_required
def discover_products():
    """
    Kick off background Amazon discovery.
    Strategy: extract unique luxury brands from TrendEntry top_products,
    search each brand on Amazon (10 results each) → ~9 searches = ~90 products.
    Data-driven: brands come from TrendEntry, nothing hardcoded.
    """
    from app.models import TrendEntry
    from app.amazon_api import is_luxury_beauty, LUXURY_BEAUTY_BRANDS

    if _discovery_state["running"]:
        return redirect(url_for("main.products") + "?discovering=1")

    manual_keyword = request.form.get("keyword", "").strip()
    trend_dicts = []

    BEAUTY_KEYWORDS = [
        "blush", "bronzer", "foundation", "concealer", "serum", "essence",
        "moisturizer", "lotion", "cream", "face", "skincare", "nail", "perfume",
        "cologne", "makeup", "mascara", "lipstick", "eyeshadow", "primer",
        "toner", "retinol", "vitamin c", "hyaluronic", "spf", "sunscreen",
        "contour", "highlighter", "setting", "powder", "lip", "eye",
    ]

    def _is_beauty_entry(cat):
        return any(kw in cat.lower() for kw in BEAUTY_KEYWORDS)

    def _extract_brand(product_name):
        """Find the luxury brand in a product name. Returns title-cased brand string."""
        name_lower = product_name.lower()
        # Match longest brand first to avoid partial matches (e.g. "la mer" before "la")
        for brand in sorted(LUXURY_BEAUTY_BRANDS, key=len, reverse=True):
            if brand in name_lower:
                return brand.title()
        return None

    if manual_keyword:
        trend_dicts = [{"keyword": manual_keyword, "category": "luxury_beauty", "source_category": "Manual Search"}]
    else:
        entries = TrendEntry.query.order_by(TrendEntry.saved_at.desc()).all()
        beauty_entries = [e for e in entries if _is_beauty_entry(e.category)]
        priority_order = {"high": 0, "medium": 1, "low": 2}
        beauty_entries.sort(key=lambda e: priority_order.get(e.priority or "medium", 1))

        # Extract unique luxury brands from top_products — one search per brand
        # 9 brands × 10 results = ~90 products, ~9 SerpAPI credits
        seen_brands = {}  # brand_key -> (display_name, source_category)
        TARGET_BRANDS = 9

        for entry in beauty_entries:
            for product_name in entry.tp_list():
                brand = _extract_brand(product_name)
                if not brand:
                    continue
                brand_key = brand.lower()
                if brand_key not in seen_brands:
                    seen_brands[brand_key] = (brand, entry.category)
                if len(seen_brands) >= TARGET_BRANDS:
                    break
            if len(seen_brands) >= TARGET_BRANDS:
                break

        for brand_key, (brand_display, source_category) in seen_brands.items():
            trend_dicts.append({
                "keyword": f"{brand_display} amazon",
                "category": "luxury_beauty",
                "source_category": source_category,
            })

        if not trend_dicts:
            return redirect(url_for("main.products") + "?error=no_trends")

    from flask import current_app
    _run_discovery_background(current_app._get_current_object(), trend_dicts, manual_keyword)
    return redirect(url_for("main.products") + "?discovering=1")


@bp.route("/products/discover/status")
@login_required
def discover_status():
    return jsonify(_discovery_state)


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
    return redirect(url_for("main.products"))


@bp.route("/products/queue/<int:candidate_id>/reject", methods=["POST"])
@login_required
def reject_candidate(candidate_id):
    candidate = ProductCandidate.query.get_or_404(candidate_id)
    candidate.status = ProductCandidate.STATUS_REJECTED
    db.session.commit()
    return redirect(url_for("main.products"))


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
    return redirect(url_for("main.products"))


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
    return redirect(url_for("main.products"))


# ── Setup wizard ──────────────────────────────────────────────────────────

@bp.route("/setup/sync-boards")
@login_required
def sync_boards():
    """
    Fetch all boards from Pinterest API and return them as JSON.
    Also identifies which ones aren't yet in config (new boards to add).
    """
    from app.pinterest_api import get_boards
    from config import Config
    try:
        boards = get_boards()
        existing_ids = set(Config.PINTEREST_BOARDS.values())
        existing_names = set(Config.PINTEREST_BOARDS.keys())
        new_boards = [b for b in boards if b["id"] not in existing_ids]
        return jsonify({
            "ok": True,
            "all_boards": boards,
            "new_boards": new_boards,
            "existing_names": list(existing_names),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


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

    from config import Config
    config_board_ids = set(Config.PINTEREST_BOARDS.values())

    return render_template(
        "setup.html",
        config_status=config_status,
        pinterest_user=pinterest_user,
        boards=boards,
        trend_count=trend_count,
        latest_trend=latest_trend,
        cookie_status=cookie_status,
        stored_cookie=stored_cookie,
        config_board_ids=config_board_ids,
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
    from app.keyword_research import get_top_keywords_for_niche

    # Pre-load top trending keywords per niche to auto-fill the keyword field
    trending = {
        "beauty":    get_top_keywords_for_niche("beauty", limit=5),
        "home_decor": get_top_keywords_for_niche("home_decor", limit=5),
        "fitness":   get_top_keywords_for_niche("fitness", limit=5),
    }

    return render_template(
        "upload_pin.html",
        benable_url=Config.BENABLE_URL,
        pinterest_boards=list(Config.PINTEREST_BOARDS.keys()),
        trending_keywords=trending,
    )


@bp.route("/upload-pin/trending-keywords")
@login_required
def trending_keywords_api():
    """Return top trending keywords per niche from cache."""
    from app.keyword_research import get_top_keywords_for_niche
    niche = request.args.get("niche", "beauty")
    keywords = get_top_keywords_for_niche(niche, limit=5)
    return jsonify({"keywords": keywords})


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


@bp.route("/upload-pin/fetch-amazon-images", methods=["POST"])
@login_required
def fetch_amazon_images():
    """
    Given a list of Amazon product URLs, extract each ASIN, fetch the real
    product image (via SerpAPI), upload to GCS, and return GCS URLs so they
    can be used as Ideogram visual references.
    """
    import re, uuid, requests as req
    from google.cloud import storage as gcs
    from config import Config

    data = request.get_json()
    amazon_urls = data.get("urls", [])[:4]  # max 4 products

    if not amazon_urls:
        return jsonify({"ok": False, "error": "No URLs provided"}), 400

    results = []
    gcs_client = gcs.Client()
    bucket = gcs_client.bucket("pinterest-automation-images-814656203168")

    for url in amazon_urls:
        url = url.strip()
        if not url:
            continue

        # Follow amzn.to short links to get the full URL with ASIN
        # Use GET (not HEAD) — Amazon often ignores HEAD and returns a redirect loop
        if 'amzn.to' in url or 'a.co' in url:
            try:
                redir = req.get(url, allow_redirects=True, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"},
                                stream=True)
                redir.close()  # don't download body, just need the final URL
                url = redir.url
                logger.info(f"Resolved short link → {url}")
            except Exception as e:
                logger.warning(f"Could not follow short link redirect for {url}: {e}")

        # Extract ASIN from URL: /dp/XXXXXXXXXX or /product/XXXXXXXXXX
        asin_match = re.search(r'/(?:dp|product|gp/product)/([A-Z0-9]{10})', url)
        if not asin_match:
            results.append({"url": url, "error": "Could not extract ASIN from URL", "image_url": None, "name": None})
            continue

        asin = asin_match.group(1)
        logger.info(f"Fetching product image for ASIN: {asin}")

        try:
            # Free method: scrape product title directly from Amazon page
            amz_headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            product_title = None
            try:
                page_resp = req.get(
                    f"https://www.amazon.com/dp/{asin}",
                    headers=amz_headers,
                    timeout=15,
                )
                if page_resp.ok:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(page_resp.text, "html.parser")

                    # Source 1: #productTitle — the definitive element
                    title_tag = soup.find(id="productTitle")
                    if title_tag:
                        product_title = title_tag.get_text(strip=True)

                    # Source 2: embedded JSON blob — Amazon serves "productTitle":"..." in
                    # a JS data object when the page is bot-detected (no rendered DOM element)
                    if not product_title:
                        json_match = re.search(r'"productTitle"\s*:\s*"([^"]{10,})"', page_resp.text)
                        if json_match:
                            import html as html_module
                            product_title = html_module.unescape(json_match.group(1)).strip()

                    # Source 3: og:title meta tag
                    if not product_title:
                        og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "title"})
                        if og and og.get("content"):
                            raw = og["content"].strip()
                            cleaned = re.sub(r'\s*[:\|]\s*Amazon\.com.*$', '', raw, flags=re.IGNORECASE).strip()
                            if cleaned and cleaned.lower() not in ("amazon.com", "amazon", ""):
                                product_title = cleaned

                    # Source 4: <title> tag with "Amazon.com :" prefix stripped
                    if not product_title:
                        page_title = soup.find("title")
                        if page_title:
                            raw = page_title.get_text(strip=True)
                            cleaned = re.sub(r'^Amazon\.com\s*[:\-]\s*', '', raw).split(" : ")[0].strip()
                            if cleaned and cleaned.lower() not in ("amazon.com", "amazon", ""):
                                product_title = cleaned
            except Exception as scrape_err:
                logger.warning(f"Could not scrape Amazon title for {asin}: {scrape_err}")

            # Try extracting title from the original URL path as last resort
            if not product_title:
                slug_match = re.search(r'/([^/]+)/dp/', url)
                if slug_match:
                    slug = slug_match.group(1).replace('-', ' ').title()
                    if len(slug) > 5:
                        product_title = slug
            if not product_title:
                product_title = f"Amazon Product ({asin})"

            # Try to get the real product image from the Amazon page we already scraped
            product_image_url = None
            img_headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Referer": "https://www.amazon.com/",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            }

            # Try scraping the main product image from the page first
            try:
                if 'page_resp' in dir() and page_resp and page_resp.ok:
                    from bs4 import BeautifulSoup as _BS
                    _soup = _BS(page_resp.text, "html.parser")
                    # Amazon stores the main image in #landingImage or #imgBlkFront
                    for img_id in ("landingImage", "imgBlkFront", "main-image"):
                        img_tag = _soup.find(id=img_id)
                        if img_tag:
                            src = img_tag.get("src") or img_tag.get("data-old-hires") or img_tag.get("data-src")
                            if src and src.startswith("http"):
                                product_image_url = src
                                break
            except Exception:
                pass

            # Fallback CDN URL patterns
            if not product_image_url:
                cdn_candidates = [
                    f"https://m.media-amazon.com/images/P/{asin}.01.LZZZZZZZ.jpg",
                    f"https://images-na.ssl-images-amazon.com/images/P/{asin}.01.LZZZZZZZ.jpg",
                ]
                for cdn_url in cdn_candidates:
                    try:
                        test = req.get(cdn_url, headers=img_headers, timeout=10)
                        # Check it's actually an image and not a placeholder (>5KB)
                        if test.ok and test.headers.get("content-type", "").startswith("image") and len(test.content) > 5000:
                            product_image_url = cdn_url
                            break
                    except Exception:
                        continue

            if not product_image_url:
                product_image_url = f"https://m.media-amazon.com/images/P/{asin}.01.LZZZZZZZ.jpg"

            img_resp = req.get(product_image_url, headers=img_headers, timeout=20)
            img_resp.raise_for_status()

            content_type = img_resp.headers.get("content-type", "image/jpeg")
            ext = "jpg" if "jpeg" in content_type else "png"

            # Upload to GCS
            blob_name = f"product-refs/{asin}_{uuid.uuid4().hex[:8]}.{ext}"
            blob = bucket.blob(blob_name)
            blob.upload_from_string(img_resp.content, content_type=content_type)
            gcs_url = f"https://storage.googleapis.com/pinterest-automation-images-814656203168/{blob_name}"

            # Use the full resolved URL — Pinterest trusts long amazon.com URLs more than short links
            # Strip tracking params that change but keep the affiliate tag
            from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
            parsed = urlparse(url)
            # Keep only the path (which has the ASIN) + affiliate tag
            full_affiliate_url = f"https://www.amazon.com/dp/{asin}?tag=auragirlcreat-20"

            results.append({
                "asin": asin,
                "name": str(product_title),
                "image_url": gcs_url,
                "amazon_url": full_affiliate_url,
                "error": None,
            })
            logger.info(f"Product image uploaded to GCS: {gcs_url}")

        except Exception as e:
            logger.error(f"Failed to fetch image for ASIN {asin}: {e}")
            results.append({"asin": asin, "url": url, "image_url": None, "name": None, "error": str(e)})

    success = [r for r in results if r.get("image_url")]
    return jsonify({"ok": True, "products": results, "fetched": len(success)})


@bp.route("/upload-pin/generate-pin-perfect-pro", methods=["POST"])
@login_required
def generate_pin_perfect_pro_route():
    """
    Full Pin Perfect Pro generation: given products + keyword + niche,
    returns title, description, hashtags, alt text, board name, theme,
    subtitle, AND a ready-to-use Ideogram image prompt.
    Also generates the actual image and returns its URL.
    """
    try:
        from config import Config
        from app.ai_writer import generate_pin_perfect_pro
        from app.imagen_api import generate_editorial_pin, generate_pin_perfect_pro_image

        data              = request.get_json()
        niche             = data.get("niche", "beauty")
        keyword           = data.get("keyword", "")
        product_names     = data.get("products", [])
        product_image_urls = data.get("product_images", [])  # GCS URLs from fetch-amazon-images
        board_name        = data.get("board_name", "")
        amazon_url        = data.get("amazon_url", "")
        price             = data.get("price", "")
        image_model       = data.get("image_model", "dalle3")
        shop_url          = Config.benable_url_for_niche(niche)

        # Auto-pick keyword from Pinterest TrendCache if not provided
        if not keyword:
            try:
                from app.keyword_research import pick_best_keyword_for_product
                first_product = product_names[0] if product_names else ""
                keyword = pick_best_keyword_for_product(first_product, niche, "evergreen")
                logger.info(f"Auto-picked keyword: '{keyword}' for product '{first_product}'")
            except Exception as e:
                logger.warning(f"Auto keyword pick failed: {e}")
                keyword = f"amazon {niche} finds 2026"

        # Step 1: Generate copy via Claude (Pin Perfect Pro formula)
        result = generate_pin_perfect_pro(
            product_names=product_names,
            niche=niche,
            trend_keyword=keyword,
            shop_url=shop_url,
            board_name=board_name,
        )
        if not result:
            return jsonify({"ok": False, "error": "Pin Perfect Pro generation failed"}), 500

        # Step 2: Generate pin image
        # If real product photos → editorial compositor (actual product, no catfishing)
        # No photos → Ideogram AI text-to-image as fallback
        image_url = None
        theme    = result.get("theme", keyword.upper()[:20])
        subtitle = result.get("subtitle", "on Amazon")

        if product_image_urls:
            image_url = generate_editorial_pin(
                product_image_urls=product_image_urls,
                theme=theme,
                subtitle=subtitle,
                niche=niche,
                benefits=result.get("benefits") or [],
                product_name=product_names[0] if product_names else "",
                amazon_url=amazon_url,
                price=price,
                image_model=image_model,
            )

        if not image_url and result.get("image_prompt"):
            image_url = generate_pin_perfect_pro_image(result["image_prompt"])

        return jsonify({
            "ok": True,
            "title":        result.get("title", ""),
            "description":  result.get("description", ""),
            "hashtags":     result.get("hashtags", ""),
            "alt_text":     result.get("alt_text", ""),
            "board_name":   result.get("board_name", ""),
            "theme":        result.get("theme", ""),
            "subtitle":     result.get("subtitle", ""),
            "image_prompt": result.get("image_prompt", ""),
            "image_url":    image_url,
        })

    except Exception as e:
        logger.error(f"Pin Perfect Pro generation failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/upload-pin/publish", methods=["POST"])
@login_required
def upload_pin_publish():
    try:
        import requests as req
        from config import Config
        from app import db
        from app.models import Pin

        data        = request.get_json()
        image_b64   = data.get("image_base64", "")
        image_url_direct = data.get("image_url", "")  # pre-hosted GCS URL from AI generation
        title       = data.get("title", "")
        description = data.get("description", "")
        board_name      = data.get("board_name", "")
        niche           = data.get("niche", "beauty")
        trend_keyword   = data.get("trend_keyword", "")
        scheduled_time  = data.get("scheduled_time")

        # Look up board ID from name
        board_id = Config.PINTEREST_BOARDS.get(board_name)
        if not board_id:
            return jsonify({"ok": False, "error": f"Unknown board: {board_name}. Please select a board."}), 400

        blotato_headers = {
            "blotato-api-key": Config.BLOTATO_API_KEY,
            "Content-Type": "application/json",
        }

        # Step 1: Get public image URL
        if image_url_direct:
            # AI-generated image already on GCS — use directly
            public_image_url = image_url_direct
        elif image_b64:
            # Manual upload — encode and push to GCS
            import base64, uuid
            from google.cloud import storage as gcs
            raw_b64 = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64
            image_bytes = base64.b64decode(raw_b64)
            bucket_name = "pinterest-automation-images-814656203168"
            blob_name   = f"upload-pins/{uuid.uuid4().hex}.jpg"
            gcs_client  = gcs.Client()
            bucket      = gcs_client.bucket(bucket_name)
            blob        = bucket.blob(blob_name)
            blob.upload_from_string(image_bytes, content_type="image/jpeg")
            public_image_url = f"https://storage.googleapis.com/pinterest-automation-images-814656203168/{blob_name}"
        else:
            return jsonify({"ok": False, "error": "No image provided. Upload an image or generate one."}), 400

        # Save Pin to DB so we get a real ID → use for /shop/pin/<id> link
        from datetime import datetime, timezone
        scheduled_dt = None
        if scheduled_time:
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
            except Exception:
                pass

        pin = Pin(
            title=title,
            description=description,
            image_url=public_image_url,
            board_name=board_name,
            trend_keyword=trend_keyword,
            status=Pin.STATUS_SCHEDULED if scheduled_dt else Pin.STATUS_POSTED,
            scheduled_for=scheduled_dt,
        )
        db.session.add(pin)
        db.session.flush()  # assigns pin.id without committing yet

        # /shop/pin/<id> is the specific product landing page for this pin
        shop_url = f"https://auragirlessentials.com/shop/pin/{pin.id}"
        pin.shop_url = shop_url

        # Append CTA to description
        if "auragirlessentials.com" not in description and "benable.com" not in description:
            pin.description = description + f"\n{_random_cta()}"
        else:
            pin.description = description

        db.session.commit()
        # Append hashtags + FTC disclosure to description for Pinterest
        description_with_link = pin.description or ""
        hashtags = data.get("hashtags", "").strip()
        if hashtags and hashtags not in description_with_link:
            description_with_link = description_with_link + "\n" + hashtags
        disclosure = "As an Amazon Associate, I may earn from qualifying purchases."
        if disclosure not in description_with_link:
            description_with_link = description_with_link + "\n" + disclosure

        # Step 2: Pass public URL to Blotato media upload
        media_resp = req.post(
            "https://backend.blotato.com/v2/media",
            headers=blotato_headers,
            json={"url": public_image_url},
            timeout=60,
        )
        media_resp.raise_for_status()
        media_url = media_resp.json().get("url")
        if not media_url:
            return jsonify({"ok": False, "error": "Image upload to Blotato failed: " + str(media_resp.json())}), 500

        # Step 3: Post to Pinterest via Blotato
        payload = {
            "post": {
                "accountId": Config.BLOTATO_ACCOUNT_ID,
                "content": {
                    "text": description_with_link,
                    "mediaUrls": [media_url],
                    "platform": "pinterest",
                },
                "target": {
                    "targetType": "pinterest",
                    "boardId": board_id,
                    "title": title,
                    "link": pin.amazon_url or shop_url,  # direct Amazon link if available
                },
            }
        }
        if scheduled_time:
            payload["scheduledTime"] = scheduled_time

        post_resp = req.post(
            "https://backend.blotato.com/v2/posts",
            headers=blotato_headers,
            json=payload,
            timeout=30,
        )
        if not post_resp.ok:
            # Roll back the Pin we saved so we don't leave a ghost record
            try:
                db.session.delete(pin)
                db.session.commit()
            except Exception:
                db.session.rollback()
            return jsonify({"ok": False, "error": f"Blotato error: {post_resp.status_code} — {post_resp.text}"}), 500

        blotato_post_id = post_resp.json().get("postSubmissionId")

        # Mark pin with the blotato submission ID for reference
        try:
            pin.pinterest_pin_id = str(blotato_post_id) if blotato_post_id else None
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({"ok": True, "post_id": blotato_post_id, "pin_id": pin.id, "shop_url": shop_url})

    except Exception as e:
        logger.error(f"Blotato publish failed: {e}", exc_info=True)
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/bulk-upload")
@login_required
def bulk_upload():
    from config import Config
    from datetime import timedelta, date
    boards = list(Config.PINTEREST_BOARDS.keys())

    # Upcoming scheduled pins for the sidebar calendar (next 60 days)
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=60)
    upcoming = (
        Pin.query
        .filter(
            Pin.status.in_([Pin.STATUS_SCHEDULED, Pin.STATUS_APPROVED]),
            Pin.scheduled_for.isnot(None),
            Pin.scheduled_for >= datetime.combine(today, datetime.min.time()),
            Pin.scheduled_for <= datetime.combine(cutoff, datetime.max.time()),
        )
        .order_by(Pin.scheduled_for.asc())
        .all()
    )

    # Group by date (CST = UTC-6) → {date_str: [{hour_cst, minute, title}]}
    from collections import defaultdict
    schedule_by_date = defaultdict(list)
    for p in upcoming:
        if p.scheduled_for:
            cst = p.scheduled_for - timedelta(hours=6)
            date_key = cst.strftime("%Y-%m-%d")
            schedule_by_date[date_key].append({
                "hour": cst.hour,
                "minute": cst.minute,
                "title": (p.title or "Untitled")[:40],
            })

    # Build list of next 21 days with their pins
    calendar_days = []
    for i in range(21):
        d = today + timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        calendar_days.append({
            "key": key,
            "label": d.strftime("%a, %b %-d"),
            "is_today": i == 0,
            "pins": schedule_by_date.get(key, []),
        })

    return render_template("bulk_upload.html", boards=boards, calendar_days=calendar_days)


@bp.route("/bulk-upload/submit", methods=["POST"])
@login_required
def bulk_upload_submit():
    """
    Accept multiple pins at once: images + Pin Perfect Pro text per pin.
    Schedules them spread across a date range at specified times.
    """
    import base64
    import uuid as _uuid
    from datetime import timedelta
    from google.cloud import storage as gcs
    from config import Config

    try:
        data         = request.get_json()
        pins_data    = data.get("pins", [])           # list of {ppp_text, image_b64, board_name}
        start_date   = data.get("start_date", "")     # ISO date string "2026-04-28"
        pins_per_day = int(data.get("pins_per_day", 3))
        post_times   = data.get("post_times", ["09:00", "13:00", "19:00"])  # HH:MM UTC

        if not pins_data:
            return jsonify({"ok": False, "error": "No pins provided"}), 400

        # If no start_date, save as drafts (no schedule)
        save_as_draft = not start_date
        schedule_slots = []
        if not save_as_draft:
            start_dt = datetime.fromisoformat(start_date)
            day = 0
            while len(schedule_slots) < len(pins_data):
                for t in post_times:
                    if len(schedule_slots) >= len(pins_data):
                        break
                    h, m = int(t.split(":")[0]), int(t.split(":")[1])
                    slot = (start_dt + timedelta(days=day)).replace(
                        hour=h, minute=m, second=0, microsecond=0,
                        tzinfo=timezone.utc
                    )
                    schedule_slots.append(slot)
                day += 1

        # Upload images to GCS
        gcs_client = gcs.Client()
        bucket = gcs_client.bucket("pinterest-automation-images-814656203168")

        saved = []
        errors = []

        for i, pin_data in enumerate(pins_data):
            try:
                ppp_text   = pin_data.get("ppp_text", "")
                image_b64  = pin_data.get("image_b64", "")
                board_name = pin_data.get("board_name", "")

                # Prefer pre-filled fields from frontend; fall back to PPP parsing
                title       = pin_data.get("title", "").strip()
                description = pin_data.get("description", "").strip()
                hashtags    = pin_data.get("hashtags", "").strip()
                alt_text    = pin_data.get("alt_text", "").strip()
                link_url    = pin_data.get("link_url", "").strip()
                amazon_url  = pin_data.get("amazon_url", "").strip()

                if not title or not description:
                    parsed = _parse_ppp_output(ppp_text)
                    title       = title or parsed.get("title", f"Pin {i+1}")
                    description = description or parsed.get("description", "")
                    hashtags    = hashtags or parsed.get("hashtags", "")
                    alt_text    = alt_text or parsed.get("alt_text", "")
                    board_name  = board_name or parsed.get("board_name", "Beauty Finds & Skincare")
                else:
                    board_name = board_name or "Beauty Finds & Skincare"

                # Upload image to GCS
                image_url = None
                if image_b64:
                    raw = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64
                    img_bytes = base64.b64decode(raw)
                    blob_name = f"bulk-upload/{_uuid.uuid4().hex}.jpg"
                    blob = bucket.blob(blob_name)
                    blob.upload_from_string(img_bytes, content_type="image/jpeg")
                    image_url = f"https://storage.googleapis.com/pinterest-automation-images-814656203168/{blob_name}"

                # Save pin to DB as draft — user reviews before scheduling
                pin = Pin(
                    title=title,
                    description=description,
                    hashtags=hashtags,
                    alt_text=alt_text,
                    board_name=board_name,
                    image_url=image_url,
                    amazon_url=amazon_url or None,
                    status=Pin.STATUS_DRAFT,
                    scheduled_for=None,
                )
                db.session.add(pin)
                db.session.flush()

                shop_url = link_url or f"https://auragirlessentials.com/shop/pin/{pin.id}"
                pin.shop_url = shop_url
                if not link_url and "auragirlessentials.com" not in description and "benable.com" not in description:
                    pin.description = description + f"\n{_random_cta()}"

                db.session.commit()
                saved.append({
                    "pin_id": pin.id,
                    "title": title,
                    "shop_url": f"/shop/pin/{pin.id}",
                })

            except Exception as e:
                db.session.rollback()
                errors.append({"index": i, "error": str(e)})
                logger.error(f"Bulk upload pin {i} failed: {e}", exc_info=True)

        return jsonify({
            "ok": True,
            "saved": len(saved),
            "errors": len(errors),
            "pins": saved,
            "error_details": errors,
        })

    except Exception as e:
        logger.error(f"Bulk upload submit failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/bulk-upload/submit-scheduled", methods=["POST"])
@login_required
def bulk_upload_submit_scheduled():
    """Save a single pin as STATUS_SCHEDULED with a specific date/time chosen by the user."""
    import base64 as _b64
    import uuid as _uuid
    from google.cloud import storage as _gcs

    try:
        data = request.get_json(force=True)
        pins = data.get("pins", [])
        if not pins:
            return jsonify({"ok": False, "error": "No pin data"}), 400

        pin_data = pins[0]
        title       = pin_data.get("title", "").strip()
        description = pin_data.get("description", "").strip()
        hashtags    = pin_data.get("hashtags", "").strip()
        alt_text    = pin_data.get("alt_text", "").strip()
        amazon_url  = pin_data.get("amazon_url", "").strip()
        board_name  = pin_data.get("board_name", "").strip()
        image_b64   = pin_data.get("image_b64", "")
        scheduled_for_str = pin_data.get("scheduled_for", "").strip()

        if not title or not description or not board_name:
            return jsonify({"ok": False, "error": "Title, description and board are required"}), 400
        if not scheduled_for_str:
            return jsonify({"ok": False, "error": "Scheduled date/time is required"}), 400

        try:
            scheduled_for = _cst_to_utc(scheduled_for_str)
            if not scheduled_for:
                raise ValueError("Invalid date")
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid date/time format"}), 400

        # Upload image to GCS
        image_url = None
        if image_b64:
            raw = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64
            img_bytes = _b64.b64decode(raw)
            bucket_name = "pinterest-automation-images-814656203168"
            blob_name = f"bulk-upload/{_uuid.uuid4().hex}.jpg"
            gcs_client = _gcs.Client()
            bucket = gcs_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(img_bytes, content_type="image/jpeg")
            image_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"

        pin = Pin(
            title=title,
            description=description,
            hashtags=hashtags,
            alt_text=alt_text or None,
            board_name=board_name,
            image_url=image_url,
            amazon_url=amazon_url or None,
            status=Pin.STATUS_SCHEDULED,
            scheduled_for=scheduled_for,
        )
        db.session.add(pin)
        db.session.flush()

        shop_url = f"https://auragirlessentials.com/shop/pin/{pin.id}"
        pin.shop_url = shop_url
        if "auragirlessentials.com" not in description and "benable.com" not in description:
            pin.description = description + f"\n{_random_cta()}"

        db.session.commit()
        return jsonify({
            "ok": True,
            "pins": [{"pin_id": pin.id, "title": title, "shop_url": f"/shop/pin/{pin.id}", "scheduled_for": scheduled_for.isoformat()}],
        })

    except Exception as e:
        logger.error(f"Bulk upload submit-scheduled failed: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


def _parse_ppp_output(text: str) -> dict:
    """
    Parse Pin Perfect Pro output into structured fields.
    Handles the exact format Pin Perfect Pro produces.
    """
    import re

    def extract_section(label_patterns, txt):
        for pat in label_patterns:
            m = re.search(pat + r'\s*\n+([\s\S]+?)(?=\n---|\n##|\n###|\Z)', txt, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    # Title — look for "Pin Title" section
    title = extract_section([r'##[^#]*Pin Title[^#\n]*', r'\*\*Pin Title'], text)
    # Strip markdown bold/italic and leading dashes
    title = re.sub(r'\*+', '', title).strip().lstrip('-').strip()
    # Take just the first line
    title = title.split('\n')[0].strip()

    # Description
    description = extract_section([r'##[^#]*Pin Description[^#\n]*', r'\*\*Pin Description'], text)
    description = re.sub(r'\*+', '', description).strip()
    description = description.split('\n')[0].strip() if description else ""

    # Alt text
    alt_text = extract_section([r'##[^#]*Alt Text[^#\n]*', r'\*\*Alt Text'], text)
    alt_text = re.sub(r'\*+', '', alt_text).strip().split('\n')[0].strip()

    # Board name
    board_name = extract_section([r'##[^#]*Board Name[^#\n]*', r'\*\*Board Name'], text)
    board_name = re.sub(r'\*+', '', board_name).strip().split('\n')[0].strip()

    # Hashtags — from Supporting Keywords section, convert to #hashtags
    keywords_raw = extract_section([r'###[^#]*Supporting Keywords', r'\*\*Supporting Keywords'], text)
    hashtags = ""
    if keywords_raw:
        kws = [k.strip().lstrip('-').strip() for k in re.split(r'[,\n]', keywords_raw) if k.strip()]
        hashtags = " ".join(f"#{kw.replace(' ', '').lower()}" for kw in kws if kw)

    # Also grab primary keyword as a hashtag
    primary_kw = extract_section([r'##[^#]*Primary Keyword', r'\*\*Primary Keyword'], text)
    primary_kw = re.sub(r'\*+', '', primary_kw).strip().split('\n')[0].strip()
    if primary_kw:
        primary_tag = f"#{primary_kw.replace(' ', '').lower()}"
        if primary_tag not in hashtags:
            hashtags = primary_tag + " " + hashtags

    return {
        "title": title,
        "description": description,
        "alt_text": alt_text,
        "board_name": board_name,
        "hashtags": hashtags.strip(),
    }


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
    from config import Config
    redirect_uri = (
        Config.PINTEREST_REDIRECT_URI
        or url_for("main.pinterest_callback", _external=True)
    ).replace("http://", "https://")
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
        from config import Config
        redirect_uri = (
            Config.PINTEREST_REDIRECT_URI
            or url_for("main.pinterest_callback", _external=True)
        ).replace("http://", "https://")
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


def _suggest_boards_from_trends(trends):
    """
    Cluster trend keywords into Pinterest board suggestions.
    Returns list of {name, emoji, reason, keywords, priority}
    """
    if not trends:
        return []

    all_kws = [t.keyword.lower() for t in trends]

    # Board clusters: each has trigger words and a board template
    clusters = [
        {
            "triggers": ["mother", "mom", "gift", "mothers day", "gift set", "gift idea"],
            "name": "Mother's Day Gift Ideas 🎁",
            "emoji": "🎁",
            "reason": "Mother's Day is May 11 — this board peaks right now and drives serious gift clicks.",
            "priority": 1,
        },
        {
            "triggers": ["spf", "sunscreen", "self tanner", "bronzer", "sun", "tanning", "summer skin"],
            "name": "Summer Skin Essentials ☀️",
            "emoji": "☀️",
            "reason": "Sun care searches spike May–August. High commission + high price products.",
            "priority": 1,
        },
        {
            "triggers": ["plant", "garden", "flower", "indoor plant", "outdoor", "landscaping", "perennial", "lily", "hydrangea"],
            "name": "Garden & Plant Inspo 🌿",
            "emoji": "🌿",
            "reason": "Plants are trending in your analytics — home & garden has strong spring engagement.",
            "priority": 2,
        },
        {
            "triggers": ["serum", "retinol", "vitamin c", "niacinamide", "skincare routine", "moisturizer", "cleanser", "toner", "glow"],
            "name": "Skincare That Actually Works 💧",
            "emoji": "💧",
            "reason": "Skincare routines are evergreen and your highest-commission category.",
            "priority": 1,
        },
        {
            "triggers": ["makeup", "foundation", "concealer", "blush", "mascara", "lip", "lip gloss", "lip oil", "eyeshadow"],
            "name": "Makeup Finds Under $50 💄",
            "emoji": "💄",
            "reason": "Affordable makeup drives high click volume on Pinterest.",
            "priority": 2,
        },
        {
            "triggers": ["collagen", "supplement", "probiotic", "wellness", "protein", "vitamin", "gut health"],
            "name": "Wellness & Supplements ✨",
            "emoji": "✨",
            "reason": "Wellness supplements are a growing category — lower commission but high search volume.",
            "priority": 3,
        },
        {
            "triggers": ["home decor", "candle", "vase", "aesthetic", "room decor", "wall art", "cozy", "living room"],
            "name": "Aesthetic Home Finds 🏠",
            "emoji": "🏠",
            "reason": "Home decor drives strong saves and repins — great for reach.",
            "priority": 2,
        },
        {
            "triggers": ["hair", "hair mask", "hair oil", "shampoo", "frizz", "curly", "hair care", "scalp"],
            "name": "Hair Care Essentials 💇‍♀️",
            "emoji": "💇‍♀️",
            "reason": "Hair care spikes in summer due to heat and humidity searches.",
            "priority": 2,
        },
        {
            "triggers": ["fragrance", "perfume", "body mist", "body spray", "scent"],
            "name": "Perfumes & Fragrances 🌸",
            "emoji": "🌸",
            "reason": "Fragrance is a high-commission luxury beauty category.",
            "priority": 2,
        },
        {
            "triggers": ["body care", "body butter", "body oil", "body lotion", "body scrub", "body wash"],
            "name": "Body Care Routine 🛁",
            "emoji": "🛁",
            "reason": "Body care searches peak in spring and summer — links well to Amazon finds.",
            "priority": 2,
        },
    ]

    keyword_set = set(all_kws)
    suggestions = []

    for cluster in clusters:
        matched_kws = []
        for trigger in cluster["triggers"]:
            for kw in all_kws:
                if trigger in kw or kw in trigger:
                    if kw not in matched_kws:
                        matched_kws.append(kw)
        if matched_kws:
            suggestions.append({
                "name": cluster["name"],
                "emoji": cluster["emoji"],
                "reason": cluster["reason"],
                "priority": cluster["priority"],
                "keywords": matched_kws[:6],
                "match_count": len(matched_kws),
            })

    suggestions.sort(key=lambda s: (s["priority"], -s["match_count"]))
    return suggestions


@bp.route("/test-scrape")
@login_required
def test_scrape():
    from config import Config as _Cfg
    import os
    app_url = os.getenv("APP_URL", "https://pinterest-automation-814656203168.us-central1.run.app")
    return render_template("test_scrape.html", app_url=app_url, dashboard_password=_Cfg.DASHBOARD_PASSWORD)


@bp.route("/trends/upload-screenshots/<int:entry_id>", methods=["POST"])
@login_required
def trends_upload_screenshots(entry_id):
    """Save (or replace) screenshots on an existing TrendEntry."""
    import json as _json
    from app.models import TrendEntry
    entry = TrendEntry.query.get_or_404(entry_id)
    data = request.get_json(force=True) or {}
    images = data.get("images") or []
    if not images:
        return jsonify({"ok": False, "error": "No images provided."})
    existing = _json.loads(entry.screenshots_b64 or "[]")
    combined = existing + images
    entry.screenshots_b64 = _json.dumps(combined[:6])
    db.session.commit()
    return jsonify({"ok": True, "count": len(combined[:6])})


@bp.route("/trends/clear-screenshots/<int:entry_id>", methods=["POST"])
@login_required
def trends_clear_screenshots(entry_id):
    from app.models import TrendEntry
    entry = TrendEntry.query.get_or_404(entry_id)
    entry.screenshots_b64 = "[]"
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/trends/set-priority/<int:entry_id>", methods=["POST"])
@login_required
def trends_set_priority(entry_id):
    from app.models import TrendEntry
    entry = TrendEntry.query.get_or_404(entry_id)
    data = request.get_json(force=True) or {}
    priority = data.get("priority", "medium")
    if priority not in ("high", "medium", "low"):
        return jsonify({"ok": False, "error": "Invalid priority"})
    entry.priority = priority
    db.session.commit()
    return jsonify({"ok": True, "priority": priority})


@bp.route("/trends/generate-brief/<int:entry_id>", methods=["POST"])
@login_required
def trends_generate_brief(entry_id):
    """Generate and save an AI Strategy Brief for an existing TrendEntry on demand."""
    import json as _json
    from app.models import TrendEntry
    entry = TrendEntry.query.get_or_404(entry_id)
    sq = entry.sq_list()
    tp = entry.tp_list()
    if not sq and not tp:
        return jsonify({"ok": False, "error": "No keywords or products saved for this entry."})
    try:
        import anthropic as _anthropic
        from config import Config as _Cfg
        _client = _anthropic.Anthropic(api_key=_Cfg.ANTHROPIC_API_KEY)

        # Accept optional metrics context passed from import script
        req_data = request.get_json(force=True, silent=True) or {}
        metrics_context = (req_data.get("metrics_context") or "").strip()

        metrics_section = ""
        if metrics_context:
            metrics_section = f"\n\nAggregate Pinterest Trends metrics (30-day growth vs prior 30 days):\n{metrics_context}\n"

        # Load screenshots first so prompt can reference them
        content = []
        screenshots = []
        if entry.screenshots_b64:
            try:
                screenshots = _json.loads(entry.screenshots_b64) or []
            except Exception:
                screenshots = []

        text_prompt = f"""You are a Pinterest affiliate marketing strategist for Aura Girl Essentials, an Amazon affiliate account focused on beauty, home decor, and wellness.

Commission rates: 10% luxury beauty, 3% home decor, 1% fitness/general.
PRIORITY: Always favor products with 10% commission (luxury beauty) — these make the most money per click.

Pinterest Trends data for category: {entry.category}

Top search queries (what people are actively searching):
{', '.join(sq) if sq else 'none'}

Top trending products on Pinterest right now:
{', '.join(tp) if tp else 'none'}{metrics_section}
{'Screenshots of the Pinterest Trends page are attached — use them to read outbound click data, trend graphs, and demographics.' if screenshots else ''}

Give a focused strategic analysis covering:
1. **Audience intent** — who is this person, what do they want, what will make them click buy?
2. **Top products to pin (10% commission first)** — from the product list above, identify which are luxury beauty (10% commission) and rank them by click/buy potential. Be specific about which products to prioritize and why.
3. **Pin angle** — what transformation or emotion should the pin lead with to drive outbound clicks?
4. **Keywords to prioritize** — top 3-5 from search queries to use in pin titles
5. **Outbound click signals** — {'read the screenshots: note the trend graph direction, demographics (age/gender), and which signals indicate high buyer intent.' if screenshots else 'use metrics and keyword intent to assess buyer readiness.' if metrics_context else 'assess from keyword phrasing which queries indicate someone ready to buy.'}
6. **Worth it?** — given 10% commission on luxury beauty, is this category high priority?

Be specific, tactical, direct. No fluff. Use markdown headers."""

        if screenshots:
            for img in screenshots[:6]:
                mime = (img.get("mime_type") or "image/png").strip() or "image/png"
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": img["image"]},
                })
            content.append({"type": "text", "text": text_prompt})
        else:
            content = text_prompt

        msg = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": content}],
        )
        insight = msg.content[0].text.strip()
        entry.insight = insight
        db.session.commit()
        return jsonify({"ok": True, "insight": insight})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/trends/preview-insight", methods=["POST"])
@login_required
def trends_preview_insight():
    """Generate an AI Strategy Brief preview without saving anything.
    Accepts: category, search_queries (list), top_products (list), full_page (raw text).
    Parses full_page the same way trends_paste() does to extract keywords/products.
    """
    import re as _re
    data = request.get_json(force=True) or {}
    category   = data.get("category", "").strip() or "Unknown"
    sq_sample  = list(data.get("search_queries", []))
    tp_sample  = list(data.get("top_products", []))
    full_page  = data.get("full_page", "").strip()

    # Parse full page text to extract more keywords/products (mirrors trends_paste logic)
    if full_page:
        seen = {k.lower() for k in sq_sample + tp_sample}
        for line in full_page.split('\n'):
            line = line.strip()
            if not line or line.startswith('http'):
                continue
            if len(line) > 25 and len(line) <= 150:
                # Likely a product name
                if line.lower() not in seen and len(tp_sample) < 15:
                    seen.add(line.lower())
                    tp_sample.append(line)
            elif 3 <= len(line) <= 50:
                kw = line.lower()
                if kw not in seen and len(sq_sample) < 20:
                    seen.add(kw)
                    sq_sample.append(kw)

    if not sq_sample and not tp_sample:
        return jsonify({"ok": False, "error": "No data found — paste your search queries or full page dump first."})

    try:
        import anthropic as _anthropic
        from config import Config as _Cfg
        _client = _anthropic.Anthropic(api_key=_Cfg.ANTHROPIC_API_KEY)
        _prompt = f"""You are a Pinterest affiliate marketing strategist for Aura Girl Essentials, an Amazon affiliate account focused on beauty, home decor, and wellness. Commission rates: 10% luxury beauty, 3% home decor, 1% fitness/general.

Pinterest Trends data for category: {category}

Top search queries (what people are actively searching):
{', '.join(sq_sample) if sq_sample else 'none'}

Top trending products on Pinterest right now:
{', '.join(tp_sample) if tp_sample else 'none recorded'}

Give a focused strategic analysis covering:
1. **Audience intent** — what is this person trying to achieve/feel?
2. **Best products to pin** — which trending products have highest click/buy potential and why?
3. **Pin angle** — what transformation or emotion should the pin lead with?
4. **Keywords to prioritize** — top 3-5 from search queries to use in pin titles
5. **Worth it?** — given our commission structure, should we prioritize or deprioritize this category?

Be specific, tactical, direct. No fluff. Use markdown headers."""
        _msg = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": _prompt}],
        )
        return jsonify({"ok": True, "insight": _msg.content[0].text.strip()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/trends/extract-screenshot", methods=["POST"])
@login_required
def trends_extract_screenshot():
    """
    Accept one or more base64-encoded screenshots of the Pinterest Trends page.
    Accepts either:
      { image, mime_type, category }          — single image (legacy)
      { images: [{image, mime_type}], category } — multiple images
    Extracts keywords from all images in one Claude call, then generates AI brief.
    Returns: { ok, search_queries: [...], insight: "..." }
    """
    data = request.get_json(force=True) or {}
    category = data.get("category", "").strip() or "Unknown"

    # Build list of {image, mime_type} dicts — support both single and multi
    images = data.get("images") or []
    if not images and data.get("image"):
        images = [{"image": data["image"], "mime_type": data.get("mime_type", "image/png")}]

    if not images:
        return jsonify({"ok": False, "error": "No images provided."})

    try:
        import anthropic as _anthropic
        from config import Config as _Cfg
        _client = _anthropic.Anthropic(api_key=_Cfg.ANTHROPIC_API_KEY)

        # Build content blocks — one image block per screenshot + one instruction at the end
        content = []
        for idx, img in enumerate(images[:6], 1):  # cap at 6
            mime = (img.get("mime_type") or "image/png").strip() or "image/png"
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": img["image"]},
            })
        content.append({
            "type": "text",
            "text": (
                f"These are {len(images)} screenshot(s) of the Pinterest Trends page for the '{category}' category. "
                "Please extract two things from across all the screenshots:\n\n"
                "1. SEARCH QUERIES: All visible search query keywords/phrases — short keyword phrases people are searching on Pinterest, "
                "often in a list or grid labeled 'Search Queries', 'Top Searches', or similar.\n\n"
                "2. PRODUCT NAMES: All visible product names — these appear in 'Top Products' or 'Explore Top Products' sections, "
                "usually longer phrases like actual product titles (e.g. 'Perricone MD High Potency Retinol Recovery Overnight Moisturizer').\n\n"
                "Return your answer in EXACTLY this format, nothing else:\n"
                "SEARCH_QUERIES:\n"
                "keyword one\n"
                "keyword two\n"
                "...\n"
                "PRODUCT_NAMES:\n"
                "Full Product Name One\n"
                "Full Product Name Two\n"
                "...\n\n"
                "Include every item you can read across all images. "
                "If a section is not visible in any screenshot, leave it empty but still include the header."
            ),
        })

        # Step 1: Extract keywords + product names from all screenshots in one call
        extract_msg = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": content}],
        )

        raw_text = extract_msg.content[0].text.strip()

        # Parse sections
        search_queries = []
        product_names = []
        current_section = None
        seen_kw = set()
        seen_prod = set()

        for line in raw_text.split('\n'):
            line = line.strip()
            if line.startswith('SEARCH_QUERIES:'):
                current_section = 'kw'
                continue
            elif line.startswith('PRODUCT_NAMES:'):
                current_section = 'prod'
                continue
            elif not line:
                continue

            cleaned = line.strip('-•').strip()
            if not cleaned or len(cleaned) < 2:
                continue

            if current_section == 'kw':
                kw = cleaned.lower()
                if len(kw) <= 80 and kw not in seen_kw and kw not in ('search queries', 'top searches', 'keywords', category.lower()):
                    seen_kw.add(kw)
                    search_queries.append(kw)
            elif current_section == 'prod':
                if len(cleaned) <= 250 and cleaned.lower() not in seen_prod:
                    seen_prod.add(cleaned.lower())
                    product_names.append(cleaned)

        # No AI brief generated here — saves API credits.
        # Brief can be generated on-demand via the Preview Insight button on the entry card.
        return jsonify({
            "ok": True,
            "search_queries": search_queries,
            "top_products": product_names,
            "insight": "",
        })

    except Exception as e:
        logger.error(f"extract-screenshot error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/trends")
@login_required
def trends():
    from app.models import TrendEntry
    cached = TrendCache.query.order_by(TrendCache.score.desc(), TrendCache.cached_at.desc()).limit(100).all()
    board_suggestions = _suggest_boards_from_trends(cached)
    entries = TrendEntry.query.order_by(TrendEntry.saved_at.desc()).all()
    return render_template("trends.html", trends=cached[:50], analysis=None, board_suggestions=board_suggestions, entries=entries)


@bp.route("/trends/delete-entry/<int:entry_id>", methods=["POST"])
@login_required
def trends_delete_entry(entry_id):
    from app.models import TrendEntry
    entry = TrendEntry.query.get(entry_id)
    if entry:
        db.session.delete(entry)
        db.session.commit()
    return jsonify({"ok": True})


@bp.route("/trends/update-products/<int:entry_id>", methods=["POST"])
@login_required
def trends_update_products(entry_id):
    """Add or replace top_products for an existing TrendEntry."""
    import json as _json
    from app.models import TrendEntry
    data = request.get_json(force=True) or {}
    products = [p.strip() for p in data.get("products", []) if p.strip()]
    entry = TrendEntry.query.get_or_404(entry_id)
    # Merge with existing (deduplicate)
    existing = entry.tp_list()
    merged = list(dict.fromkeys(existing + products))  # preserve order, deduplicate
    entry.top_products = _json.dumps(merged)
    db.session.commit()
    return jsonify({"ok": True, "count": len(merged), "products": merged})


@bp.route("/trends/extract-pin-products", methods=["POST"])
@login_required
def trends_extract_pin_products():
    """Fetch Pinterest pin URLs and extract product names from JSON-LD."""
    import re
    import requests as http_requests

    payload = request.get_json(force=True) or {}
    urls = payload.get("urls", [])

    if not urls:
        return jsonify({"ok": False, "error": "No URLs provided."})

    UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    products = []
    seen = set()

    for url in urls[:60]:  # cap at 60
        url = url.strip()
        if "pinterest.com/pin" not in url:
            continue
        try:
            resp = http_requests.get(url, headers={"User-Agent": UA}, timeout=10)
            html = resp.text
            # Extract JSON-LD headline
            m = re.search(r'application/ld\+json">(.*?)</script>', html, re.DOTALL)
            if m:
                import json as _json
                d = _json.loads(m.group(1))
                name = d.get("headline") or d.get("sharedContent", {}).get("headline", "")
                name = name.strip()
                if name and name not in seen and len(name) > 3:
                    seen.add(name)
                    products.append(name)
        except Exception as e:
            logger.warning(f"Pin fetch failed for {url}: {e}")
            continue

    if not products:
        return jsonify({"ok": False, "error": "Could not extract product names from those pins."})

    return jsonify({"ok": True, "products": products})


@bp.route("/trends/bookmarklet-import", methods=["POST", "OPTIONS"])
def trends_bookmarklet_import():
    """
    Accept data POSTed by the Pinterest Trends bookmarklet.
    Auth: X-Import-Token header must match DASHBOARD_PASSWORD.
    CORS open so the bookmarklet can POST from trends.pinterest.com.
    """
    from flask import make_response
    import json as _json
    import re
    import requests as http_requests

    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type, X-Import-Token",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
    }

    if request.method == "OPTIONS":
        return make_response("", 204, cors_headers)

    # Token auth (no session needed — runs cross-origin from Pinterest)
    from config import Config as _Cfg
    token = request.headers.get("X-Import-Token", "")
    if not token or token != (_Cfg.DASHBOARD_PASSWORD or ""):
        return make_response(jsonify({"ok": False, "error": "Unauthorized"}), 401, cors_headers)

    payload  = request.get_json(force=True) or {}
    category = (payload.get("category") or "").strip()
    keywords = [k.strip() for k in (payload.get("keywords") or []) if k.strip()]
    metrics  = payload.get("metrics") or {}
    pins     = payload.get("pins") or []

    if not category or not keywords:
        return make_response(jsonify({"ok": False, "error": "Missing category or keywords"}), 400, cors_headers)

    # Fuzzy-match to existing TrendEntry
    from app.models import TrendEntry
    def _fuzzy(cat, entries):
        cl = cat.lower().replace("&", "and").replace(" ", "")
        for eid, name in entries:
            nl = name.lower().replace("&", "and").replace(" ", "")
            if cl in nl or nl in cl:
                return eid, name
            cw = set(re.findall(r"\w+", cat.lower()))
            nw = set(re.findall(r"\w+", name.lower()))
            if len(cw & nw) / max(len(cw), 1) >= 0.6:
                return eid, name
        return None, None

    all_entries = [(str(e.id), e.category) for e in TrendEntry.query.all()]
    entry_id, matched_name = _fuzzy(category, all_entries)
    if not entry_id:
        return make_response(
            jsonify({"ok": False, "error": f'No entry found for "{category}". Add it in Trends first.'}),
            404, cors_headers
        )

    entry = TrendEntry.query.get(int(entry_id))

    # Merge keywords (never replace existing)
    merged_sq = list(dict.fromkeys(entry.sq_list() + [k.lower() for k in keywords]))
    entry.search_queries = _json.dumps(merged_sq)

    # Fetch product names from pin URLs server-side
    new_products = []
    if pins:
        UA   = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        seen = set(entry.tp_list())
        for url in pins[:20]:
            if "pinterest.com/pin" not in url:
                continue
            try:
                r    = http_requests.get(url, headers={"User-Agent": UA}, timeout=8)
                m    = re.search(r'application/ld\+json">(.*?)</script>', r.text, re.DOTALL)
                if m:
                    d    = _json.loads(m.group(1))
                    name = (d.get("headline") or d.get("name", "")).strip()
                    if name and name not in seen and len(name) > 5:
                        seen.add(name)
                        new_products.append(name)
            except Exception:
                continue

    # Merge products (never replace)
    merged_tp = list(dict.fromkeys(entry.tp_list() + new_products))
    if new_products:
        entry.top_products = _json.dumps(merged_tp)

    db.session.commit()

    # Build metrics text for brief prompt
    metric_labels = {"OUTBOUND_CLICK": "Outbound clicks", "ENGAGEMENT": "Engagement", "SAVE": "Saves"}
    metrics_text  = "\n".join(f"{metric_labels.get(k,k)}: {v} growth (last 30 days)" for k, v in metrics.items())

    # Generate AI brief
    brief_ok = False
    try:
        import anthropic as _anthropic
        _client = _anthropic.Anthropic(api_key=_Cfg.ANTHROPIC_API_KEY)
        sq = entry.sq_list()
        tp = entry.tp_list()
        ms = f"\n\nAggregate metrics (30-day growth):\n{metrics_text}\n" if metrics_text else ""
        prompt = f"""You are a Pinterest affiliate marketing strategist for Aura Girl Essentials (Amazon affiliate: beauty, home decor, wellness). Commission: 10% luxury beauty, 3% home decor, 1% general.

Pinterest Trends category: {entry.category}
Search queries: {', '.join(sq) if sq else 'none'}
Trending products: {', '.join(tp[:20]) if tp else 'none'}{ms}

Strategic analysis:
1. **Audience intent** — what is this person trying to achieve?
2. **Best products to pin** — highest click/buy potential and why?
3. **Pin angle** — what transformation should the pin lead with?
4. **Keywords to prioritize** — top 3-5 for pin titles
5. **Outbound click signals** — {'use metrics to assess buyer intent; note most transactional query phrasings' if metrics_text else 'assess from keyword intent'}
6. **Worth it?** — given commission structure, prioritize or deprioritize?

Specific, tactical, direct. No fluff. Markdown headers."""
        msg = _anthropic.Anthropic(api_key=_Cfg.ANTHROPIC_API_KEY).messages.create(
            model="claude-sonnet-4-6", max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        entry.insight = msg.content[0].text.strip()
        db.session.commit()
        brief_ok = True
    except Exception as e:
        logger.warning(f"Bookmarklet brief generation failed: {e}")

    return make_response(jsonify({
        "ok":           True,
        "matched":      matched_name,
        "keywords":     len(merged_sq),
        "products":     len(merged_tp),
        "new_products": len(new_products),
        "brief":        brief_ok,
    }), 200, cors_headers)


@bp.route("/trends/paste", methods=["POST"])
@login_required
def trends_paste():
    """
    Accept pasted text from Pinterest Analytics search queries section.
    Extracts keywords (one per line, comma-separated, or raw block text),
    saves to TrendCache (merges with existing), and archives raw paste to disk.
    """
    import re
    import os

    payload = request.get_json(force=True) or {}
    search_queries_raw = (payload.get("text") or "").strip()
    products_raw       = (payload.get("products") or "").strip()
    full_page_raw      = (payload.get("full_page") or "").strip()
    category_label     = (payload.get("category") or "pinterest analytics").strip()
    saved_images       = payload.get("images") or []  # [{image: base64, mime_type: str}]

    if not search_queries_raw and not products_raw and not full_page_raw:
        return jsonify({"ok": False, "error": "Paste something into at least one box."})

    def clean_kw(line, max_len=80):
        kw = line.strip().lower()
        kw = re.sub(r'[^\w\s\-]', '', kw).strip()
        return kw if (kw and 3 <= len(kw) <= max_len) else ""

    def clean_product(line):
        """For product names — preserve case, allow longer strings, strip only leading/trailing noise."""
        p = line.strip()
        if not p or len(p) < 3:
            return ""
        # Truncate very long names at a natural word boundary around 150 chars
        if len(p) > 150:
            p = p[:150].rsplit(' ', 1)[0]
        return p

    ui_noise = re.compile(
        r'^(copy keywords?|view (less|more|all product categor.*)|people engaging|people interested|'
        r'people interested in .* are also interested.*|also interested in these.*|'
        r'related|other product categor.*|performance|demographics|forecast.*|outbound clicks?|'
        r'engagement|pin saves?|key metric.*|top products on pinterest|products based on.*|explore top.*|'
        r'amazon|walmart|target|the home depot|etsy|lowe.*|kroger.*|fast growing trees|'
        r'great garden plants.*|heirloom|seedssun|ejuqi|seed therapy|opens a new tab|'
        r'opens a new tab|; opens a new tab|opens a|; opens|\; opens|'
        r'volume indexed.*|date range|past \d+.*|age|gender|female|male|'
        r'unspecified|relative interest.*|view all.*|review (how|other).*|'
        r'expected to grow.*|forecast magic.*|age and gender.*|distribution of pinners.*|'
        r'people engaging with.*|commonly search for.*|also interested.*|'
        r'product category|product categories|beta|region|united states|us only|'
        r'search queries|top products|relative interest over time|'
        r'weekly trend|monthly trend|trending now|trending up|trending down|'
        r'high confidence|medium confidence|low confidence|'
        r'showing \d+.*|preview|merchant|product name|past \d+ months?|'
        r'review other.*|key metric.*|pinterest top products.*|'
        r'plant addicts|nature hills|fast growing trees|gurney.*|burpee.*|'
        r'etsy|wayfair|overstock|homedepot|lowes|costco|'
        r'southern europe.*|northern europe.*|eastern europe.*|nordic countries.*|'
        r'latin americ.*|western europe.*|germanic.*|benelux.*|'
        r'great britain.*|hispanic latin.*|'
        r'aura girl.*|pinbot|pinterest|[;,]\s*opens.*|\d+%|\d+[km]?|\s*)$',
        re.IGNORECASE
    )

    seen = set()

    # ── Box 2: Search queries (user pasted exact section — trust every line) ──
    search_queries_kws = []
    for line in re.split(r'[\n,;]+', search_queries_raw):
        kw = clean_kw(line)
        if kw and kw not in seen:
            seen.add(kw)
            search_queries_kws.append(kw)

    # ── Box 3: Top products (use clean_product — longer names, preserve case) ──
    top_products_kws = []
    for line in re.split(r'[\n;]+', products_raw):
        # Skip raw URLs — those should have been extracted already
        if line.strip().startswith('http'):
            continue
        kw = clean_product(line)
        if kw and kw.lower() not in seen and not ui_noise.match(kw):
            seen.add(kw.lower())
            top_products_kws.append(kw)

    # ── Full page dump: auto-detect Search queries and Top products sections ──
    full_page_sq_kws = []
    full_page_context_kws = []
    if full_page_raw:
        # Try to find "Search queries" section
        sq_match = re.search(
            r'(?:search queries?[^\n]*\n(?:people engaging[^\n]*\n)?(?:copy keywords?[^\n]*\n)?)([\s\S]+?)(?=\n(?:other product|people interested|demographics|performance|related to|view less|view all|top products|$))',
            full_page_raw, re.IGNORECASE
        )
        if sq_match:
            for line in re.split(r'[\n,;]+', sq_match.group(1)):
                kw = clean_kw(line)
                if kw and kw not in seen and not ui_noise.match(kw):
                    seen.add(kw)
                    full_page_sq_kws.append(kw)

        # Try to find "Top products" section in full page — route to top_products_kws
        tp_match = re.search(
            r'top products?\b[^\n]*\n([\s\S]+?)(?=\n\s*(?:other product|people interested|demographics|performance|related to|view less|view all|search quer|$))',
            full_page_raw, re.IGNORECASE
        )
        if tp_match:
            for line in tp_match.group(1).split('\n'):
                p = clean_product(line)
                if p and p.lower() not in seen and not ui_noise.match(p) and not line.strip().startswith('http'):
                    seen.add(p.lower())
                    top_products_kws.append(p)

        # Everything else from the full page:
        # - Long lines (>25 chars) → likely product names → route to top_products
        # - Short lines → keyword context
        for line in re.split(r'[\n]+', full_page_raw):
            line = line.strip()
            if not line or line.startswith('http'):
                continue
            if len(line) > 25:
                # Looks like a product name — use clean_product
                p = clean_product(line)
                if p and p.lower() not in seen and not ui_noise.match(p):
                    seen.add(p.lower())
                    top_products_kws.append(p)
            else:
                kw = clean_kw(line, max_len=50)
                if kw and kw not in seen and not ui_noise.match(kw):
                    seen.add(kw)
                    full_page_context_kws.append(kw)

    # ── Category auto-detect from full page if not provided ──
    if (not category_label or category_label == "pinterest analytics") and full_page_raw:
        # First non-noise line is usually the category
        for line in full_page_raw.split('\n'):
            candidate = line.strip()
            if candidate and 2 < len(candidate) < 40 and not ui_noise.match(candidate.lower()):
                category_label = candidate
                break

    # Priority order: explicit search queries > full page search queries > top products > full page context
    keywords = search_queries_kws + full_page_sq_kws + top_products_kws + full_page_context_kws

    if not keywords:
        return jsonify({"ok": False, "error": "No valid keywords found. Check what you pasted."})

    # ── Archive raw paste to disk (dated, never deleted) ──
    archive_dir = os.path.join(os.path.dirname(__file__), "..", "trend_archive")
    os.makedirs(archive_dir, exist_ok=True)
    from datetime import date
    today_str = date.today().strftime("%Y-%m-%d")
    archive_path = os.path.join(archive_dir, f"{today_str}_{category_label.replace(' ','_').lower()}.txt")
    # Append so multiple pastes same day don't overwrite each other
    with open(archive_path, "a", encoding="utf-8") as f:
        f.write(f"\n=== {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} — {category_label} ===\n")
        f.write(f"[SEARCH QUERIES]\n{search_queries_raw}\n[TOP PRODUCTS]\n{products_raw}\n")

    # ── Merge into TrendCache ──
    # Search queries: 100→80, top products hints: 60→20
    sq_set = set(search_queries_kws)
    sq_total = len(search_queries_kws) or 1
    prod_total = len(top_products_kws) or 1
    saved = 0

    for i, kw in enumerate(search_queries_kws):
        score = round(100 - (20 * i / sq_total), 1)
        existing = TrendCache.query.filter_by(keyword=kw).first()
        if existing:
            if score > (existing.score or 0):
                existing.score = score
                existing.cached_at = datetime.now(timezone.utc)
        else:
            db.session.add(TrendCache(keyword=kw, category=_guess_category(kw), score=score, cached_at=datetime.now(timezone.utc)))
            saved += 1

    def _save_kws(kw_list, score_high, score_low):
        nonlocal saved
        total_n = len(kw_list) or 1
        for i, kw in enumerate(kw_list):
            score = round(score_high - ((score_high - score_low) * i / total_n), 1)
            existing = TrendCache.query.filter_by(keyword=kw).first()
            if existing:
                if score > (existing.score or 0):
                    existing.score = score
                    existing.cached_at = datetime.now(timezone.utc)
            else:
                db.session.add(TrendCache(keyword=kw, category=_guess_category(kw), score=score, cached_at=datetime.now(timezone.utc)))
                saved += 1

    _save_kws(top_products_kws,      60, 20)
    _save_kws(full_page_sq_kws,      85, 70)   # full page search queries: slightly below explicit box
    _save_kws(full_page_context_kws, 40, 10)   # full page context: lowest priority

    db.session.commit()

    # AI brief skipped on save — generated on demand via Generate Brief button on entry card
    insight = ""

    # ── Save a dated TrendEntry for the library ──
    import json as _json
    from app.models import TrendEntry
    # Save screenshots as base64 JSON (cap at 6 to keep DB size reasonable)
    screenshots_json = _json.dumps(saved_images[:6]) if saved_images else None

    entry = TrendEntry(
        category        = category_label or "Uncategorized",
        search_queries  = _json.dumps(search_queries_kws + full_page_sq_kws),
        top_products    = _json.dumps(top_products_kws),
        full_page_kws   = _json.dumps(full_page_context_kws[:30]),
        insight         = insight,
        total_keywords  = len(keywords),
        screenshots_b64 = screenshots_json,
    )
    db.session.add(entry)
    db.session.commit()

    # ── Build by_category for understanding panel ──
    from collections import defaultdict

    def _categorize_kw(kw):
        if any(w in kw for w in ["plant", "garden", "flower", "lily", "hydrangea", "perennial", "landscap", "grass", "fertiliz", "rose", "cherry tree", "shrub", "tree", "outdoor plant", "potted"]):
            return "garden"
        return _guess_category(kw)

    by_category = defaultdict(list)
    for kw in keywords:
        by_category[_categorize_kw(kw)].append(kw)

    return jsonify({
        "ok": True,
        "saved": saved,
        "total": len(keywords),
        "entry_id": entry.id,
        "category": category_label,
        "search_queries": search_queries_kws + full_page_sq_kws,
        "top_products": top_products_kws,
        "full_page_context": full_page_context_kws[:20],
        "by_category": {k: v for k, v in by_category.items()},
        "ignored": [],
    })


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

    cached = TrendCache.query.order_by(TrendCache.score.desc()).limit(100).all()
    board_suggestions = _suggest_boards_from_trends(cached)
    return render_template("trends.html", trends=cached[:50], analysis=analysis, board_suggestions=board_suggestions)


# ── Public shop pages ─────────────────────────────────────────────────────

SHOP_NICHES = {
    "glam-home": {
        "title": "Glam Home Decor Finds",
        "description": "Curated home decor picks that make your space feel elevated.",
        "categories": ["home_decor", "kitchen", "office"],
        "emoji": "🏠",
    },
    "beauty": {
        "title": "Beauty & Skincare Finds",
        "description": "Affordable beauty essentials and skincare picks.",
        "categories": ["beauty"],
        "emoji": "💕",
    },
    "wellness": {
        "title": "Wellness & Fitness Finds",
        "description": "Self care and wellness essentials for your best life.",
        "categories": ["fitness"],
        "emoji": "✨",
    },
}

def _affiliate_url(amazon_url, tag="auragirlcreat-20"):
    """Append affiliate tag to Amazon URL."""
    if not amazon_url:
        return amazon_url
    if tag in amazon_url:
        return amazon_url
    separator = "&" if "?" in amazon_url else "?"
    return f"{amazon_url}{separator}tag={tag}"

@bp.route("/privacy")
def privacy():
    return render_template("privacy.html")

@bp.route("/shop")
def shop():
    recent_pins = (
        Pin.query.filter(
            Pin.status.in_([Pin.STATUS_POSTED, Pin.STATUS_SCHEDULED, Pin.STATUS_DRAFT]),
            Pin.image_url.isnot(None),
        )
        .order_by(Pin.created_at.desc())
        .limit(6)
        .all()
    )
    return render_template("shop.html", niches=SHOP_NICHES, recent_pins=recent_pins)

@bp.route("/shop/<niche>")
def shop_niche(niche):
    if niche not in SHOP_NICHES:
        return redirect(url_for("main.shop"))
    niche_info = SHOP_NICHES[niche]
    products = Product.query.filter(
        Product.is_active == True,
        Product.category.in_(niche_info["categories"])
    ).order_by(Product.added_at.desc()).all()
    for p in products:
        p.affiliate_url = _affiliate_url(p.amazon_url)
    return render_template("shop_niche.html", niche=niche, niche_info=niche_info, products=products)


@bp.route("/shop/pin/<int:pin_id>")
def shop_pin(pin_id):
    """
    'Shop the Pin' landing page — shows only the products featured in that specific pin.
    This is the link we put in every Pinterest pin so visitors land on exactly
    what they saw, not a wall of 50 products.
    """
    pin = Pin.query.filter(
        Pin.id == pin_id,
        Pin.status.in_([Pin.STATUS_DRAFT, Pin.STATUS_POSTED, Pin.STATUS_APPROVED, Pin.STATUS_SCHEDULED])
    ).first()
    if not pin:
        return redirect(url_for("main.shop"))

    products = [p for p in pin.products if p.is_active]
    for p in products:
        p.affiliate_url = _affiliate_url(p.amazon_url)

    return render_template("shop_pin.html", pin=pin, products=products)


# ── Health check ──────────────────────────────────────────────────────────

@bp.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})
