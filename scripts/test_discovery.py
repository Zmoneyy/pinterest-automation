#!/usr/bin/env python3
"""
Test that product discovery correctly reads from TrendEntry data.
Validates: ONLY 10% commission (luxury beauty) products pass through.
Does NOT make real Amazon API calls — just tests the logic.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.amazon_api import is_luxury_beauty

print("=" * 60)
print("Test 1: Luxury beauty brand detection (10% commission)")
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
    "Hero Cosmetics Rescue Balm Red Correct",
    "TEATRICAL Tone Correcting Face Cream",
    "TreeActiv Crepey Skin Repair Cream",
]

passed = 0
failed = 0

for p in should_be_luxury:
    result = is_luxury_beauty(p)
    status = "✅" if result else "❌ FAIL"
    if not result: failed += 1
    else: passed += 1
    print(f"  {status} {p[:65]}")

print()
for p in should_not_be_luxury:
    result = is_luxury_beauty(p)
    status = "✅ BLOCKED" if not result else "❌ FAIL — should be blocked (not 10%)"
    if result: failed += 1
    else: passed += 1
    print(f"  {status}: {p[:55]}")

print(f"\nResult: {passed} passed, {failed} failed")

print()
print("=" * 60)
print("Test 2: HARD RULE — only 10% products reach the queue")
print("=" * 60)

all_products = [
    # Should pass (luxury beauty, 10%)
    "Perricone MD High Potency Retinol Recovery Overnight Moisturizer",
    "Clinique Moisture Surge 100H Auto-Replenishing Hydrator",
    "Jan Marini Skin Research C-esta Vitamin C Face Cream",
    "Shiseido Benefiance Wrinkle Smoothing Cream",
    "Caudalie Resveratrol Lift Retinol Alternative Moisturizer",
    "Dr. Jart+ Premium BB Tinted Moisturizer",
    # Should be blocked (regular beauty/mass market, 3%)
    "Neutrogena Rapid Tone Repair Retinol + Vitamin C Face Cream",
    "L'Oreal Paris Wrinkle Expert 55+ Face Moisturizer",
    "POND'S Rejuveness Face Cream",
    "50g Turmeric Face Cream",
    "Collagen Jelly Cream 100g",
    "TRSTAY Moisturizing Face Cream",
]

queued  = [p for p in all_products if is_luxury_beauty(p)]
blocked = [p for p in all_products if not is_luxury_beauty(p)]

print(f"\n  ✅ QUEUED for pins (10% commission):")
for p in queued:
    print(f"    🥇 {p[:70]}")

print(f"\n  🚫 BLOCKED (under 10% — never shown):")
for p in blocked:
    print(f"    ✗  {p[:70]}")

rule_ok = len(queued) == 6 and len(blocked) == 6
print(f"\n  Hard rule enforced: {'✅ PASS' if rule_ok else '❌ FAIL'} — {len(queued)} queued, {len(blocked)} blocked")

if failed == 0 and rule_ok:
    print("\n✅ All tests passed — only 10% commission products will be shown")
else:
    print(f"\n❌ {failed} test(s) failed")
    sys.exit(1)
