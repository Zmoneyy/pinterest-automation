#!/usr/bin/env python3
"""
Live test — actually calls SerpAPI and confirms Amazon products come back.
Uses 1 SerpAPI credit. Run sparingly.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.amazon_api import search_products, is_luxury_beauty

passed = 0
failed = 0

def ok(label):
    global passed; passed += 1
    print(f"  ✅ {label}")

def fail(label):
    global failed; failed += 1
    print(f"  ❌ FAIL: {label}")


print("=" * 60)
print("Live SerpAPI Test — uses 1 real credit")
print("=" * 60)

results = search_products("Tatcha amazon", category="luxury_beauty", max_results=10)

# 1. Got results back
if len(results) > 0:
    ok(f"{len(results)} products returned from SerpAPI")
else:
    fail("0 products returned — SerpAPI call failed or returned nothing")
    print("\n❌ Cannot continue — no results to validate")
    sys.exit(1)

# 2. Each result has required fields
missing_fields = []
for p in results:
    for field in ["name", "asin", "amazon_url"]:
        if not p.get(field):
            missing_fields.append(f"{field} missing on: {p.get('name','?')[:40]}")

if not missing_fields:
    ok("All results have name, asin, amazon_url")
else:
    for m in missing_fields:
        fail(m)

# 3. Amazon URLs are real affiliate links
bad_urls = [p for p in results if p.get("amazon_url") and "amazon.com" not in p["amazon_url"]]
if not bad_urls:
    ok("All URLs point to amazon.com")
else:
    fail(f"{len(bad_urls)} results have non-Amazon URLs")

# 4. Query-level luxury check (brand-level searches: Amazon often omits brand from title)
query = "Tatcha amazon"
query_is_luxury = is_luxury_beauty(query)
if query_is_luxury:
    ok(f"Search query '{query}' recognized as luxury — all {len(results)} results trusted as 10% commission")
else:
    luxury_results = [p for p in results if is_luxury_beauty(p.get("name", ""))]
    if luxury_results:
        ok(f"{len(luxury_results)}/{len(results)} results pass luxury filter by product name")
    else:
        fail("0 results passed luxury filter")

# 5. Print what we got
query = "Tatcha amazon"
query_is_luxury = is_luxury_beauty(query)
print(f"\n  Products returned (query recognized as luxury={query_is_luxury}):")
for p in results:
    would_queue = query_is_luxury or is_luxury_beauty(p.get("name", ""))
    status = "💎 QUEUE" if would_queue else "🚫 skip"
    print(f"    {status} {p.get('name','')[:65]}")
    print(f"           ASIN: {p.get('asin','')}  Price: ${p.get('price','?')}")

print()
print(f"Result: {passed} passed, {failed} failed")
if failed == 0:
    print("\n✅ SerpAPI is live and returning real Amazon products")
else:
    print(f"\n❌ {failed} test(s) failed")
    sys.exit(1)
