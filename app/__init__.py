import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
_bg_scheduler = BackgroundScheduler(timezone="UTC")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(config_object=None):
    app = Flask(__name__, template_folder="../templates")

    if config_object is None:
        from config import Config

        app.config.from_object(Config)
    else:
        app.config.from_object(config_object)

    # Init extensions
    db.init_app(app)

    with app.app_context():
        # Import models so SQLAlchemy knows about them
        from app import models  # noqa: F401

        from sqlalchemy.exc import OperationalError
        try:
            db.create_all()
        except OperationalError:
            db.session.rollback()

        # Seed sample data on first run
        _seed_sample_data()

        # Register routes
        from app.routes import bp

        app.register_blueprint(bp)

        # Start the scheduler
        _start_scheduler(app)

    return app


def _seed_sample_data():
    """
    Seed sample products on first run.
    These are placeholders — replace them with your real Benable links.
    Each product should have an image_url pointing to the Amazon product image
    so the collage generator can download and compose it.
    """
    from app.models import Product

    if Product.query.count() > 0:
        return

    samples = [
        Product(
            name="Cozy Knit Throw Blanket",
            amazon_url="https://www.amazon.com/dp/B09EXAMPLE1",
            benable_url="https://benable.com/example",
            category="home_decor",
            price="39.99",
            image_url="https://images-na.ssl-images-amazon.com/images/I/placeholder1.jpg",
            is_active=True,
        ),
        Product(
            name="Ceramic Pour-Over Coffee Set",
            amazon_url="https://www.amazon.com/dp/B08EXAMPLE2",
            benable_url="https://benable.com/example",
            category="kitchen",
            price="54.99",
            image_url="https://images-na.ssl-images-amazon.com/images/I/placeholder2.jpg",
            is_active=True,
        ),
        Product(
            name="Minimalist Desk Organizer",
            amazon_url="https://www.amazon.com/dp/B07EXAMPLE3",
            benable_url="https://benable.com/example",
            category="office",
            price="28.99",
            image_url="https://images-na.ssl-images-amazon.com/images/I/placeholder3.jpg",
            is_active=True,
        ),
        Product(
            name="Fluffy Crossband Slippers",
            amazon_url="https://www.amazon.com/dp/B06EXAMPLE4",
            benable_url="https://benable.com/example",
            category="fashion",
            price="22.99",
            image_url="https://images-na.ssl-images-amazon.com/images/I/placeholder4.jpg",
            is_active=True,
        ),
        Product(
            name="EOS Cashmere Body Oil",
            amazon_url="https://www.amazon.com/dp/B05EXAMPLE5",
            benable_url="https://benable.com/example",
            category="beauty",
            price="12.99",
            image_url="https://images-na.ssl-images-amazon.com/images/I/placeholder5.jpg",
            is_active=True,
        ),
        Product(
            name="Linen Pillow Cover Set",
            amazon_url="https://www.amazon.com/dp/B04EXAMPLE6",
            benable_url="https://benable.com/example",
            category="home_decor",
            price="24.99",
            image_url="https://images-na.ssl-images-amazon.com/images/I/placeholder6.jpg",
            is_active=True,
        ),
        Product(
            name="Marble Wireless Charger",
            amazon_url="https://www.amazon.com/dp/B03EXAMPLE7",
            benable_url="https://benable.com/example",
            category="tech",
            price="19.99",
            image_url="https://images-na.ssl-images-amazon.com/images/I/placeholder7.jpg",
            is_active=True,
        ),
        Product(
            name="Gold Acrylic Tray",
            amazon_url="https://www.amazon.com/dp/B02EXAMPLE8",
            benable_url="https://benable.com/example",
            category="home_decor",
            price="16.99",
            image_url="https://images-na.ssl-images-amazon.com/images/I/placeholder8.jpg",
            is_active=True,
        ),
    ]

    for s in samples:
        db.session.add(s)

    db.session.commit()
    logger.info(f"Seeded {len(samples)} sample products. Replace with your real product links!")


def _start_scheduler(app):
    """Configure and start APScheduler jobs."""
    if _bg_scheduler.running:
        return

    from app.scheduler import run_daily_pin_generation, schedule_approved_pins

    # Daily pin generation at 9 AM UTC
    _bg_scheduler.add_job(
        func=lambda: _run_with_context(app, run_daily_pin_generation),
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_pin_generation",
        name="Daily Pin Generation",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Check for scheduled pins every 15 minutes
    _bg_scheduler.add_job(
        func=lambda: _run_with_context(app, schedule_approved_pins),
        trigger="interval",
        minutes=15,
        id="schedule_approved_pins",
        name="Post Scheduled Pins",
        replace_existing=True,
    )

    _bg_scheduler.start()
    logger.info("APScheduler started.")


def _run_with_context(app, func):
    """Run a function inside the Flask app context."""
    with app.app_context():
        try:
            func()
        except Exception as e:
            logger.error(f"Scheduler job error in {func.__name__}: {e}", exc_info=True)
