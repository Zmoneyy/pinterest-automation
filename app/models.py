from datetime import datetime, timezone

from app import db

# ---------------------------------------------------------------------------
# Association table: a Pin features many Products (many-to-many)
# ---------------------------------------------------------------------------
pin_products = db.Table(
    "pin_products",
    db.Column("pin_id", db.Integer, db.ForeignKey("pins.id", ondelete="CASCADE"), primary_key=True),
    db.Column("product_id", db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    db.Column("position", db.Integer, default=0),  # display order in the collage
)


class Product(db.Model):
    __tablename__ = "products"

    CONTENT_EVERGREEN = "evergreen"   # sells year-round (skincare basics, home organizers)
    CONTENT_SEASONAL  = "seasonal"    # tied to a season or moment (summer, holiday, back-to-school)
    CONTENT_TRENDING  = "trending"    # growing fast on Pinterest right now

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    amazon_url = db.Column(db.Text, nullable=False)
    benable_url = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    image_url = db.Column(db.Text, nullable=True)
    price = db.Column(db.String(20), nullable=True)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    content_type = db.Column(db.String(20), default="evergreen", nullable=False)  # evergreen/seasonal/trending

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "amazon_url": self.amazon_url,
            "benable_url": self.benable_url,
            "category": self.category,
            "image_url": self.image_url,
            "price": self.price,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "is_active": self.is_active,
            "content_type": self.content_type,
        }

    def __repr__(self):
        return f"<Product {self.id}: {self.name}>"


class Pin(db.Model):
    __tablename__ = "pins"

    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_POSTED = "posted"
    STATUS_SCHEDULED = "scheduled"
    STATUS_NEEDS_IMAGE = "needs_image"

    id = db.Column(db.Integer, primary_key=True)
    theme = db.Column(db.String(255), nullable=True)          # e.g. "Winter Staples Under $100"
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    hashtags = db.Column(db.Text, nullable=True)              # JSON array stored as string
    image_path = db.Column(db.Text, nullable=True)            # local /tmp path
    image_url = db.Column(db.Text, nullable=True)             # remote URL after posting
    status = db.Column(db.String(50), default="pending", nullable=False)
    scheduled_for = db.Column(db.DateTime, nullable=True)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    pinterest_pin_id = db.Column(db.String(255), nullable=True)
    trend_keyword = db.Column(db.String(255), nullable=True)
    style_variant = db.Column(db.String(50), nullable=True)
    board_name    = db.Column(db.String(255), nullable=True)   # Pinterest board name for posting
    alt_text      = db.Column(db.Text, nullable=True)          # SEO alt text for the pin
    shop_url      = db.Column(db.Text, nullable=True)          # shop page link (auragirlessentials.com/shop/...)
    amazon_url    = db.Column(db.Text, nullable=True)          # direct Amazon affiliate URL (for bulk-uploaded pins)
    post_error    = db.Column(db.Text, nullable=True)          # last posting error message (cleared on success)

    # Many-to-many: each collage pin features 5-8 products
    products = db.relationship(
        "Product",
        secondary=pin_products,
        backref=db.backref("pins", lazy=True),
        order_by=pin_products.c.position,
    )

    def hashtags_list(self):
        import json
        if not self.hashtags:
            return []
        try:
            return json.loads(self.hashtags)
        except (json.JSONDecodeError, TypeError):
            return [h.strip() for h in self.hashtags.split(",") if h.strip()]

    def product_names(self):
        return ", ".join(p.name for p in self.products)

    def to_dict(self):
        return {
            "id": self.id,
            "theme": self.theme,
            "products": [p.to_dict() for p in self.products],
            "product_count": len(self.products),
            "title": self.title,
            "description": self.description,
            "hashtags": self.hashtags_list(),
            "image_path": self.image_path,
            "image_url": self.image_url,
            "status": self.status,
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "pinterest_pin_id": self.pinterest_pin_id,
            "trend_keyword": self.trend_keyword,
            "style_variant": self.style_variant,
        }

    def __repr__(self):
        return f"<Pin {self.id}: {self.title[:40]}... [{self.status}]>"


class TrendCache(db.Model):
    __tablename__ = "trend_cache"

    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    cached_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    score = db.Column(db.Float, nullable=True)

    def __repr__(self):
        return f"<TrendCache {self.keyword} ({self.category})>"


class TrendEntry(db.Model):
    """One dated paste session per product category from Pinterest Analytics."""
    __tablename__ = "trend_entries"

    PRIORITY_HIGH   = "high"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_LOW    = "low"

    id               = db.Column(db.Integer, primary_key=True)
    category         = db.Column(db.String(255), nullable=False)
    saved_at         = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    search_queries   = db.Column(db.Text)   # JSON list of keyword strings
    top_products     = db.Column(db.Text)   # JSON list of product strings
    full_page_kws    = db.Column(db.Text)   # JSON list of keywords from full page dump
    insight          = db.Column(db.Text)   # AI-generated summary of this trend category
    total_keywords   = db.Column(db.Integer, default=0)
    priority         = db.Column(db.String(20), default="medium")  # high / medium / low
    screenshots_b64  = db.Column(db.Text)   # JSON list of {image: base64, mime_type: str} — saved screenshots

    def sq_list(self):
        import json
        try: return json.loads(self.search_queries or "[]")
        except: return []

    def tp_list(self):
        import json
        try: return json.loads(self.top_products or "[]")
        except: return []

    def fp_list(self):
        import json
        try: return json.loads(self.full_page_kws or "[]")
        except: return []

    def ss_count(self):
        import json
        try: return len(json.loads(self.screenshots_b64 or "[]"))
        except: return 0

    def __repr__(self):
        return f"<TrendEntry {self.category} @ {self.saved_at}>"


class ProductCandidate(db.Model):
    """Amazon products discovered automatically, waiting for user approval."""

    __tablename__ = "product_candidates"

    STATUS_PENDING  = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(255), nullable=False)
    asin            = db.Column(db.String(20), nullable=True)
    amazon_url      = db.Column(db.Text, nullable=False)
    category        = db.Column(db.String(100), nullable=True)
    source_category = db.Column(db.String(255), nullable=True)   # the TrendEntry category name
    image_url       = db.Column(db.Text, nullable=True)
    price           = db.Column(db.String(20), nullable=True)
    trend_keyword   = db.Column(db.String(255), nullable=True)
    status          = db.Column(db.String(20), default="pending", nullable=False)
    discovered_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "asin": self.asin,
            "amazon_url": self.amazon_url,
            "category": self.category,
            "image_url": self.image_url,
            "price": self.price,
            "trend_keyword": self.trend_keyword,
            "status": self.status,
        }

    def __repr__(self):
        return f"<ProductCandidate {self.id}: {self.name} [{self.status}]>"


class PinResearch(db.Model):
    """Saved Pin → Products research sessions (the 'folders' the user builds)."""
    __tablename__ = "pin_research"

    id           = db.Column(db.Integer, primary_key=True)
    title        = db.Column(db.String(500), nullable=False)
    keywords     = db.Column(db.Text, nullable=True)   # comma-separated
    summary      = db.Column(db.Text, nullable=True)
    products     = db.Column(db.Text, nullable=True)   # JSON array
    image_prompt = db.Column(db.Text, nullable=True)   # ChatGPT image generation prompt
    ppp_prompt   = db.Column(db.Text, nullable=True)   # Pin Perfect Pro GPT prompt
    blog_post    = db.Column(db.Text, nullable=True)   # optional blog post for website
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def products_list(self):
        import json
        try:
            return json.loads(self.products or "[]")
        except Exception:
            return []

    def __repr__(self):
        return f"<PinResearch {self.id}: {self.title[:40]}>"


class Setting(db.Model):
    """Key-value settings table for persisting OAuth tokens and config."""

    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @classmethod
    def get(cls, key, default=None):
        row = cls.query.filter_by(key=key).first()
        return row.value if row else default

    @classmethod
    def set(cls, key, value):
        row = cls.query.filter_by(key=key).first()
        if row:
            row.value = value
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = cls(key=key, value=value)
            db.session.add(row)
        db.session.commit()

    def __repr__(self):
        return f"<Setting {self.key}>"
