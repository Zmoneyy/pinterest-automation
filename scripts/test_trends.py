#!/usr/bin/env python3
"""
Smoke-test for the Trends page routes.
Run after every deploy: python3 scripts/test_trends.py
"""
import os, sys, re, requests

BASE     = os.getenv("APP_URL", "https://pinterest-automation-814656203168.us-central1.run.app")
PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")

PASS_COUNT = 0
FAIL_COUNT = 0

def check(name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        print(f"  ✅ {name}")
        PASS_COUNT += 1
    else:
        print(f"  ❌ {name}{': ' + detail if detail else ''}")
        FAIL_COUNT += 1

def make_session():
    s = requests.Session()
    # Log in via the dashboard password form
    r = s.post(f"{BASE}/login", data={"password": PASSWORD}, allow_redirects=True, timeout=10)
    if "logged_in" not in s.cookies and r.url.endswith("/login"):
        # Try empty password (no password set)
        r = s.post(f"{BASE}/login", data={"password": ""}, allow_redirects=True, timeout=10)
    return s

def get_first_entry_id(html):
    m = re.search(r'id="entry-(\d+)"', html)
    return int(m.group(1)) if m else None

def test_trends_page(s):
    print("\n── Trends page ──")
    r = s.get(f"{BASE}/trends", timeout=10)
    check("Status 200", r.status_code == 200, f"got {r.status_code}")
    html = r.text
    check("Has entry cards",        'entry-card' in html)
    check("Has drop zone",          'ss-dropzone' in html)
    check("Sidebar uses scrollIntoView", 'scrollIntoView' in html)
    check("Bottom padding present", '60vh' in html)
    check("clearScreenshots JS",    'clearScreenshots' in html)
    check("clear-screenshots route","clear-screenshots" in html)
    check("scroll-to-top button",   'scrollY' in html)
    return html

def test_screenshot_routes(s, entry_id):
    print("\n── Screenshot upload / clear ──")
    tiny = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    # Clear first so we start fresh
    s.post(f"{BASE}/trends/clear-screenshots/{entry_id}", timeout=10)

    # Upload 1
    r1 = s.post(f"{BASE}/trends/upload-screenshots/{entry_id}", timeout=10,
                json={"images": [{"image": tiny, "mime_type": "image/png"}]})
    d1 = r1.json()
    check("Upload 1 → ok",   d1.get("ok") is True, str(d1))
    check("Count = 1",       d1.get("count") == 1,  f"count={d1.get('count')}")

    # Upload 1 more — should MERGE to 2
    r2 = s.post(f"{BASE}/trends/upload-screenshots/{entry_id}", timeout=10,
                json={"images": [{"image": tiny, "mime_type": "image/png"}]})
    d2 = r2.json()
    check("Upload 2nd merges → count 2", d2.get("count") == 2, f"count={d2.get('count')}")

    # Clear
    r3 = s.post(f"{BASE}/trends/clear-screenshots/{entry_id}", timeout=10)
    check("Clear → ok", r3.json().get("ok") is True)

    # Confirm cleared (upload again and count should be 1, not 3)
    r4 = s.post(f"{BASE}/trends/upload-screenshots/{entry_id}", timeout=10,
                json={"images": [{"image": tiny, "mime_type": "image/png"}]})
    d4 = r4.json()
    check("After clear, upload starts fresh at 1", d4.get("count") == 1, f"count={d4.get('count')}")

    # Clean up
    s.post(f"{BASE}/trends/clear-screenshots/{entry_id}", timeout=10)

def test_priority(s, entry_id):
    print("\n── Priority route ──")
    for p in ("high", "medium", "low"):
        r = s.post(f"{BASE}/trends/set-priority/{entry_id}", timeout=10, json={"priority": p})
        check(f"Set priority={p}", r.json().get("ok") is True)

if __name__ == "__main__":
    print(f"Testing {BASE}")
    s = make_session()
    try:
        html = test_trends_page(s)
        entry_id = get_first_entry_id(html)
        if entry_id:
            test_screenshot_routes(s, entry_id)
            test_priority(s, entry_id)
        else:
            print("\n  ⚠️  No entry cards found — add some trend entries first")
    except Exception as e:
        print(f"\n💥 Crash: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    print(f"\n{'='*40}")
    print(f"  {PASS_COUNT} passed, {FAIL_COUNT} failed")
    if FAIL_COUNT:
        sys.exit(1)
