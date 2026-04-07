"""
Entry point for the Pinterest Automation Flask app.
Run directly: python main.py
Production:   gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 120 main:app
"""
import logging
import os

from app import create_app

logger = logging.getLogger(__name__)

app = create_app()

if __name__ == "__main__":
    from config import Config

    port = Config.PORT
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")

    logger.info(f"Starting PinBot on port {port} (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug)
