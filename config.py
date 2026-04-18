import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Pinterest API
    PINTEREST_APP_ID = os.environ.get("PINTEREST_APP_ID", "")
    PINTEREST_APP_SECRET = os.environ.get("PINTEREST_APP_SECRET", "")
    PINTEREST_ACCESS_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
    PINTEREST_BOARD_ID = os.environ.get("PINTEREST_BOARD_ID", "")

    # Affiliate / Branding
    BENABLE_URL         = os.environ.get("BENABLE_URL", "")
    BENABLE_URL_BEAUTY  = os.environ.get("BENABLE_URL_BEAUTY", "https://benable.com/AuraGirlFinds/beauty-faves")
    BENABLE_URL_HOME    = os.environ.get("BENABLE_URL_HOME", "https://benable.com/AuraGirlFinds/glam-home")
    BENABLE_URL_FITNESS = os.environ.get("BENABLE_URL_FITNESS", "https://benable.com/AuraGirlFinds/wellness-picks")
    BRAND_NAME          = os.environ.get("BRAND_NAME", "")

    @classmethod
    def benable_url_for_niche(cls, niche: str) -> str:
        return {
            "beauty":     cls.BENABLE_URL_BEAUTY,
            "home_decor": cls.BENABLE_URL_HOME,
            "fitness":    cls.BENABLE_URL_FITNESS,
        }.get(niche, cls.BENABLE_URL_BEAUTY)

    # Amazon product search (via SerpAPI Google Shopping)
    SERP_API_KEY         = os.environ.get("SERP_API_KEY", "")
    AMAZON_ASSOCIATE_TAG = os.environ.get("AMAZON_ASSOCIATE_TAG", "")  # e.g. auragirlcre-20

    # AI APIs
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
    GOOGLE_PROJECT_ID = os.environ.get("GOOGLE_PROJECT_ID", "")
    GOOGLE_LOCATION   = os.environ.get("GOOGLE_LOCATION", "us-central1")
    BLOTATO_API_KEY   = os.environ.get("BLOTATO_API_KEY", "")
    FAL_API_KEY       = os.environ.get("FAL_API_KEY", "")

    # Database
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///pins.db")
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-please")
    DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

    # Server
    PORT = int(os.environ.get("PORT", 8080))

    # Pinterest OAuth
    PINTEREST_REDIRECT_URI = os.environ.get(
        "PINTEREST_REDIRECT_URI", "http://localhost:8080/pinterest/callback"
    )

    @classmethod
    def is_configured(cls):
        """Return a dict of which required settings are configured."""
        return {
            "pinterest_app": bool(cls.PINTEREST_APP_ID and cls.PINTEREST_APP_SECRET),
            "pinterest_token": bool(cls.PINTEREST_ACCESS_TOKEN),
            "pinterest_board": bool(cls.PINTEREST_BOARD_ID),
            "benable": bool(cls.BENABLE_URL),
            "amazon_search": bool(cls.SERP_API_KEY),
            "anthropic": bool(cls.ANTHROPIC_API_KEY),
            "google_vertex": bool(cls.GOOGLE_PROJECT_ID),
            "dashboard_password": bool(cls.DASHBOARD_PASSWORD),
            "brand_name": bool(cls.BRAND_NAME),
        }
