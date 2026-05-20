"""
Test: Send a pin to Tailwind as a draft.
Verifies the full flow: image URL accessible → Tailwind API call → draft created.
Uses 1 real Tailwind post (immediately deleted).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ['DATABASE_URL'] = os.environ.get('DATABASE_URL',
    'postgresql://postgres.ehksqgyndmyihvyzumgj:7qFTfJCkQh1SJxxj@aws-1-us-east-1.pooler.supabase.com:5432/postgres')

import requests
from app import create_app
from app.models import Pin
from config import Config

TAILWIND_KEY = 'tw_pk_12e125f4c6cd9697331efb5bd7eb479d'
ACCOUNT_ID   = '1641739'
BASE_URL     = f'https://api-v1.tailwind.ai/v1/accounts/{ACCOUNT_ID}'
HEADERS      = {'Authorization': f'Bearer {TAILWIND_KEY}', 'Content-Type': 'application/json'}

app = create_app()
with app.app_context():
    # 1. Get a real draft pin with an image
    pin = Pin.query.filter(Pin.status == 'draft', Pin.image_url.isnot(None)).order_by(Pin.id.desc()).first()
    assert pin, "FAIL: No draft pins with image_url found — save a pin first"
    print(f"✓ Found pin #{pin.id}: {pin.title[:50]}")
    print(f"  image_url: {pin.image_url}")

    # 2. Check image is publicly accessible
    img_resp = requests.head(pin.image_url, timeout=10)
    assert img_resp.status_code == 200, f"FAIL: Image URL not publicly accessible ({img_resp.status_code})"
    print(f"✓ Image URL is public (HTTP {img_resp.status_code})")

    # 3. Resolve board ID
    board_id = Config.PINTEREST_BOARDS.get(pin.board_name or '') or '1140044161863463132'
    print(f"✓ Board ID: {board_id} ({pin.board_name})")

    # 4. Send to Tailwind
    create_resp = requests.post(
        f'{BASE_URL}/posts',
        headers=HEADERS,
        json={
            'mediaUrl':    pin.image_url,
            'title':       (pin.title or '')[:100],
            'description': (pin.description or '')[:500],
            'url':         pin.amazon_url or pin.shop_url or 'https://auragirlessentials.com',
            'boardId':     board_id,
        },
        timeout=60,
    )
    assert create_resp.status_code == 201, f"FAIL: Tailwind create returned {create_resp.status_code}: {create_resp.text[:300]}"
    post_id = create_resp.json()['data']['post']['id']
    print(f"✓ Pin sent to Tailwind as draft — post_id: {post_id}")

    # 5. Verify it exists
    get_resp = requests.get(f'{BASE_URL}/posts/{post_id}', headers=HEADERS, timeout=10)
    assert get_resp.status_code == 200, "FAIL: Could not fetch created post"
    assert get_resp.json()['data']['post']['status'] == 'draft', "FAIL: Post is not in draft status"
    print(f"✓ Verified: post exists in Tailwind with status=draft")

    # 6. Clean up test post
    del_resp = requests.delete(f'{BASE_URL}/posts/{post_id}', headers=HEADERS, timeout=10)
    assert del_resp.json().get('data', {}).get('deleted'), "WARN: Could not delete test post"
    print(f"✓ Test post cleaned up")

    print("\n✅ Tailwind send works correctly.")
