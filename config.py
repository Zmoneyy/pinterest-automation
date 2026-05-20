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
    BENABLE_URL_BEAUTY  = os.environ.get("BENABLE_URL_BEAUTY", "https://auragirlessentials.com/shop/beauty")
    BENABLE_URL_HOME    = os.environ.get("BENABLE_URL_HOME", "https://auragirlessentials.com/shop/glam-home")
    BENABLE_URL_FITNESS = os.environ.get("BENABLE_URL_FITNESS", "https://auragirlessentials.com/shop/wellness")
    BRAND_NAME          = os.environ.get("BRAND_NAME", "")

    @classmethod
    def benable_url_for_niche(cls, niche: str) -> str:
        return {
            "beauty":     cls.BENABLE_URL_BEAUTY,
            "home_decor": cls.BENABLE_URL_HOME,
            "fitness":    cls.BENABLE_URL_FITNESS,
        }.get(niche, cls.BENABLE_URL_BEAUTY)

    AMAZON_ASSOCIATE_TAG = os.environ.get("AMAZON_ASSOCIATE_TAG", "")  # e.g. auragirlcre-20
    SERPAPI_KEY          = os.environ.get("SERPAPI_KEY", "")

    # AI APIs
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
    GOOGLE_PROJECT_ID = os.environ.get("GOOGLE_PROJECT_ID", "")
    GOOGLE_LOCATION   = os.environ.get("GOOGLE_LOCATION", "us-central1")
    OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
    BLOTATO_API_KEY    = os.environ.get("BLOTATO_API_KEY", "")
    BLOTATO_ACCOUNT_ID = os.environ.get("BLOTATO_ACCOUNT_ID", "5694")
    TAILWIND_API_KEY   = os.environ.get("TAILWIND_API_KEY", "")

    PINTEREST_BOARDS = {
        "Beauty Finds & Skincare":              os.environ.get("PINTEREST_BOARD_BEAUTY",           "1140044161863463132"),
        "Glam Home Decor Ideas":                os.environ.get("PINTEREST_BOARD_GLAM_HOME",        "1140044161863463135"),
        "Wellness & Self Care Essentials":      os.environ.get("PINTEREST_BOARD_WELLNESS",         "1140044161863463136"),
        "Nail Inspo & Nail Art Ideas":          os.environ.get("PINTEREST_BOARD_NAILS",            "1140044161863463150"),
        "Luxury Look for Less Home Decor":      os.environ.get("PINTEREST_BOARD_LUXURY_HOME",      "1140044161863463151"),
        "Amazon Home Finds":                    os.environ.get("PINTEREST_BOARD_AMAZON_HOME",      "1140044161863463152"),
        "Aesthetic Home Decor for Cozy Spaces": os.environ.get("PINTEREST_BOARD_AESTHETIC_HOME",   "1140044161863463154"),
        "Affordable Beauty Essentials":         os.environ.get("PINTEREST_BOARD_AFFORDABLE_BEAUTY","1140044161863463155"),
        "Fitness Finds on Amazon":              os.environ.get("PINTEREST_BOARD_FITNESS",          "1140044161863463156"),
        "Aesthetic Home Finds":                 os.environ.get("PINTEREST_BOARD_AESTHETIC_FINDS",  "1140044161863515409"),
        "Garden & Plant Inspo":                 os.environ.get("PINTEREST_BOARD_GARDEN",           "1140044161863515416"),
        "Hair Care Essentials":                 os.environ.get("PINTEREST_BOARD_HAIR",             "1140044161863515412"),
        "Makeup Finds Under $50":               os.environ.get("PINTEREST_BOARD_MAKEUP",           "1140044161863515414"),
        "Mother's Day Gift Ideas":              os.environ.get("PINTEREST_BOARD_MOTHERS_DAY",      "1140044161863515413"),
    }
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
        # Check DB for token in case it was set via OAuth flow
        db_token = ""
        try:
            from app.models import Setting
            db_token = Setting.get("pinterest_access_token", "")
        except Exception:
            pass
        return {
            "pinterest_app": bool(cls.PINTEREST_APP_ID and cls.PINTEREST_APP_SECRET),
            "pinterest_token": bool(cls.PINTEREST_ACCESS_TOKEN or db_token),
            "pinterest_board": bool(cls.PINTEREST_BOARD_ID),
            "benable": bool(cls.BENABLE_URL),
            "anthropic": bool(cls.ANTHROPIC_API_KEY),
            "google_vertex": bool(cls.GOOGLE_PROJECT_ID),
            "dashboard_password": bool(cls.DASHBOARD_PASSWORD),
            "brand_name": bool(cls.BRAND_NAME),
        }
