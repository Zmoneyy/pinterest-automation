#!/usr/bin/env python3
"""
Parse a saved Pinterest Trends category page (HTML) and update the
matching trend entry in the app with extracted keywords and data.

Usage:
    python3 scripts/import_trends_html.py ~/Desktop/"(48) Pinterest.htm"
    python3 scripts/import_trends_html.py ~/Desktop/face_lotions.htm
"""
import sys, re, json, os
import requests
from bs4 import BeautifulSoup

BASE     = os.getenv("APP_URL", "https://pinterest-automation-814656203168.us-central1.run.app")
PASSWORD = os.getenv("DASHBOARD_PASSWORD", "Pinnymoney30!")

def login():
    s = requests.Session()
    s.post(f"{BASE}/login", data={"password": PASSWORD}, allow_redirects=True, timeout=10)
    return s

def parse_html(path):
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # Category name
    category = None
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(strip=True)
        # The category heading is in the product-category-info section
        if tag.get("class") and any("wyEmcc" in c for c in tag.get("class", [])):
            if text and "Pinterest Trends" not in text and "Product category" not in text:
                if len(text) > 3:
                    category = text
                    break

    if not category:
        # Fallback: look for the Related to "X" heading
        for tag in soup.find_all(["h2"]):
            text = tag.get_text(strip=True)
            if text.startswith("Related to "):
                category = text.replace("Related to ", "").strip()
                break

    # Search query keywords (trend pills)
    keywords = []
    for a in soup.find_all("a", attrs={"data-test-id": re.compile(r"^trend-pill-")}):
        label = a.get("aria-label", "")
        kw = label.replace("Go to the Trend Detail page for ", "").strip()
        if kw:
            keywords.append(kw)

    # Key metrics
    metrics = {}
    for div in soup.find_all("div", attrs={"data-test-id": re.compile(r"-growth-summary$")}):
        metric_type = div["data-test-id"].replace("-growth-summary", "")
        pct_span = div.find("span", class_=re.compile("YLh4cb"))
        if pct_span:
            metrics[metric_type] = pct_span.get_text(strip=True)

    return category, keywords, metrics

def find_entry(s, category):
    """Find the trend entry ID whose category name fuzzy-matches."""
    r = s.get(f"{BASE}/trends", timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")
    entries = []
    for div in soup.find_all("div", class_="entry-card"):
        eid = div.get("id", "").replace("entry-", "")
        name_div = div.find("div", class_="entry-cat-name")
        if name_div and eid:
            entries.append((eid, name_div.get_text(strip=True).replace("🛍️", "").strip()))

    # Fuzzy match
    cat_lower = category.lower().replace("&", "and").replace(" ", "")
    for eid, name in entries:
        name_lower = name.lower().replace("&", "and").replace(" ", "")
        if cat_lower in name_lower or name_lower in cat_lower:
            return eid, name
        # Check word overlap
        cat_words = set(re.findall(r'\w+', category.lower()))
        name_words = set(re.findall(r'\w+', name.lower()))
        overlap = len(cat_words & name_words) / max(len(cat_words), 1)
        if overlap >= 0.6:
            return eid, name

    return None, None

def generate_brief(s, entry_id, category, keywords, metrics):
    """Trigger AI brief generation for the entry."""
    r = s.post(f"{BASE}/trends/generate-brief/{entry_id}", timeout=60)
    return r.json()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/import_trends_html.py <path_to_saved_html>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"\nParsing: {path}")

    category, keywords, metrics = parse_html(path)

    print(f"\n📂 Category: {category}")
    print(f"🔍 Keywords ({len(keywords)}): {', '.join(keywords[:10])}{'...' if len(keywords) > 10 else ''}")
    print(f"📊 Metrics: {metrics}")

    if not category or not keywords:
        print("\n❌ Could not extract category or keywords. Make sure this is a Pinterest Trends category page.")
        sys.exit(1)

    print(f"\nLogging into app...")
    s = login()

    entry_id, matched_name = find_entry(s, category)
    if not entry_id:
        print(f"\n❌ No matching entry found for '{category}'. Make sure you've saved this category in your Trends tab.")
        sys.exit(1)

    print(f"✓ Matched entry: '{matched_name}' (id={entry_id})")

    # Generate AI brief
    print(f"\n🧠 Generating AI brief...")
    result = generate_brief(s, entry_id, category, keywords, metrics)
    if result.get("ok"):
        print(f"✓ AI brief generated successfully!")
    else:
        print(f"⚠️  Brief generation: {result}")

    print(f"\n✅ Done! Check the '{matched_name}' entry in your Trends tab.")
