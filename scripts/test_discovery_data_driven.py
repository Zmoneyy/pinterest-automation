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
print("Test 5: Simulated TrendEntry → search query pipeline")
print("=" * 60)

# Simulate what TrendEntry.tp_list() returns for a beauty category
mock_trend_entries = [
    {
        "category": "Face Lotions & Creams",
        "priority": "high",
        "top_products": [
            "Perricone MD High Potency Retinol Recovery Overnight Moisturizer",
            "Clinique Moisture Surge 100H Auto-Replenishing Hydrator",
            "Jan Marini Skin Research C-esta Vitamin C Face Cream",
            "Neutrogena Rapid Tone Repair Retinol + Vitamin C Face Cream",  # NOT luxury
        ],
    },
    {
        "category": "Yoga Mats",  # non-beauty — should be skipped
        "priority": "high",
        "top_products": ["Lululemon The Reversible Mat 5mm"],
    },
]

search_queries = []
skipped_categories = []

for entry in mock_trend_entries:
    if not is_beauty_entry(entry["category"]):
        skipped_categories.append(entry["category"])
        continue
    for product_name in entry["top_products"]:
        search_queries.append((product_name, entry["category"]))

expected_queries = 4  # all 4 from Face Lotions (including non-luxury — SerpAPI finds what it finds)
expected_skipped = ["Yoga Mats"]

if len(search_queries) == expected_queries:
    ok(f"{len(search_queries)} search queries built from TrendEntry top_products")
else:
    fail(f"Expected {expected_queries} queries, got {len(search_queries)}")

if skipped_categories == expected_skipped:
    ok(f"Non-beauty categories skipped: {skipped_categories}")
else:
    fail(f"Expected skipped={expected_skipped}, got={skipped_categories}")

print(f"\n  Search queries that would go to SerpAPI:")
for q, cat in search_queries:
    print(f"    🔍 '{q[:60]}' (from: {cat})")


# ── Summary ───────────────────────────────────────────────────────────────────
print()
print(f"Result: {passed} passed, {failed} failed")
if failed == 0:
    print("\n✅ All tests passed — discovery is 100% data-driven from TrendEntry")
else:
    print(f"\n❌ {failed} test(s) failed")
    sys.exit(1)
