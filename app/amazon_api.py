"""
Amazon product discovery — free scraping, no SerpAPI.

Flow:
  1. Take a trending keyword from Pinterest TrendCache
  2. Search Amazon for that keyword
  3. Extract: name, ASIN, price, image, URL
  4. Return top results → scheduler adds to ProductCandidate queue
"""
import logging
import re
import time
import random
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# High-commission categories to prioritize in searches
# beauty=10%, home=3%, fitness=1% — beauty first always
NICHE_SEARCH_SUFFIXES = {
    "beauty":    ["amazon beauty", "skincare amazon", "makeup amazon finds"],
    "home_decor": ["amazon home decor", "home finds amazon", "room decor amazon"],
    "fitness":   ["amazon wellness", "self care amazon", "supplements amazon"],
}

AMAZON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def _build_affiliate_url(asin: str, associate_tag: str) -> str:
    # Full amazon.com URL — Pinterest trusts these more than amzn.to short links
    return f"https://www.amazon.com/dp/{asin}?tag={associate_tag}&linkCode=ll1&language=en_US&ref_=as_li_ss_tl"


def search_products(
    keyword: str,
    category: Optional[str] = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Search Amazon for products matching a keyword via SerpAPI.
    Falls back to empty list if SerpAPI key not configured.
    Returns list of {name, asin, amazon_url, image_url, price, category}.
    """
    from config import Config

    associate_tag = Config.AMAZON_ASSOCIATE_TAG or "auragirlcreat-20"

    # Try SerpAPI first (works from Cloud Run — no IP blocking)
    serpapi_key = _get_serpapi_key()
    if serpapi_key:
        try:
            results = _search_via_serpapi(keyword, serpapi_key, max_results=max_results)
            for r in results:
                if r.get("asin"):
                    r["amazon_url"] = _build_affiliate_url(r["asin"], associate_tag)
                r["category"] = category or _guess_category(r.get("name", ""))
            logger.info(f"SerpAPI search '{keyword}': {len(results)} products found")
            return results
        except Exception as e:
            logger.error(f"SerpAPI search failed for '{keyword}': {e}")

    return []


def _get_serpapi_key() -> str:
    """Get SerpAPI key from DB setting or environment config."""
    try:
        from app.models import Setting
        key = Setting.get("serpapi_key", "")
        if key:
            return key
    except Exception:
        pass
    from config import Config
    return Config.SERPAPI_KEY or ""


def _search_via_serpapi(keyword: str, api_key: str, max_results: int = 5) -> list[dict]:
    """Search Amazon products using SerpAPI's Amazon Search engine."""
    params = {
        "engine": "amazon",
        "q": keyword,
        "api_key": api_key,
        "amazon_domain": "amazon.com",
    }
    resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    products = []
    organic = data.get("organic_results", [])
    for item in organic[:max_results]:
        asin = item.get("asin", "")
        name = item.get("title", "")
        if not asin or not name:
            continue
        # Price — SerpAPI returns price as string like "$38.00" or float
        price_raw = item.get("price", {})
        if isinstance(price_raw, dict):
            price = str(price_raw.get("value", "0"))
        elif isinstance(price_raw, (int, float)):
            price = str(price_raw)
        else:
            price = str(price_raw).replace("$", "").strip()

        image_url = item.get("thumbnail", "") or item.get("image", "")

        products.append({
            "name": name,
            "asin": asin,
            "image_url": image_url,
            "price": price,
        })

    return products


def _scrape_amazon_search(keyword: str, max_results: int = 5) -> list[dict]:
    """Stub — Amazon blocks Cloud Run IPs. Use SerpAPI instead."""
    return []


def _fetch_amazon_product(asin: str) -> Optional[dict]:
    """Stub — Amazon blocks Cloud Run IPs. Use SerpAPI instead."""
    return None


# Luxury beauty searches that reliably return 10% commission products
LUXURY_BEAUTY_SEARCHES = [
    ("charlotte tilbury amazon", "Charlotte Tilbury"),
    ("tatcha skincare amazon", "Tatcha"),
    ("drunk elephant serum amazon", "Drunk Elephant"),
    ("rare beauty selena gomez amazon", "Rare Beauty"),
    ("merit beauty amazon", "Merit"),
    ("nars cosmetics amazon", "NARS"),
    ("dyson airwrap amazon", "Dyson"),
    ("sunday riley amazon", "Sunday Riley"),
    ("peter thomas roth amazon", "Peter Thomas Roth"),
    ("ilia beauty amazon", "ILIA"),
    ("kate somerville amazon", "Kate Somerville"),
    ("pat mcgrath amazon", "Pat McGrath"),
    ("shiseido amazon", "Shiseido"),
    ("estee lauder amazon", "Estée Lauder"),
    ("lancôme amazon", "Lancôme"),
    ("ysl beauty amazon", "YSL Beauty"),
    ("tom ford beauty amazon", "Tom Ford Beauty"),
    ("la mer moisturizer amazon", "La Mer"),
    ("sk-ii facial treatment amazon", "SK-II"),
    ("westman atelier amazon", "Westman Atelier"),
]


def discover_products_for_trends(trends: list[dict], per_trend: int = 3) -> list[dict]:
    """
    Search Amazon for products. ALWAYS leads with luxury beauty (10% commission)
    searches first, then trend-matched products.
    """
    all_products = []
    seen_asins = set()

    def _add_products(products, trend_keyword, source_category):
        for p in products:
            asin = p.get("asin", "")
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
                p["trend_keyword"]   = trend_keyword
                p["source_category"] = source_category
                all_products.append(p)

    # ── STEP 1: Always search luxury beauty brands first (10% commission) ──
    # Shuffle so we don't always get the same brands
    luxury_searches = list(LUXURY_BEAUTY_SEARCHES)
    random.shuffle(luxury_searches)
    for query, brand in luxury_searches[:8]:   # top 8 luxury brands per run
        products = search_products(query, category="luxury_beauty", max_results=3)
        _add_products(products, brand, "Luxury Beauty (10%)")
        time.sleep(random.uniform(1.5, 3))

    # ── STEP 2: Trend-matched searches from TrendEntry categories ──
    for trend in trends[:15]:
        keyword         = trend.get("keyword", "")
        niche           = trend.get("niche") or trend.get("category", "beauty")
        source_category = trend.get("source_category", "")
        if not keyword:
            continue
        products = search_products(keyword, category=niche, max_results=per_trend)
        _add_products(products, keyword, source_category)
        time.sleep(random.uniform(2, 4))

    return all_products


def discover_evergreen_products(per_query: int = 3) -> list[dict]:
    """Search for evergreen high-commission beauty products."""
    evergreen_queries = [
        "best skincare serum amazon",
        "vitamin c serum face amazon",
        "retinol cream amazon best seller",
        "hyaluronic acid moisturizer amazon",
        "niacinamide serum amazon",
    ]
    all_products = []
    seen_asins = set()

    for query in evergreen_queries[:3]:
        products = search_products(query, category="beauty", max_results=per_query)
        for p in products:
            asin = p.get("asin", "")
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
                all_products.append(p)
        time.sleep(random.uniform(2, 4))

    return all_products


# Luxury Beauty brands on Amazon → 10% commission
LUXURY_BEAUTY_BRANDS = [
    "la mer", "tatcha", "charlotte tilbury", "sk-ii", "sk ii", "sisley",
    "sulwhasoo", "valmont", "dr. barbara sturm", "barbara sturm", "augustinus bader",
    "dyson", "nars", "pat mcgrath", "pat mcgrath labs", "hourglass", "by terry",
    "drunk elephant", "de la mer", "cle de peau", "clé de peau", "shiseido",
    "estee lauder", "estée lauder", "lancome", "lancôme", "ysl beauty",
    "yves saint laurent", "giorgio armani beauty", "dior beauty", "chanel beauty",
    "givenchy beauty", "tom ford beauty", "guerlain", "la prairie",
    "peter thomas roth", "sunday riley", "kate somerville", "perricone md",
    "tata harper", "ilia", "westman atelier", "merit", "rare beauty",
    # Additional luxury beauty brands from TrendEntry products
    "clinique", "jan marini", "caudalie", "dr. jart", "dr jart", "laneige",
    "embryolisse", "erborian", "la roche-posay", "la roche posay", "avene",
    "avène", "cle de peau", "beaute", "beauté", "kiehl's", "kiehls",
    "origins", "fresh beauty", "olehenriksen", "ole henriksen",
    "boscia", "belif", "innisfree", "missha", "some by mi",
    "paula's choice", "paulas choice", "the ordinary", "niod",
    "medik8", "image skincare", "obagi", "skinceuticals",
    "murad", "glowbiotics", "revision skincare", "elta md",
    "colorescience", "dermablend", "it cosmetics", "urban decay",
    "too faced", "benefit cosmetics", "tarte", "becca", "smashbox",
]


def is_luxury_beauty(product_name: str) -> bool:
    """Return True if this product name contains a known luxury beauty brand (10% commission)."""
    name_lower = product_name.lower()
    return any(brand in name_lower for brand in LUXURY_BEAUTY_BRANDS)

# ── Curated Luxury Beauty Catalogue ──────────────────────────────────────────
# Hand-picked bestsellers across all 3 price tiers. All earn 10% Amazon commission.
# Format: (asin, name, price, brand)
CURATED_LUXURY_PRODUCTS = [
    # ── Entry Luxury $30–$75 ──
    ("B01N8QNZ4A", "Charlotte Tilbury Matte Revolution Lipstick in Pillow Talk", "38.00", "Charlotte Tilbury"),
    ("B0BVQPK7M1", "Charlotte Tilbury Hollywood Flawless Filter Foundation", "49.00", "Charlotte Tilbury"),
    ("B08QS58TZQ", "Charlotte Tilbury Airbrush Flawless Setting Spray", "38.00", "Charlotte Tilbury"),
    ("B07TGMJRHQ", "Rare Beauty by Selena Gomez Soft Pinch Liquid Blush", "23.00", "Rare Beauty"),
    ("B09B5Q9B8T", "Rare Beauty Perfect Strokes Universal Volumizing Mascara", "22.00", "Rare Beauty"),
    ("B0BZMB76WJ", "Merit Beauty Day Glow Highlighting Balm", "38.00", "Merit Beauty"),
    ("B09LSPWMQC", "Merit Beauty The Minimalist Complexion Stick", "38.00", "Merit Beauty"),
    ("B001UE8NVS", "NARS Radiant Creamy Concealer", "34.00", "NARS"),
    ("B00ARL9IN0", "NARS All Day Luminous Weightless Foundation", "54.00", "NARS"),
    ("B07WZZKN92", "Tatcha The Dewy Skin Cream Plumping & Hydrating Moisturizer", "68.00", "Tatcha"),
    ("B00VW16HCS", "Tatcha The Water Cream Oil-Free Pore Minimizing Moisturizer", "68.00", "Tatcha"),
    ("B08CXVXZ4M", "Drunk Elephant Lala Retro Whipped Moisturizer", "62.00", "Drunk Elephant"),
    ("B01LX6SXBW", "Hourglass Veil Mineral Primer", "52.00", "Hourglass"),
    ("B00NT8GVYE", "Sunday Riley Good Genes All-In-One Lactic Acid Treatment", "35.00", "Sunday Riley"),
    ("B09NPYF82Z", "Westman Atelier Baby Cheeks Blush Stick", "48.00", "Westman Atelier"),
    # ── Mid Luxury $75–$150 ──
    ("B01M1E0YAY", "Drunk Elephant C-Firma Fresh Day Serum", "90.00", "Drunk Elephant"),
    ("B07ZQYB98N", "Drunk Elephant Protini Polypeptide Moisturizer", "90.00", "Drunk Elephant"),
    ("B0856QV3TT", "Tatcha The Silk Serum Wrinkle Smoothing Retinol Alternative", "110.00", "Tatcha"),
    ("B0016FXNWC", "SK-II Facial Treatment Essence", "99.00", "SK-II"),
    ("B01NBXKWRG", "Estée Lauder Advanced Night Repair Synchronized Multi-Recovery Complex", "115.00", "Estée Lauder"),
    ("B07MRZQZKK", "Peter Thomas Roth Peptide 21 Wrinkle Resist Serum", "130.00", "Peter Thomas Roth"),
    ("B07H4J5TSK", "Kate Somerville ExfoliKate Intensive Exfoliating Treatment", "85.00", "Kate Somerville"),
    ("B00LG6YWKI", "Shiseido Benefiance Wrinkle Smoothing Cream", "75.00", "Shiseido"),
    ("B07QF7XLLZ", "Sunday Riley C.E.O. 15% Vitamin C Brightening Serum", "85.00", "Sunday Riley"),
    ("B00COSOAYW", "Lancôme Génifique Youth Activating Serum", "115.00", "Lancôme"),
    ("B01LXFAIRY", "Pat McGrath Labs MatteTrance Lipstick", "38.00", "Pat McGrath"),
    ("B09VQKFP9Y", "ILIA Super Serum Skin Tint SPF 40 Foundation", "48.00", "ILIA Beauty"),
    # ── High Luxury $150+ ──
    ("B0017RBM92", "La Mer The Moisturizing Soft Cream", "195.00", "La Mer"),
    ("B00B62RBUU", "La Mer The Treatment Lotion", "220.00", "La Mer"),
    ("B001F0ASDG", "SK-II Facial Treatment Essence Full Size", "185.00", "SK-II"),
    ("B08GPBZXPD", "Augustinus Bader The Rich Cream", "265.00", "Augustinus Bader"),
    ("B09GZBXD6B", "Dyson Airwrap Multi-Styler Complete Long", "599.00", "Dyson"),
    ("B08LKP9GQ1", "Dyson Supersonic Hair Dryer", "429.00", "Dyson"),
    ("B0B8VBD47Q", "Tom Ford Soleil Neige Eau de Parfum", "220.00", "Tom Ford Beauty"),
    ("B00BVHHQAA", "La Prairie Skin Caviar Luxe Cream", "450.00", "La Prairie"),
    ("B06Y15NJZM", "Sisley Paris Black Rose Cream Mask", "145.00", "Sisley"),
    ("B07RQP8NVB", "Tatcha Violet-C Brightening Serum", "88.00", "Tatcha"),
]


def get_curated_products(associate_tag: str = "auragirlcreat-20") -> list[dict]:
    """Return the full curated luxury beauty catalogue as product dicts."""
    products = []
    for asin, name, price, brand in CURATED_LUXURY_PRODUCTS:
        affiliate_url = f"https://www.amazon.com/dp/{asin}?tag={associate_tag}&linkCode=ll1&language=en_US"
        image_url = f"https://images-na.ssl-images-amazon.com/images/I/{asin}._SL500_.jpg"
        products.append({
            "name": name,
            "asin": asin,
            "amazon_url": affiliate_url,
            "image_url": image_url,
            "price": price,
            "category": "luxury_beauty",
            "trend_keyword": brand,
            "source_category": "Luxury Beauty (10%)",
        })
    return products


def _guess_category(name: str) -> str:
    """Guess niche from product name. Detects luxury beauty brands for accurate 10% commission."""
    n = name.lower()
    # Check luxury beauty brands first — 10% commission
    if any(brand in n for brand in LUXURY_BEAUTY_BRANDS):
        return "luxury_beauty"
    if any(w in n for w in ["nail", "makeup", "serum", "moisturizer", "cleanser", "toner", "mask", "lash", "lip", "foundation", "concealer", "blush", "skincare", "retinol", "vitamin c", "niacinamide", "spf", "sunscreen"]):
        return "beauty"
    if any(w in n for w in ["home", "decor", "candle", "vase", "throw", "blanket", "rug", "lamp", "shelf", "organizer", "pillow", "frame", "wall art"]):
        return "home_decor"
    if any(w in n for w in ["supplement", "collagen", "protein", "vitamin", "probiotic", "massage", "foam roller", "yoga", "workout", "wellness", "glow up"]):
        return "fitness"
    return "beauty"
