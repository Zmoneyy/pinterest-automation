"""
Run this before deploying to catch API/config errors early.
Usage: python3 scripts/test_apis.py
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Load .env
from pathlib import Path
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

PASS = "✅"
FAIL = "❌"
results = []

def check(name, fn):
    try:
        fn()
        print(f"  {PASS} {name}")
        results.append((name, True, None))
    except Exception as e:
        print(f"  {FAIL} {name}: {e}")
        results.append((name, False, str(e)))

# ── 1. Anthropic API ──────────────────────────────────────────────
print("\n🤖 Anthropic API")

def test_anthropic():
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    assert key and key != "PASTE_YOUR_NEW_KEY_HERE", "ANTHROPIC_API_KEY not set"
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=30,
        messages=[{"role": "user", "content": 'Reply with valid JSON: {"ok": true}'}]
    )
    # Find text block (skip ThinkingBlock)
    text = next((b.text for b in msg.content if hasattr(b, "text") and b.text.strip()), "")
    cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned).strip()
    parsed = json.loads(cleaned)
    assert parsed.get("ok") is True, f"Unexpected response: {text}"

check("Key valid + Sonnet 5 returns parseable JSON", test_anthropic)

# ── 2. SerpAPI ───────────────────────────────────────────────────
print("\n🔍 SerpAPI")

def test_serpapi_key():
    key = os.environ.get("SERPAPI_KEY", "")
    assert key, "SERPAPI_KEY not set"
    import requests
    r = requests.get("https://serpapi.com/account", params={"api_key": key}, timeout=10)
    data = r.json()
    assert "error" not in data or "Invalid" not in data.get("error", ""), f"Bad key: {data}"
    searches = data.get("plan_searches_left", "?")
    print(f"       → {searches} searches left this month")

def test_serpapi_amazon():
    key = os.environ.get("SERPAPI_KEY", "")
    assert key, "SERPAPI_KEY not set"
    import requests
    r = requests.get("https://serpapi.com/search.json", params={
        "engine": "amazon", "amazon_domain": "amazon.com",
        "k": "best self tanner", "api_key": key
    }, timeout=15)
    data = r.json()
    results = data.get("organic_results", [])
    assert len(results) > 0, f"No results. Response: {str(data)[:300]}"
    print(f"       → {len(results)} results returned")

check("API key valid", test_serpapi_key)
check("Amazon search returns results", test_serpapi_amazon)

# ── 3. Database ──────────────────────────────────────────────────
print("\n🗄️  Database")

def test_db():
    db_url = os.environ.get("DATABASE_URL", "")
    assert db_url, "DATABASE_URL not set"
    import sqlalchemy
    engine = sqlalchemy.create_engine(db_url, connect_args={"connect_timeout": 10})
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("SELECT 1"))

check("Supabase connection", test_db)

# ── Summary ──────────────────────────────────────────────────────
print("\n" + "─" * 40)
passed = sum(1 for _, ok, _ in results if ok)
total  = len(results)
print(f"  {passed}/{total} checks passed")
if passed < total:
    print("\n  Failed checks:")
    for name, ok, err in results:
        if not ok:
            print(f"    {FAIL} {name}: {err}")
    sys.exit(1)
else:
    print(f"\n  All good — safe to deploy 🚀")
