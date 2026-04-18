# Pinterest Automation App — Project Context

## Project Info
- **Repo:** `zmoneyy/pinterest-automation`
- **Branch:** `claude/pinterest-affiliate-automation-VRZU2`
- **Working dir:** `/Users/zamzamyusuf/pinterest-automation`
- **Stack:** Python, Flask, SQLAlchemy, Pillow, Anthropic Claude API, Pinterest API

## What This App Does
Automated Pinterest affiliate marketing tool for "Aura Girl Essentials" brand.
- Generates 5 pins/day using trending keywords
- Uses Claude (Anthropic) to write keyword-stuffed titles, descriptions, hashtags
- Posts pins automatically to Pinterest via official API
- Links all pins to Benable affiliate collection page
- Dashboard to approve/reject/edit pins before posting

## Key Files
- `app/imagen_api.py` — image generation (currently PIL collage, replacing with Nano Banana Pro)
- `app/scheduler.py` — daily pin generation (5 pins/day)
- `app/ai_writer.py` — Claude content generation
- `app/routes.py` — all Flask routes
- `app/models.py` — DB models + Config
- `templates/setup.html` — setup/config page
- `config.py` — app configuration

## Pin Content Strategy
- Title format: `"Spring Nail Inspo 2026, Spring Nail Ideas, Spring Nail Art, Spring Nails 2027"`
- Description: direct CTA → "This pin is about [keyword], [variation]" → soft seasonal CTA
- 5 pins/day (safe for affiliate accounts, won't trigger spam filter)
- Style: Jackie Aina editorial roundup collage aesthetic

## What's Been Built ✅
- Full Flask app: dashboard, products, trends, setup pages
- Pinterest OAuth + pin posting
- Claude writes all pin content
- PIL collage image generator (being replaced)
- Trends CSV upload + Claude analysis
- Pin approval/reject/edit dashboard

## What Needs to Be Built Next (in order)

### 1. Nano Banana Pro Image Generation (HIGHEST PRIORITY)
Replace `generate_collage_image()` in `app/imagen_api.py` with Google Gemini 3 Pro Image API (aka "Nano Banana Pro").
- User uploads product images → Nano Banana Pro generates beautiful editorial Pinterest pin
- Overlay title + CTA pill on top using PIL
- Add `GEMINI_API_KEY` to config + setup page
- Current PIL collage fails because Amazon blocks server-side image requests

### 2. Fix Amazon Image Fetching
- `app/imagen_api.py` → `_load_product_image()` → add browser-like `User-Agent` headers to `requests.get()`

### 3. Per-Category Benable URLs
- Each product category (beauty, home, fashion) needs its own Benable list URL
- Currently one global `BENABLE_URL` — need category → URL mapping in Setup
- Scheduler picks the right URL based on dominant product category in pin

### 4. Pinterest Board Routing
- Pins should post to themed boards (Beauty, Home Decor, Fashion) not one default board
- `post_pin()` in `app/pinterest_api.py` already accepts `board_id` param
- Need category → board_id mapping in Setup page

## Brand Info
- Brand name: Aura Girl Essentials
- Benable URL: configured in setup
- Target audience: women who love affordable aesthetic finds
- Pinterest style: Jackie Aina editorial, warm, aspirational, never salesy
