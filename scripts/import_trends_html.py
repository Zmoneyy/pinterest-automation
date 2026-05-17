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
        # Fallback: look for product-category-info div
        info_div = soup.find(attrs={"data-test-id": "product-category-info"})
        if info_div:
            # First substantial text node is the category name
            for tag in info_div.find_all(["h1", "h2", "h3"]):
                text = tag.get_text(strip=True)
                if text and len(text) > 3:
                    category = text
                    break
            if not category:
                # Just grab the first line of text
                full_text = info_div.get_text(separator="\n", strip=True)
                first_line = full_text.split("\n")[0].strip()
                if first_line and len(first_line) > 3:
                    category = first_line

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

    # Key metrics (aggregate)
    metrics = {}
    for div in soup.find_all("div", attrs={"data-test-id": re.compile(r"-growth-summary$")}):
        metric_type = div["data-test-id"].replace("-growth-summary", "")
        pct_span = div.find("span", class_=re.compile("YLh4cb"))
        if pct_span:
            metrics[metric_type] = pct_span.get_text(strip=True)

    # Top products from carousel (brand/store names as listed on Pinterest)
    products = []
    carousel = soup.find(attrs={"data-test-id": "top-products-carousel-items"})
    if carousel:
        seen = set()
        for child in carousel.children:
            if not hasattr(child, "get_text"):
                continue
            # Each child is a product tile — grab the first link aria-label
            for a in child.find_all("a"):
                label = a.get("aria-label", "").replace("; Opens a new tab", "").strip()
                text = a.get_text(strip=True).replace("; Opens a new tab", "").strip()
                name = label or text
                # Skip generic store names without context
                if name and name not in seen and name not in {"Walmart", "Amazon", "Target", "SHEIN", "Sephora", "Ulta Beauty"}:
                    seen.add(name)
                    products.append(name)
                    break

    return category, keywords, metrics, products

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
    """Trigger AI brief generation for the entry, passing metrics as context."""
    # Build a metrics summary string to inject into the brief
    metrics_text = ""
    metric_labels = {
        "OUTBOUND_CLICK": "Outbound clicks",
        "ENGAGEMENT": "Engagement",
        "SAVE": "Saves",
        "IMPRESSION": "Impressions",
    }
    if metrics:
        parts = []
        for k, v in metrics.items():
            label = metric_labels.get(k, k)
            parts.append(f"{label}: {v} growth (last 30 days)")
        metrics_text = "\n".join(parts)

    # Pass metrics as extra context via POST body
    r = s.post(
        f"{BASE}/trends/generate-brief/{entry_id}",
        json={"metrics_context": metrics_text},
        timeout=60,
    )
    return r.json()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/import_trends_html.py <path_to_saved_html>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"\nParsing: {path}")

    category, keywords, metrics, products = parse_html(path)

    print(f"\n📂 Category: {category}")
    print(f"🔍 Keywords ({len(keywords)}): {', '.join(keywords[:10])}{'...' if len(keywords) > 10 else ''}")
    print(f"📊 Metrics: {metrics}")
    print(f"🛍️  Products found: {', '.join(products[:5]) if products else 'none'}")

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

    # Update products if we found any
    if products:
        r = s.post(f"{BASE}/trends/update-products/{entry_id}", json={"products": products}, timeout=10)
        result = r.json()
        if result.get("ok"):
            print(f"✓ Updated {len(products)} products")
        else:
            print(f"⚠️  Products update: {result}")

    # Generate AI brief
    print(f"\n🧠 Generating AI brief...")
    result = generate_brief(s, entry_id, category, keywords, metrics)
    if result.get("ok"):
        print(f"✓ AI brief generated successfully!")
    else:
        print(f"⚠️  Brief generation: {result}")

    print(f"\n✅ Done! Check the '{matched_name}' entry in your Trends tab.")
