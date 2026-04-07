from datetime import datetime, timezone

from app import db


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    amazon_url = db.Column(db.Text, nullable=False)
    benable_url = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    image_url = db.Column(db.Text, nullable=True)
    price = db.Column(db.String(20), nullable=True)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    pins = db.relationship("Pin", backref="product", lazy=True)

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
        }

    def __repr__(self):
        return f"<Product {self.id}: {self.name}>"


class Pin(db.Model):
    __tablename__ = "pins"

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_POSTED = "posted"
    STATUS_SCHEDULED = "scheduled"
    STATUS_NEEDS_IMAGE = "needs_image"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    hashtags = db.Column(db.Text, nullable=True)  # JSON array stored as string
    image_path = db.Column(db.Text, nullable=True)  # local /tmp path
    image_url = db.Column(db.Text, nullable=True)   # remote URL if applicable
    status = db.Column(db.String(50), default="pending", nullable=False)
    scheduled_for = db.Column(db.DateTime, nullable=True)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    pinterest_pin_id = db.Column(db.String(255), nullable=True)
    trend_keyword = db.Column(db.String(255), nullable=True)
    style_variant = db.Column(db.String(50), nullable=True)

    def hashtags_list(self):
        """Return hashtags as a Python list."""
        import json

        if not self.hashtags:
            return []
        try:
            return json.loads(self.hashtags)
        except (json.JSONDecodeError, TypeError):
            return [h.strip() for h in self.hashtags.split(",") if h.strip()]

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else None,
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
