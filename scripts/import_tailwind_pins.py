"""
Import published Tailwind pins into the local Pin DB.
Run from the repo root: python3 scripts/import_tailwind_pins.py
"""
import os, sys, json, requests
from datetime import datetime, timezone
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()  # read keys from .env so the script works on its own

TAILWIND_KEY = os.environ.get("TAILWIND_API_KEY")
if not TAILWIND_KEY:
    sys.exit("TAILWIND_API_KEY not set. Export it before running this script.")
ACCOUNT_ID   = "1641739"

BOARD_NAMES = {
    "1140044161863463132": "Beauty Finds & Skincare",
    "1140044161863463135": "Glam Home Decor Ideas",
    "1140044161863463136": "Wellness & Self Care Essentials",
    "1140044161863463150": "Nail Inspo & Nail Art Ideas",
    "1140044161863463151": "Luxury Look for Less Home Decor",
    "1140044161863463152": "Amazon Home Finds",
    "1140044161863463154": "Aesthetic Home Decor for Cozy Spaces",
    "1140044161863463155": "Affordable Beauty Essentials",
    "1140044161863463156": "Fitness Finds on Amazon",
}

def fetch_tailwind_posts():
    url = (
        f"https://api-v1.tailwind.ai/v1/accounts/{ACCOUNT_ID}/posts"
        f"?status=sent&startDate=2025-01-01T00:00:00Z"
        f"&endDate={datetime.now(timezone.utc).strftime('%Y-%m-%dT23:59:59Z')}&limit=100"
    )
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {TAILWIND_KEY}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"]["posts"]

def run():
    from app import create_app, db
    from app.models import Pin

    app = create_app()
    with app.app_context():
        posts = fetch_tailwind_posts()
        print(f"Fetched {len(posts)} posts from Tailwind.")

        imported = 0
        skipped  = 0

        for p in posts:
            pin_id = p.get("pinId") or p.get("id")

            # Skip if already imported (check by pinterest_pin_id)
            existing = Pin.query.filter_by(pinterest_pin_id=str(pin_id)).first()
            if existing:
                skipped += 1
                continue

            board_id   = str(p.get("boardId", ""))
            board_name = BOARD_NAMES.get(board_id, "Curated Finds")
            sent_ts    = p.get("sentAt")
            sent_at    = datetime.fromtimestamp(sent_ts, tz=timezone.utc) if sent_ts else datetime.now(timezone.utc)

            pin = Pin(
                title             = p.get("title") or "Aura Girl Essentials Find",
                description       = p.get("description") or "",
                image_url         = p.get("mediaUrl"),
                alt_text          = p.get("altText"),
                amazon_url        = p.get("url"),
                shop_url          = p.get("url"),
                board_name        = board_name,
                pinterest_pin_id  = str(pin_id),
                status            = Pin.STATUS_POSTED,
                posted_at         = sent_at,
                created_at        = sent_at,
            )
            db.session.add(pin)
            imported += 1
            print(f"  + [{board_name}] {pin.title[:60]}")

        db.session.commit()
        print(f"\nDone — {imported} imported, {skipped} already existed.")

if __name__ == "__main__":
    run()
