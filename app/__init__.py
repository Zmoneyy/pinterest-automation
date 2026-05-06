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

        # Migrate any new columns added to existing tables
        _run_migrations()

        # Remove sample placeholder products
        _remove_sample_data()

        # Register routes
        from app.routes import bp

        app.register_blueprint(bp)

        # Expose APP_ENV to all templates
        app_env = os.environ.get("APP_ENV", "prod")
        app.jinja_env.globals["APP_ENV"] = app_env

        # Start the scheduler
        _start_scheduler(app)

    return app


def _run_migrations():
    """Add new columns to existing tables without dropping data."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE pins ADD COLUMN IF NOT EXISTS board_name VARCHAR(255)",
        "ALTER TABLE pins ADD COLUMN IF NOT EXISTS alt_text TEXT",
        "ALTER TABLE pins ADD COLUMN IF NOT EXISTS shop_url TEXT",
        "ALTER TABLE pins ADD COLUMN IF NOT EXISTS post_error TEXT",
    ]
    for sql in migrations:
        try:
            db.session.execute(text(sql))
        except Exception:
            db.session.rollback()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _remove_sample_data():
    """Remove placeholder sample products that were seeded on first run."""
    from app.models import Product

    sample_names = [
        "Cozy Knit Throw Blanket",
        "Ceramic Pour-Over Coffee Set",
        "Minimalist Desk Organizer",
        "Fluffy Crossband Slippers",
        "EOS Cashmere Body Oil",
        "Linen Pillow Cover Set",
        "Marble Wireless Charger",
        "Gold Acrylic Tray",
    ]

    removed = 0
    for name in sample_names:
        p = Product.query.filter_by(name=name).first()
        if p:
            db.session.delete(p)
            removed += 1

    if removed:
        db.session.commit()
        logger.info(f"Removed {removed} sample placeholder products.")


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
