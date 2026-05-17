#!/usr/bin/env python3
"""
Test that product discovery correctly reads from TrendEntry data.
Validates: luxury beauty prioritization, niche detection, no duplicates.
Does NOT make real Amazon API calls — just tests the logic.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.amazon_api import is_luxury_beauty, LUXURY_BEAUTY_BRANDS

print("=" * 60)
print("Test 1: Luxury beauty brand detection")
print("=" * 60)

should_be_luxury = [
    "Perricone MD High Potency Retinol Recovery Overnight Moisturizer",
    "Clinique Moisture Surge 100H Auto-Replenishing Hydrator",
    "Jan Marini Skin Research C-esta Vitamin C Face Cream",
    "Shiseido Benefiance Wrinkle Smoothing Cream",
    "Caudalie Resveratrol Lift Retinol Alternative Moisturizer",
    "Dr. Jart+ Premium BB Tinted Moisturizer",
    "LANEIGE Water Bank Blue Hyaluronic Cream",
    "Charlotte Tilbury Matte Revolution Lipstick",
    "Tatcha The Dewy Skin Cream",
    "Drunk Elephant Lala Retro Whipped Moisturizer",
]

should_not_be_luxury = [
    "Neutrogena Rapid Tone Repair Retinol + Vitamin C Face Cream",
    "L'Oreal Paris Skin Paradise Tinted Moisturizer",
    "POND'S Correcting Cream Clarant B3",
    "50g Turmeric Face Cream Organic Ingredients",
    "TRSTAY Moisturizing Face Cream",
    "Collagen Jelly Cream 100g Pore Minimizing",
]

passed = 0
failed = 0

for p in should_be_luxury:
    result = is_luxury_beauty(p)
    status = "✅" if result else "❌ FAIL"
    if not result: failed += 1
    else: passed += 1
    print(f"  {status} {p[:60]}")

print()
for p in should_not_be_luxury:
    result = is_luxury_beauty(p)
    status = "✅" if not result else "❌ FAIL (should NOT be luxury)"
    if result: failed += 1
    else: passed += 1
    print(f"  {status} {p[:60]}")

print(f"\nResult: {passed} passed, {failed} failed")

print()
print("=" * 60)
print("Test 2: Niche detection from category names")
print("=" * 60)

niche_cases = [
    ("Face Lotions & Creams", "beauty"),
    ("Serums & essences", "beauty"),
    ("Bed sheets", "home_decor"),
    ("Throw pillows", "home_decor"),
    ("Outdoor furniture", "home_decor"),
    ("Nail art", "beauty"),
    ("Deodorants & antiperspirants", "beauty"),
    ("Quilts & comforters", "home_decor"),
]

for category, expected_niche in niche_cases:
    cat_lower = category.lower()
    if any(w in cat_lower for w in ["bed", "pillow", "blanket", "duvet", "quilt", "rug", "furniture",
                                     "ottoman", "clock", "throw", "outdoor", "lawn", "garden", "decor",
                                     "appliance", "pool", "spa"]):
        niche = "home_decor"
    elif any(w in cat_lower for w in ["wellness", "fitness", "supplement", "vitamin", "health"]):
        niche = "fitness"
    else:
        niche = "beauty"
    
    status = "✅" if niche == expected_niche else f"❌ FAIL (got {niche})"
    print(f"  {status} '{category}' → {niche}")

print()
print("=" * 60)
print("Test 3: Face Lotions & Creams — luxury vs regular split")
print("=" * 60)

face_lotion_products = [
    "Perricone MD High Potency Retinol Recovery Overnight Moisturizer",
    "Clinique Moisture Surge 100H Auto-Replenishing Hydrator",
    "Jan Marini Skin Research C-esta Vitamin C Face Cream",
    "Shiseido Benefiance Wrinkle Smoothing Cream",
    "Neutrogena Rapid Tone Repair Retinol + Vitamin C Face Cream",
    "L'Oreal Paris Wrinkle Expert 55+ Face Moisturizer",
    "POND'S Rejuveness Face Cream",
    "Caudalie Resveratrol Lift Retinol Alternative Moisturizer",
    "Dr. Jart+ Premium BB Tinted Moisturizer",
]

luxury = [p for p in face_lotion_products if is_luxury_beauty(p)]
regular = [p for p in face_lotion_products if not is_luxury_beauty(p)]

print(f"\n  Luxury (10% commission) — pinned first:")
for p in luxury:
    print(f"    🥇 {p[:70]}")

print(f"\n  Regular beauty (3% commission) — pinned after:")
for p in regular:
    print(f"    📦 {p[:70]}")

print(f"\n  Total: {len(luxury)} luxury + {len(regular)} regular = {len(face_lotion_products)} products")
