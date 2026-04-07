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

        db.create_all()

        # Seed sample data on first run
        _seed_sample_data()

        # Register routes
        from app.routes import bp

        app.register_blueprint(bp)

        # Start the scheduler
        _start_scheduler(app)

    return app


def _seed_sample_data():
    """Add a sample product if the database is empty."""
    from app.models import Product

    if Product.query.count() == 0:
        sample = Product(
            name="Cozy Knit Throw Blanket",
            amazon_url="https://www.amazon.com/dp/B09EXAMPLE",
            benable_url="https://benable.com/example/cozy-knit-throw-blanket",
            category="home_decor",
            price="39.99",
            is_active=True,
        )
        db.session.add(sample)

        sample2 = Product(
            name="Ceramic Pour-Over Coffee Set",
            amazon_url="https://www.amazon.com/dp/B08EXAMPLE",
            benable_url="https://benable.com/example/ceramic-pour-over-coffee-set",
            category="kitchen",
            price="54.99",
            is_active=True,
        )
        db.session.add(sample2)

        sample3 = Product(
            name="Minimalist Desk Organizer",
            amazon_url="https://www.amazon.com/dp/B07EXAMPLE",
            benable_url="https://benable.com/example/minimalist-desk-organizer",
            category="office",
            price="28.99",
            is_active=True,
        )
        db.session.add(sample3)

        db.session.commit()
        logger.info("Seeded sample products into database.")


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
