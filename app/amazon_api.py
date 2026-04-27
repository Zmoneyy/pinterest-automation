"""
Amazon product discovery helpers.

SerpAPI has been removed. Products are added manually via the Upload Pin page.
These stubs keep existing callers working without errors.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _build_affiliate_url(asin: str, associate_tag: str) -> str:
    return f"https://www.amazon.com/dp/{asin}?tag={associate_tag}"


def search_products(
    keyword: str,
    category: Optional[str] = None,
    max_results: int = 8,
) -> list[dict]:
    """Products are added manually via Upload Pin — keyword search not used."""
    return []


def discover_products_for_trends(trends: list[dict], per_trend: int = 5) -> list[dict]:
    """Products are added manually via Upload Pin — trend-based discovery not used."""
    return []


def discover_evergreen_products(per_query: int = 4) -> list[dict]:
    """Products are added manually via Upload Pin — evergreen discovery not used."""
    return []
