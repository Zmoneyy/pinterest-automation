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

        # Markdown → HTML filter for AI Strategy Brief
        import re as _re
        from markupsafe import Markup

        def md_to_html(text):
            if not text:
                return ""
            t = str(text)
            # Escape HTML entities first
            t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            # Horizontal rules --- → <hr>
            t = _re.sub(r'^\s*[-]{3,}\s*$', '<hr style="border:none;border-top:1px solid #bbf7d0;margin:8px 0;">', t, flags=_re.MULTILINE)
            # Markdown tables — strip them into a simple list of rows
            def _render_table(m):
                rows = [r.strip() for r in m.group(0).strip().split('\n') if r.strip() and not _re.match(r'^\|[-| :]+\|$', r.strip())]
                html = '<div style="margin:6px 0;">'
                for row in rows:
                    cells = [c.strip() for c in row.strip('|').split('|') if c.strip()]
                    html += '<div style="display:flex;gap:12px;padding:3px 0;border-bottom:1px solid #d1fae5;">' + ''.join(f'<span style="flex:1;font-size:12px;">{c}</span>' for c in cells) + '</div>'
                html += '</div>'
                return html
            t = _re.sub(r'(^\|.+\|\n?)+', _render_table, t, flags=_re.MULTILINE)
            # Bold **text**
            t = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
            # Italic *text*
            t = _re.sub(r'\*(.+?)\*', r'<em>\1</em>', t)
            # ## Heading → bold section header
            t = _re.sub(r'^#{1,3}\s+(.+)$', r'<p style="font-weight:800;margin:10px 0 3px 0;color:#14532d;">\1</p>', t, flags=_re.MULTILINE)
            # Numbered list  1. item
            t = _re.sub(r'^\d+\.\s+(.+)$', r'<li>\1</li>', t, flags=_re.MULTILINE)
            # Bullet - item
            t = _re.sub(r'^[-•]\s+(.+)$', r'<li>\1</li>', t, flags=_re.MULTILINE)
            # Wrap consecutive <li> in <ul>
            t = _re.sub(r'(<li>.*?</li>(\n|$))+', lambda m: '<ul style="margin:4px 0 6px 16px;padding:0;">' + m.group(0) + '</ul>', t, flags=_re.DOTALL)
            # Paragraphs: blank lines
            t = _re.sub(r'\n{2,}', '</p><p style="margin:4px 0;">', t)
            t = '<p style="margin:4px 0;">' + t + '</p>'
            # Clean up empty paragraphs
            t = _re.sub(r'<p[^>]*>\s*(<hr[^>]*>)?\s*</p>', r'\1', t)
            return Markup(t)

        app.jinja_env.filters["md"] = md_to_html

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
        # trend_entries table
        "ALTER TABLE trend_entries ADD COLUMN IF NOT EXISTS full_page_kws TEXT",
        "ALTER TABLE trend_entries ADD COLUMN IF NOT EXISTS total_keywords INTEGER DEFAULT 0",
        # product_candidates — source category tag
        "ALTER TABLE product_candidates ADD COLUMN IF NOT EXISTS source_category VARCHAR(255)",
        # trend_entries — priority (high/medium/low based on outbound click volume)
        "ALTER TABLE trend_entries ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'medium'",
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
