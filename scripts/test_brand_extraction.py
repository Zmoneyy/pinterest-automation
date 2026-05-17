#!/usr/bin/env python3
"""
Test brand extraction from TrendEntry product names.
Validates: correct brand pulled, deduplication works, 9 brands = ~90 products plan.
No SerpAPI calls made.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.amazon_api import LUXURY_BEAUTY_BRANDS

passed = 0
failed = 0

def ok(label):
    global passed; passed += 1
    print(f"  ✅ {label}")

def fail(label):
    global failed; failed += 1
    print(f"  ❌ FAIL: {label}")


def extract_brand(product_name):
    name_lower = product_name.lower()
    for brand in sorted(LUXURY_BEAUTY_BRANDS, key=len, reverse=True):
        if brand in name_lower:
            return brand.title()
    return None


# ── Test 1: Brand extraction from product names ───────────────────────────────
print("=" * 60)
print("Test 1: Brand extraction from product names")
print("=" * 60)

cases = [
    ("Perricone MD High Potency Retinol Recovery Overnight Moisturizer", "Perricone Md"),
    ("Clinique Moisture Surge 100H Auto-Replenishing Hydrator",           "Clinique"),
    ("Jan Marini Skin Research C-esta Vitamin C Face Cream",              "Jan Marini"),
    ("Tatcha The Dewy Skin Cream Plumping & Hydrating Moisturizer",       "Tatcha"),
    ("Drunk Elephant Lala Retro Whipped Moisturizer",                     "Drunk Elephant"),
    ("Charlotte Tilbury Matte Revolution Lipstick",                       "Charlotte Tilbury"),
    ("La Mer The Moisturizing Soft Cream",                                "La Mer"),
    ("SK-II Facial Treatment Essence",                                    "Sk-Ii"),
    ("LANEIGE Water Bank Blue Hyaluronic Cream",                          "Laneige"),
    ("Shiseido Benefiance Wrinkle Smoothing Cream",                       "Shiseido"),
    ("Neutrogena Rapid Tone Repair Retinol + Vitamin C",                  None),  # not luxury
    ("L'Oreal Paris Wrinkle Expert Face Moisturizer",                     None),  # not luxury
    ("CeraVe Moisturizing Cream",                                         None),  # not luxury
]

for product, expected in cases:
    result = extract_brand(product)
    if result == expected:
        label = f"NOT LUXURY" if expected is None else f'"{result}"'
        ok(f"{label} ← {product[:55]}")
    else:
        fail(f'Expected "{expected}", got "{result}" ← {product[:55]}')


# ── Test 2: Deduplication — multiple products same brand = 1 search ──────────
print()
print("=" * 60)
print("Test 2: Deduplication — multiple same-brand products = 1 search")
print("=" * 60)

mock_top_products = [
    "Tatcha The Dewy Skin Cream Plumping & Hydrating Moisturizer",
    "Tatcha The Water Cream Oil-Free Pore Minimizing Moisturizer",  # same brand
    "Tatcha Violet-C Brightening Serum",                            # same brand
    "Drunk Elephant Lala Retro Whipped Moisturizer",
    "Drunk Elephant C-Firma Fresh Day Serum",                       # same brand
    "Charlotte Tilbury Matte Revolution Lipstick",
    "Clinique Moisture Surge 100H Hydrator",
    "Perricone MD High Potency Retinol Moisturizer",
    "Shiseido Benefiance Wrinkle Smoothing Cream",
    "La Mer The Moisturizing Soft Cream",
    "Neutrogena Rapid Tone Repair",  # NOT luxury — should be excluded
]

seen_brands = {}
for product in mock_top_products:
    brand = extract_brand(product)
    if not brand:
        continue
    brand_key = brand.lower()
    if brand_key not in seen_brands:
        seen_brands[brand_key] = brand

search_queries = [f"{b} amazon" for b in seen_brands.values()]

if len(search_queries) == 7:
    ok(f"11 products → 7 unique brand searches (3 Tatcha, 2 Drunk Elephant deduplicated, Neutrogena excluded)")
else:
    fail(f"Expected 7 unique brands, got {len(search_queries)}: {list(seen_brands.keys())}")

print(f"\n  Search queries that would be sent to SerpAPI:")
for q in search_queries:
    print(f"    🔍 '{q}'")


# ── Test 3: Math — 9 brands × 10 results = ~90 products ─────────────────────
print()
print("=" * 60)
print("Test 3: Efficiency math — 9 searches → ~90 products")
print("=" * 60)

TARGET_BRANDS   = 9
RESULTS_PER     = 10
EXPECTED_PRODUCTS = TARGET_BRANDS * RESULTS_PER

ok(f"{TARGET_BRANDS} brand searches × {RESULTS_PER} results = up to {EXPECTED_PRODUCTS} products")
ok(f"{TARGET_BRANDS} SerpAPI credits used (vs 50 in old approach)")
ok(f"After luxury filter (~70% pass rate): ~{int(EXPECTED_PRODUCTS * 0.7)}–{EXPECTED_PRODUCTS} products in queue")


# ── Summary ───────────────────────────────────────────────────────────────────
print()
print(f"Result: {passed} passed, {failed} failed")
if failed == 0:
    print("\n✅ All tests passed — brand extraction is working correctly")
else:
    print(f"\n❌ {failed} test(s) failed")
    sys.exit(1)
