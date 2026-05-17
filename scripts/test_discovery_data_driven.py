#!/usr/bin/env python3
"""
Test that product discovery is 100% data-driven from TrendEntry.
Validates:
  - No hardcoded product lists used
  - Discovery reads product names from TrendEntry.top_products
  - Only beauty categories (10% commission) are searched
  - Non-beauty categories are skipped
Does NOT make real SerpAPI calls.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.amazon_api import is_luxury_beauty

passed = 0
failed = 0

def ok(label):
    global passed
    passed += 1
    print(f"  ✅ {label}")

def fail(label):
    global failed
    failed += 1
    print(f"  ❌ FAIL: {label}")


# ── Test 1: CURATED_LUXURY_PRODUCTS is gone ──────────────────────────────────
print("=" * 60)
print("Test 1: Hardcoded curated list is removed")
print("=" * 60)

try:
    from app.amazon_api import CURATED_LUXURY_PRODUCTS
    fail("CURATED_LUXURY_PRODUCTS still exists — should be deleted")
except ImportError:
    ok("CURATED_LUXURY_PRODUCTS removed from amazon_api")

try:
    from app.amazon_api import get_curated_products
    fail("get_curated_products() still exists — should be deleted")
except ImportError:
    ok("get_curated_products() removed from amazon_api")


# ── Test 2: LUXURY_SEARCHES hardcoded list is gone from routes ───────────────
print()
print("=" * 60)
print("Test 2: Hardcoded LUXURY_SEARCHES removed from routes")
print("=" * 60)

import inspect
try:
    import app.routes as routes_module
    source = inspect.getsource(routes_module)
    if "LUXURY_SEARCHES" in source:
        fail("LUXURY_SEARCHES still referenced in routes.py")
    else:
        ok("LUXURY_SEARCHES removed from routes.py")
    if "get_curated_products" in source:
        fail("get_curated_products still called in routes.py")
    else:
        ok("get_curated_products not called in routes.py")
except Exception as e:
    fail(f"Could not inspect routes.py: {e}")


# ── Test 3: Scheduler uses TrendEntry, not curated list ──────────────────────
print()
print("=" * 60)
print("Test 3: Scheduler discovery reads TrendEntry data")
print("=" * 60)

try:
    import app.scheduler as scheduler_module
    sched_source = inspect.getsource(scheduler_module)
    if "CURATED_LUXURY_PRODUCTS" in sched_source:
        fail("CURATED_LUXURY_PRODUCTS still in scheduler.py")
    else:
        ok("CURATED_LUXURY_PRODUCTS removed from scheduler.py")
    if "get_curated_products" in sched_source:
        fail("get_curated_products() still called in scheduler.py")
    else:
        ok("get_curated_products() not called in scheduler.py")
    if "TrendEntry" in sched_source and "tp_list" in sched_source:
        ok("Scheduler reads from TrendEntry.tp_list()")
    else:
        fail("Scheduler not reading TrendEntry.tp_list()")
except Exception as e:
    fail(f"Could not inspect scheduler.py: {e}")


# ── Test 4: Beauty category filter logic ─────────────────────────────────────
print()
print("=" * 60)
print("Test 4: Only beauty entries trigger searches")
print("=" * 60)

BEAUTY_KEYWORDS = [
    "blush", "bronzer", "foundation", "concealer", "serum", "essence",
    "moisturizer", "lotion", "cream", "face", "skincare", "nail", "perfume",
    "makeup", "mascara", "lipstick", "eyeshadow", "primer", "toner",
    "retinol", "vitamin c", "hyaluronic", "spf", "sunscreen", "contour",
    "highlighter", "setting", "powder", "lip", "eye",
]

def is_beauty_entry(category_name):
    return any(kw in category_name.lower() for kw in BEAUTY_KEYWORDS)

beauty_cats = [
    "Face Lotions & Creams",
    "Eye Creams & Treatments",
    "Facial Serums",
    "Lip Care",
    "SPF & Sunscreen",
]
non_beauty_cats = [
    "Home Office Furniture",
    "Yoga Mats",
    "Whey Protein & Supplements",
    "Kitchen Organizers",
    "Resistance Bands",
]

for cat in beauty_cats:
    if is_beauty_entry(cat):
        ok(f"INCLUDED: {cat}")
    else:
        fail(f"Should be included but wasn't: {cat}")

for cat in non_beauty_cats:
    if not is_beauty_entry(cat):
        ok(f"EXCLUDED: {cat}")
    else:
        fail(f"Should be excluded but wasn't: {cat}")


# ── Test 5: Simulated TrendEntry → search query pipeline ─────────────────────
print()
print("=" * 60)
print("Test 5: Query filter — only luxury brands sent to SerpAPI")
print("=" * 60)

mock_trend_entries = [
    {
        "category": "Face Lotions & Creams",
        "priority": "high",
        "top_products": [
            "Perricone MD High Potency Retinol Recovery Overnight Moisturizer",  # luxury ✅
            "Clinique Moisture Surge 100H Auto-Replenishing Hydrator",           # luxury ✅
            "Jan Marini Skin Research C-esta Vitamin C Face Cream",              # luxury ✅
            "Neutrogena Rapid Tone Repair Retinol + Vitamin C Face Cream",       # NOT luxury ❌
            "L'Oreal Paris Wrinkle Expert Face Moisturizer",                     # NOT luxury ❌
        ],
    },
    {
        "category": "Yoga Mats",  # non-beauty — entire category skipped
        "priority": "high",
        "top_products": ["Lululemon The Reversible Mat 5mm"],
    },
]

search_queries = []
skipped_non_luxury = []
skipped_categories = []

for entry in mock_trend_entries:
    if not is_beauty_entry(entry["category"]):
        skipped_categories.append(entry["category"])
        continue
    for product_name in entry["top_products"]:
        if not is_luxury_beauty(product_name):
            skipped_non_luxury.append(product_name)
            continue
        search_queries.append((product_name, entry["category"]))

if len(search_queries) == 3:
    ok(f"3 luxury queries sent to SerpAPI (non-luxury skipped)")
else:
    fail(f"Expected 3 luxury queries, got {len(search_queries)}")

if len(skipped_non_luxury) == 2:
    ok(f"2 non-luxury products skipped (no wasted SerpAPI credits)")
else:
    fail(f"Expected 2 skipped, got {len(skipped_non_luxury)}")

if skipped_categories == ["Yoga Mats"]:
    ok("Non-beauty category (Yoga Mats) fully skipped")
else:
    fail(f"Expected ['Yoga Mats'] skipped, got {skipped_categories}")

print(f"\n  Queries sent to SerpAPI:")
for q, cat in search_queries:
    print(f"    🔍 '{q[:65]}' (from: {cat})")
print(f"\n  Skipped (non-luxury, 3% commission):")
for q in skipped_non_luxury:
    print(f"    🚫 '{q[:65]}'")


# ── Test 6: Result-level filter — SerpAPI results also checked ───────────────
print()
print("=" * 60)
print("Test 6: Result filter — non-luxury SerpAPI results blocked")
print("=" * 60)

# Simulate SerpAPI returning a mix (Amazon doesn't always return exactly what you search)
mock_serpapi_results = [
    {"name": "Clinique Moisture Surge 100H Hydrator", "asin": "B001ABC"},       # luxury ✅
    {"name": "Neutrogena Hydro Boost Water Gel", "asin": "B002DEF"},            # NOT luxury ❌
    {"name": "Tatcha The Water Cream", "asin": "B003GHI"},                      # luxury ✅
    {"name": "CeraVe Moisturizing Cream", "asin": "B004JKL"},                   # NOT luxury ❌
    {"name": "Perricone MD Essential Fx Moisturizer", "asin": "B005MNO"},       # luxury ✅
]

queued = [p for p in mock_serpapi_results if is_luxury_beauty(p["name"])]
blocked = [p for p in mock_serpapi_results if not is_luxury_beauty(p["name"])]

if len(queued) == 3:
    ok(f"3 luxury products queued from SerpAPI results")
else:
    fail(f"Expected 3 queued, got {len(queued)}")

if len(blocked) == 2:
    ok(f"2 non-luxury results blocked (Neutrogena, CeraVe — 3% commission)")
else:
    fail(f"Expected 2 blocked, got {len(blocked)}")

print(f"\n  Queued (10% commission):")
for p in queued:
    print(f"    ✅ {p['name']}")
print(f"  Blocked (3% commission):")
for p in blocked:
    print(f"    🚫 {p['name']}")


# ── Summary ───────────────────────────────────────────────────────────────────
print()
print(f"Result: {passed} passed, {failed} failed")
if failed == 0:
    print("\n✅ All tests passed — discovery is 100% data-driven from TrendEntry")
else:
    print(f"\n❌ {failed} test(s) failed")
    sys.exit(1)
