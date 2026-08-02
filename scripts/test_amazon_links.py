"""
Tests SerpAPI query fallback logic + direct link extraction.
Run: python3 scripts/test_amazon_links.py
"""
import os, sys, re, urllib.parse
from pathlib import Path

for line in (Path(__file__).parent.parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

import requests

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
TAG = "auragirlcreat-20"
TEST_TITLE = "7 Rhode Skin Dupes Under $15 That Deliver the Same Glazed Donut Glow"
REVIEW_MIN = 200

if not SERPAPI_KEY:
    print("❌ SERPAPI_KEY not set in .env"); sys.exit(1)


FILLER = r'\b(that|delivers?|the same|you need|i found|amazon finds?|routine|perfect|ultimate|only|every|girl|girls?|women|aesthetic|vibe|inspired|inspired by|style|era|moment|season|trend|trending|viral|hack|hacks?|steal|steals?|glazed donut|clean girl|glass skin|glow up|glow|glazed|donut)\b'
PRICE  = r'\bunder\s+\$?\d+\b|\$\d+\b'
COUNTS = r'^\d+\s+'

def strip(text, extras=''):
    t = re.sub(COUNTS, '', text, flags=re.I)
    t = re.sub(PRICE,  '', t,    flags=re.I)
    t = re.sub(FILLER, '', t,    flags=re.I)
    if extras:
        t = re.sub(extras, '', t, flags=re.I)
    return ' '.join(t.split()).strip(' -–—,')

def build_queries(title):
    seen, queries = set(), []
    def add(q):
        q = q.strip()
        if q and q.lower() not in seen:
            seen.add(q.lower()); queries.append(q)
    add(strip(title))
    lifestyle = r'\b(dupes?|affordable|budget|cheap|best|top)\b'
    add(strip(title, lifestyle))
    skip = {'the','a','an','and','or','for','with','of','to','in','on','by','from','at','that','this'}
    words = [w for w in re.sub(r'[^\w\s]','',title).split()
             if w.lower() not in skip and not w.isdigit() and len(w) > 2][:4]
    add(' '.join(words))
    add(title)
    return queries


def make_url(item):
    asin     = (item.get("asin") or item.get("product_id") or "").strip()
    raw_link = (item.get("link") or item.get("url") or "").strip()
    if not asin and raw_link:
        m = re.search(r'/dp/([A-Z0-9]{10})', raw_link)
        if m: asin = m.group(1)
    if asin:
        return f"https://www.amazon.com/dp/{asin}?tag={TAG}", "✅ DIRECT"
    elif raw_link and "amazon.com" in raw_link:
        clean = re.sub(r'/ref=[^/?]*', '', raw_link).split("?")[0]
        return f"{clean}?tag={TAG}", "🟡 LINK"
    return f"https://www.amazon.com/s?k={urllib.parse.quote_plus(item.get('title',''))}&tag={TAG}", "❌ SEARCH"


print(f"\n📌 {TEST_TITLE!r}\n")
queries = build_queries(TEST_TITLE)
print("🔁 Queries to try:")
for i, q in enumerate(queries, 1):
    print(f"   {i}. {q!r}")
print()

items, used_query = [], None
for q in queries:
    r = requests.get("https://serpapi.com/search.json", params={
        "engine": "amazon", "amazon_domain": "amazon.com", "k": q, "api_key": SERPAPI_KEY
    }, timeout=15)
    raw = r.json().get("organic_results", [])
    filtered = [i for i in raw if float(i.get("rating") or 0) >= 4.0 and int(i.get("reviews") or 0) >= REVIEW_MIN]
    print(f"   {len(raw):2d} raw / {len(filtered):2d} pass filter (4★ + {REVIEW_MIN}+ reviews) → {q!r}")
    if filtered:
        items, used_query = filtered, q
        break

print(f"\n✅ Using: {used_query!r}  ({len(items)} products)\n{'─'*68}")

direct = search = 0
for item in items[:10]:
    url, url_type = make_url(item)
    if "SEARCH" in url_type: search += 1
    else: direct += 1
    print(f"{url_type}  ⭐{item.get('rating')}  ({int(item.get('reviews') or 0):,} reviews)")
    print(f"  {(item.get('title') or '')[:65]}")
    print(f"  {url}\n")

print("─" * 68)
print(f"  ✅ Direct links : {direct}")
print(f"  ❌ Search pages : {search}")
print("  All good 🎉" if search == 0 else f"\n  ⚠️  {search} fell back to search pages")
