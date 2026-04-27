"""
Pinterest pin image generator.

Priority order:
  1. Claude Design (primary) — Claude generates HTML pin, Playwright screenshots it to PNG.
  2. gpt-image-1 (fallback) — OpenAI image generation with product photo reference.
  3. PIL collage (last resort) — basic editorial collage using Pillow.
"""
import io
import logging
import math
import os
import random
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

OUTPUT_DIR  = "/tmp/generated_images"
GCS_BUCKET  = "pinterest-automation-images-814656203168"
GCS_BASE_URL = f"https://storage.googleapis.com/{GCS_BUCKET}"


def _upload_to_gcs(local_path: str) -> Optional[str]:
    """Upload a local file to GCS and return its public URL."""
    try:
        from google.cloud import storage as gcs
        client = gcs.Client()
        bucket = client.bucket(GCS_BUCKET)
        fname  = os.path.basename(local_path)
        blob   = bucket.blob(f"pins/{fname}")
        blob.upload_from_filename(local_path, content_type="image/png")
        return f"{GCS_BASE_URL}/pins/{fname}"
    except Exception as e:
        logger.error(f"GCS upload failed: {e}")
        return None

# ── Canvas dimensions (Pinterest 2:3 portrait) ────────────────────────────
W, H = 1000, 1500

# ── Colour palette ────────────────────────────────────────────────────────
CREAM        = (248, 243, 236)   # warm ivory background
DARK_BROWN   = (42,  35,  28)    # title text / ornament
MID_BROWN    = (90,  80,  70)    # subtitle / light text
PILL_BG      = (30,  28,  26)    # CTA pill background (near-black)
PILL_TEXT    = (255, 255, 255)   # CTA pill text
DIVIDER      = (160, 145, 130)   # thin rule / ornament

# ── Section heights ───────────────────────────────────────────────────────
HEADER_H   = 230   # theme title + ornament + subtitle
PRODUCT_H  = 1140  # product mosaic area
FOOTER_H   = H - HEADER_H - PRODUCT_H   # 130 px for CTA pill + signature

MARGIN     = 32    # left/right padding
INNER_W    = W - 2 * MARGIN


# ══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════

def generate_claude_design_pin(
    product_image_url: str,
    product_name: str,
    amazon_url: str,
    niche: str = "beauty",
    price: str = "",
) -> Optional[str]:
    """
    Generate a Pinterest pin using Claude Design:
    1. Send product info + image to Claude API with the system prompt
    2. Claude returns a full HTML pin (1000x1500px)
    3. Playwright screenshots it to PNG
    4. Upload PNG to GCS, return URL
    """
    import base64
    import re
    import requests as req
    from config import Config

    if not Config.ANTHROPIC_API_KEY:
        logger.warning("Claude Design: no ANTHROPIC_API_KEY")
        return None

    try:
        # Load system prompt
        system_prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "system_prompt.txt")
        with open(system_prompt_path) as f:
            system_prompt = f.read()

        # Fetch and base64-encode the product image
        img_b64 = None
        if product_image_url:
            try:
                img_resp = req.get(product_image_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if img_resp.ok:
                    img_b64 = base64.standard_b64encode(img_resp.content).decode("utf-8")
                    img_media_type = img_resp.headers.get("content-type", "image/jpeg").split(";")[0]
            except Exception as e:
                logger.warning(f"Claude Design: could not fetch product image: {e}")

        # Build user message
        user_text = f"Generate a Pinterest pin for this product.\n\nProduct: {product_name}\nAmazon URL: {amazon_url}\nCategory: {niche}"
        if price:
            user_text += f"\nPrice: {price}"

        content = []
        if img_b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": img_media_type, "data": img_b64},
            })
        content.append({"type": "text", "text": user_text})

        import anthropic
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )

        html = response.content[0].text.strip()

        # Strip markdown fences if Claude wrapped it anyway
        html = re.sub(r'^```html?\s*', '', html, flags=re.IGNORECASE)
        html = re.sub(r'\s*```$', '', html)

        # ── CRITICAL: inject base64 image so Playwright (file://) can render it ──
        # Claude generates <img src="IMAGE_PLACEHOLDER"> or an http URL.
        # Playwright running from file:// can't load external URLs, so we must
        # embed the product image as a data URI directly in the HTML.
        if img_b64:
            data_uri = f"data:{img_media_type};base64,{img_b64}"
            # Replace the placeholder Claude was instructed to use
            html = html.replace("IMAGE_PLACEHOLDER", data_uri)
            # Also replace any raw http(s) URL that matches the original product image
            if product_image_url:
                html = html.replace(product_image_url, data_uri)
            # Fallback: replace the first external img src we find (covers cases where
            # Claude used a different URL or ignored the placeholder instruction)
            html = re.sub(
                r'(<img\b[^>]*\bsrc=")[^"]*(?:http|IMAGE_PLACEHOLDER)[^"]*(")',
                rf'\g<1>{data_uri}\2',
                html,
                count=1,
            )

        # Save HTML to temp file
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        pin_id = uuid.uuid4().hex
        html_path = os.path.join(OUTPUT_DIR, f"{pin_id}.html")
        png_path  = os.path.join(OUTPUT_DIR, f"{pin_id}.png")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        # Screenshot with Playwright
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = browser.new_page(viewport={"width": 1000, "height": 1500})
            page.goto(f"file://{html_path}")
            page.wait_for_timeout(2000)  # let Google Fonts load
            page.screenshot(path=png_path, full_page=False, clip={"x": 0, "y": 0, "width": 1000, "height": 1500})
            browser.close()

        # Upload to GCS
        gcs_url = _upload_to_gcs(png_path)

        # Clean up temp files
        try:
            os.remove(html_path)
            os.remove(png_path)
        except Exception:
            pass

        logger.info(f"Claude Design pin uploaded: {gcs_url}")
        return gcs_url

    except Exception as e:
        logger.error(f"Claude Design pin failed: {e}", exc_info=True)
        return None


def generate_dalle3_pin(
    product_image_url: str,
    product_name: str,
    niche: str = "beauty",
    theme: str = "",
    benefits: list = None,
) -> Optional[str]:
    """
    Generate a Pinterest pin using DALL-E 3.
    DALL-E 3 can create lifestyle backgrounds, glow effects, and photorealistic
    product scenes — much closer to the Pin Perfect Pro / gpt-image-2 style.
    """
    import requests as req
    from openai import OpenAI
    from config import Config

    if not Config.OPENAI_API_KEY:
        logger.warning("DALL-E 3: no OPENAI_API_KEY")
        return None

    client = OpenAI(api_key=Config.OPENAI_API_KEY)

    b = benefits or ["Premium Quality", "Fast Results", "Easy to Use"]
    b1 = b[0] if len(b) > 0 else "Premium Quality"
    b2 = b[1] if len(b) > 1 else "Fast Results"
    b3 = b[2] if len(b) > 2 else "Easy to Use"

    headline = theme if theme else product_name

    NICHE_STYLE = {
        "beauty": {
            "bg": "soft pink or rose gradient background with sparkle/glitter effects and glowing skin bokeh in the background",
            "accent": "hot pink (#d4547a)",
            "cta": "Save This Routine",
        },
        "home_decor": {
            "bg": "warm cozy lifestyle living room scene with soft ambient lighting, cream and beige tones",
            "accent": "warm gold (#b07d3a)",
            "cta": "Save This Idea",
        },
        "fitness": {
            "bg": "fresh energetic background — either clean white with citrus/ingredient props or dark dramatic with glow effects",
            "accent": "teal or bold gold (#2a9d8f or #e8a020)",
            "cta": "Save This",
        },
    }
    style = NICHE_STYLE.get(niche, NICHE_STYLE["beauty"])

    prompt = f"""Create a Pinterest pin image (portrait, 2:3 ratio) for: {product_name}

EXACT LAYOUT (top to bottom):
1. TOP SECTION (~30%): {style["bg"]}. Large bold headline text: "{headline}" — biggest text on the pin, font weight 900, mixed case or ALL CAPS. One key word in {style["accent"]} accent color.
2. MIDDLE SECTION (~45%): The product "{product_name}" as the hero — large, centered, photorealistic, true to the actual product packaging and colors. Background behind product blends with the overall scene.
3. BOTTOM SECTION (~25%): Light panel. Three benefit icons in a row: {b1} · {b2} · {b3}. Below that a full-width rounded button with bookmark icon and text "🔖 {style["cta"]}" in {style["accent"]} color.

STYLE: Pinterest-native, scroll-stopping, premium editorial. Feels like a magazine ad. Warm, aspirational, not clinical. No watermarks. No borders. Mobile-optimized."""

    try:
        logger.info(f"Calling DALL-E 3 for product='{product_name}', niche='{niche}'")
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1792",  # closest to 2:3 portrait
            quality="hd",
            response_format="b64_json",
        )

        import base64
        img_bytes = base64.b64decode(response.data[0].b64_json)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        fname = f"pin_dalle3_{uuid.uuid4().hex}.png"
        path = os.path.join(OUTPUT_DIR, fname)
        with open(path, "wb") as f:
            f.write(img_bytes)

        gcs_url = _upload_to_gcs(path)
        try:
            os.remove(path)
        except Exception:
            pass

        logger.info(f"DALL-E 3 pin uploaded: {gcs_url}")
        return gcs_url

    except Exception as e:
        logger.error(f"DALL-E 3 generation failed: {e}", exc_info=True)
        return None


def generate_editorial_pin(
    product_image_urls: list,
    theme: str,
    subtitle: str = "on Amazon",
    niche: str = "beauty",
    benefits: list = None,
    product_name: str = "",
    amazon_url: str = "",
    price: str = "",
    image_model: str = "dalle3",
) -> Optional[str]:
    """
    Generate a Pinterest editorial pin.

    image_model options:
      "dalle3"        — DALL-E 3 (default, best lifestyle/glow aesthetic)
      "claude_design" — Claude HTML → Playwright PNG
      "gpt_image_1"   — gpt-image-1 edit (requires org verification)

    Falls back to claude_design then PIL if primary fails.
    """
    from config import Config

    # 1. DALL-E 3 (default)
    if image_model == "dalle3" and Config.OPENAI_API_KEY:
        result = generate_dalle3_pin(
            product_image_url=product_image_urls[0] if product_image_urls else "",
            product_name=product_name,
            niche=niche,
            theme=theme,
            benefits=benefits or [],
        )
        if result:
            return result
        logger.warning("DALL-E 3 failed — falling back to Claude Design")

    # 2. Claude Design
    if image_model in ("claude_design", "dalle3") and Config.ANTHROPIC_API_KEY and product_image_urls:
        result = generate_claude_design_pin(
            product_image_url=product_image_urls[0],
            product_name=product_name,
            amazon_url=amazon_url,
            niche=niche,
            price=price,
        )
        if result:
            return result
        logger.warning("Claude Design failed — falling back to gpt-image-1")

    # 3. gpt-image-1
    if Config.OPENAI_API_KEY:
        result = _generate_gpt_image_pin(
            product_image_urls=product_image_urls,
            theme=theme,
            subtitle=subtitle,
            niche=niche,
            benefits=benefits or [],
            product_name=product_name,
        )
        if result:
            return result
        logger.warning("gpt-image-1 failed — falling back to PIL compositor")

    # 4. PIL last resort
    return _generate_pil_editorial_pin(
        product_image_urls=product_image_urls,
        theme=theme,
        subtitle=subtitle,
        niche=niche,
        benefits=benefits or [],
    )


def _generate_gpt_image_pin(
    product_image_urls: list,
    theme: str,
    subtitle: str,
    niche: str,
    benefits: list,
    product_name: str = "",
) -> Optional[str]:
    """
    Use gpt-image-1 with the real product photo passed via images.edit
    so the model sees the actual product colors, shape, and packaging.
    """
    import base64
    import requests as req
    from openai import OpenAI
    from PIL import Image as PILImage
    from config import Config

    client = OpenAI(api_key=Config.OPENAI_API_KEY)

    b1 = benefits[0] if len(benefits) > 0 else "Clearer Skin"
    b2 = benefits[1] if len(benefits) > 1 else "Smaller Pores"
    b3 = benefits[2] if len(benefits) > 2 else "Smoother Texture"
    product_label = product_name if product_name else "a premium product"

    # ── RULE 1: Color palette pulled from product packaging ────────────────
    # The pin's colors must match the actual product. We pass the real photo
    # via images.edit so the model sees the exact packaging — but we also
    # describe it explicitly in the prompt so nothing is left to chance.

    # ── RULE 2: Background scene by niche ─────────────────────────────────
    NICHE_SCENE = {
        "beauty": (
            "Clean white or soft light beige background with subtle drop shadow. "
            "Product centered and hero — no room scene, no people. "
            "If the product is a cream or liquid, add a small texture swipe behind it showing the product's texture. "
            "If it's a hydrating product, add soft water droplets around it. "
            "Soft studio lighting, premium skincare editorial feel."
        ),
        "home_decor": (
            "Full lifestyle room scene — cozy living room or bedroom setting. "
            "Show the product styled IN a real room: sofa, throw blanket, candles, plants, wall art nearby. "
            "Warm ambient lighting from the product itself if it's a lamp. "
            "The room context is essential — people need to visualize it in their own space. "
            "Neutral warm tones: cream, beige, wood, warm whites."
        ),
        "fitness": (
            "Fresh, energetic product scene. "
            "Surround the product with fresh ingredients that match the flavor or benefit "
            "(citrus for hydration, berries/greens for supplements, clean gym surface for equipment). "
            "Or show a lifestyle usage shot: a woman using the product in a wellness/gym context. "
            "Bright, clean, energizing feel. White or very light background with fresh props."
        ),
    }
    scene = NICHE_SCENE.get(niche, NICHE_SCENE["beauty"])

    # ── RULE 3: Headline font energy by niche ─────────────────────────────
    NICHE_FONT_STYLE = {
        "beauty":    "bold clean modern sans-serif, dark charcoal/black, high contrast on light background — clinical and trustworthy",
        "home_decor":"bold serif or mixed serif/sans — feels editorial, interior-design-magazine-worthy, warm dark brown tones",
        "fitness":   "bold heavy sans-serif, can be ALL CAPS for energy products, dark on light or white on dark — powerful and energetic",
    }
    font_style = NICHE_FONT_STYLE.get(niche, NICHE_FONT_STYLE["beauty"])

    # ── RULE 5: CTA language by niche ─────────────────────────────────────
    NICHE_CTA = {
        "beauty":    "Save This Routine →",
        "home_decor":"Save This Idea →",
        "fitness":   "Save for Later →",
    }
    cta_text = NICHE_CTA.get(niche, "Shop on Amazon →")

    # ── RULE 6: Category label by niche ───────────────────────────────────
    NICHE_CATEGORY = {
        "beauty":    "Cult-Favorite Skincare",
        "home_decor":"Editor's Home Pick",
        "fitness":   "Wellness Essential",
    }
    category_label = NICHE_CATEGORY.get(niche, "Amazon Find")

    prompt = f"""Create a Pinterest-optimized vertical pin (2:3 ratio, 1000x1500 px) for: {product_label}

CRITICAL — PRODUCT ACCURACY: Recreate this product with 100% accurate colors, shape, packaging, labels, and design. Match exactly what you see in the reference photo. Do NOT change any colors or details. The product's own color palette must drive the entire pin's color scheme.

SCENE & BACKGROUND:
{scene}

TYPOGRAPHY — top to bottom, all text crisp and legible on mobile:
1. Very top center: small elegant spaced uppercase "AURA GIRL ESSENTIALS" in light gray
2. Small uppercase category label just above headline: "{category_label}"
3. Large bold headline — {font_style}: "{theme}"
4. Below product — 3 benefit lines with small icons, each on its own line:
   • {b1}
   • {b2}
   • {b3}
5. Below benefits — dot-separated summary line: "{b1} • {b2} • {b3}"
6. Bottom center — dark rounded pill button with white text: "{cta_text}"

VISUAL HIERARCHY RULES (must follow exactly):
- Headline is the LARGEST text — takes up significant space at the top
- Product is the HERO — large, centered, sharp, photorealistic
- Benefits are smaller than the headline but clearly readable
- CTA pill is the final eye stop at the very bottom
- Generous white space — never cramped or cluttered
- High contrast throughout — dark text on light, or light text on dark (never low contrast)
- The pin must feel like a premium editorial magazine page, not a basic product ad

STYLE: Scroll-stopping, Pinterest-native, mobile-optimized. No watermarks. No borders. No gradients. No generic stock-photo feel."""

    try:
        if not product_image_urls:
            logger.error("No product image URLs provided")
            return None

        # Download real product image and pass it to images.edit
        # This gives the model the exact product to reference
        img_resp = req.get(product_image_urls[0], timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        img_resp.raise_for_status()

        # Convert to RGBA PNG for images.edit
        pil_img = PILImage.open(io.BytesIO(img_resp.content)).convert("RGBA")
        png_buf = io.BytesIO()
        pil_img.save(png_buf, format="PNG")
        png_buf.seek(0)

        logger.info(f"Calling gpt-image-1 edit for theme='{theme}', niche='{niche}'")

        response = client.images.edit(
            model="gpt-image-1",
            image=("product.png", png_buf, "image/png"),
            prompt=prompt,
            n=1,
            size="1024x1536",
        )

        image_data = response.data[0]
        if hasattr(image_data, "b64_json") and image_data.b64_json:
            img_bytes = base64.b64decode(image_data.b64_json)
        elif hasattr(image_data, "url") and image_data.url:
            dl = req.get(image_data.url, timeout=30)
            dl.raise_for_status()
            img_bytes = dl.content
        else:
            logger.error("gpt-image-1 returned no image data")
            return None

        # Save + upload to GCS
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        fname = f"pin_gpt2_{uuid.uuid4().hex}.png"
        path = os.path.join(OUTPUT_DIR, fname)
        with open(path, "wb") as f:
            f.write(img_bytes)

        gcs_url = _upload_to_gcs(path)
        if gcs_url:
            logger.info(f"gpt-image-2 pin uploaded to GCS: {gcs_url}")
            return gcs_url
        return path

    except Exception as e:
        logger.error(f"gpt-image-2 generation failed: {e}", exc_info=True)
        return None


def _generate_pil_editorial_pin(
    product_image_urls: list,
    theme: str,
    subtitle: str,
    niche: str,
    benefits: list,
) -> Optional[str]:
    """PIL fallback compositor — used when OpenAI API is unavailable."""
    import requests as req
    from PIL import Image as PILImage, ImageDraw, ImageFont

    # ── Niche accent colour (used for CTA pill + thin rules only) ─────────
    NICHE_ACCENT = {
        "beauty":    ( 95, 150, 190),   # soft blue (like the Medicube CTA)
        "home_decor":(130, 105,  60),   # warm gold
        "fitness":   ( 70, 130,  90),   # sage green
    }
    accent    = NICHE_ACCENT.get(niche, NICHE_ACCENT["beauty"])
    BG        = (255, 255, 255)         # pure white always
    TEXT_DARK = ( 22,  22,  30)         # near-black for headline
    TEXT_MID  = ( 80,  80,  90)         # mid-grey for bullets/subtitle

    W, H = 1000, 1500

    # ── Default benefit bullets by niche if not provided ──────────────────
    if not benefits:
        _defaults = {
            "beauty":    ["Smoother Skin", "Fewer Breakouts", "Instant Glow"],
            "home_decor":["Elevates Any Room", "Budget-Friendly", "Ships Fast"],
            "fitness":   ["Boosts Results", "Clean Ingredients", "Worth It"],
        }
        benefits = _defaults.get(niche, _defaults["beauty"])

    # ── Layout zones (1000 × 1500 canvas) ────────────────────────────────
    HOOK_TOP     = 0       # hook headline starts here
    HOOK_BOT     = 270     # hook headline ends (270px)
    PRODUCT_TOP  = 270     # product hero starts
    PRODUCT_BOT  = 1165    # product hero ends (895px — ~60% of canvas)
    BULLETS_TOP  = 1165    # benefit bullets
    BULLETS_BOT  = 1360
    CTA_TOP      = 1368
    CTA_BOT      = 1460

    # ── Download real product images ──────────────────────────────────────
    product_imgs = []
    for url in product_image_urls[:4]:
        try:
            r = req.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            img = PILImage.open(io.BytesIO(r.content)).convert("RGBA")
            product_imgs.append(img)
        except Exception as e:
            logger.warning(f"Could not load product image {url}: {e}")

    if not product_imgs:
        logger.error("No product images loaded for editorial pin — cannot generate")
        return None

    # ── Build white canvas ────────────────────────────────────────────────
    canvas = PILImage.new("RGB", (W, H), BG)
    draw   = ImageDraw.Draw(canvas)

    # ── Load fonts ────────────────────────────────────────────────────────
    BOLD_FONTS = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    REG_FONTS = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]

    def _load_font(paths, size):
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    font_hook    = _load_font(BOLD_FONTS, 100)   # big hook headline
    font_brand   = _load_font(REG_FONTS,  19)    # small brand label
    font_bullets = _load_font(BOLD_FONTS, 34)    # benefit bullets
    font_cta     = _load_font(BOLD_FONTS, 30)    # CTA pill

    # ═══════════════════════════════════════════════════════════════════════
    # ZONE 1: HOOK HEADLINE (top)
    # ═══════════════════════════════════════════════════════════════════════
    # Thin top rule
    draw.rectangle([50, 16, W - 50, 19], fill=(220, 220, 220))

    # Brand label — tiny, uppercase, centered
    _draw_centered_text(draw, "AURA GIRL ESSENTIALS", font_brand, W, 28, (170, 170, 175), letter_gap=3)

    # Hook text — large, bold, dark, centered, up to 2 lines
    hook_display = theme.upper()
    hook_lines   = _wrap_text(hook_display, font_hook, W - 80)
    hook_y = 72
    for line in hook_lines[:2]:
        _draw_centered_text(draw, line, font_hook, W, hook_y, TEXT_DARK)
        try:
            bbox = font_hook.getbbox(line)
            hook_y += (bbox[3] - bbox[1]) + 6
        except Exception:
            hook_y += 106

    # ═══════════════════════════════════════════════════════════════════════
    # ZONE 2: PRODUCT HERO (middle — the biggest zone)
    # ═══════════════════════════════════════════════════════════════════════
    PROD_ZONE_H = PRODUCT_BOT - PRODUCT_TOP   # ~895px
    PROD_ZONE_W = W

    n = len(product_imgs)

    if n == 1:
        img = product_imgs[0].copy()
        # Fill the zone — very tight padding so product is massive
        img.thumbnail((PROD_ZONE_W - 20, PROD_ZONE_H - 10), PILImage.LANCZOS)
        x = (W - img.width) // 2
        y = PRODUCT_TOP + (PROD_ZONE_H - img.height) // 2
        _paste_with_alpha(canvas, img, x, y)

    elif n == 2:
        # Side by side — each takes half, no gap
        cell_w = W // 2
        cell_h = PROD_ZONE_H
        for i, img in enumerate(product_imgs):
            img = img.copy()
            img.thumbnail((cell_w - 10, cell_h - 10), PILImage.LANCZOS)
            x = i * cell_w + (cell_w - img.width) // 2
            y = PRODUCT_TOP + (cell_h - img.height) // 2
            _paste_with_alpha(canvas, img, x, y)

    elif n == 3:
        # Main product top (large), two smaller bottom
        top_h = int(PROD_ZONE_H * 0.58)
        bot_h = PROD_ZONE_H - top_h - 4

        img0 = product_imgs[0].copy()
        img0.thumbnail((W - 20, top_h - 8), PILImage.LANCZOS)
        _paste_with_alpha(canvas, img0,
                          (W - img0.width) // 2,
                          PRODUCT_TOP + (top_h - img0.height) // 2)

        # 1px separator
        draw.rectangle([40, PRODUCT_TOP + top_h, W - 40, PRODUCT_TOP + top_h + 1],
                       fill=(230, 230, 230))

        cell_w = W // 2
        for i, img in enumerate(product_imgs[1:3]):
            img = img.copy()
            img.thumbnail((cell_w - 12, bot_h - 8), PILImage.LANCZOS)
            x = i * cell_w + (cell_w - img.width) // 2
            y = PRODUCT_TOP + top_h + 4 + (bot_h - img.height) // 2
            _paste_with_alpha(canvas, img, x, y)

    else:
        # 2×2 grid
        cell_w = W // 2
        cell_h = PROD_ZONE_H // 2
        for i, img in enumerate(product_imgs[:4]):
            col, row = i % 2, i // 2
            img = img.copy()
            img.thumbnail((cell_w - 12, cell_h - 12), PILImage.LANCZOS)
            x = col * cell_w + (cell_w - img.width) // 2
            y = PRODUCT_TOP + row * cell_h + (cell_h - img.height) // 2
            _paste_with_alpha(canvas, img, x, y)

    # ═══════════════════════════════════════════════════════════════════════
    # ZONE 3: BENEFIT BULLETS (bottom white band)
    # ═══════════════════════════════════════════════════════════════════════
    # Fill bottom with white
    draw.rectangle([0, BULLETS_TOP - 4, W, H], fill=BG)
    # Thin separator line
    draw.rectangle([40, BULLETS_TOP - 4, W - 40, BULLETS_TOP - 2], fill=(220, 220, 225))

    # Bullet line: "✔ Smooth Skin  •  Fewer Breakouts  •  Oil Control"
    bullets_str = "  •  ".join(benefits[:3])
    check_str   = "\u2714 " + bullets_str
    _draw_centered_text(draw, check_str, font_bullets, W, BULLETS_TOP + 16, TEXT_MID)

    # ═══════════════════════════════════════════════════════════════════════
    # ZONE 4: CTA PILL
    # ═══════════════════════════════════════════════════════════════════════
    cta_label = subtitle if subtitle else "Shop This Find"
    # Make it title case and trim
    if cta_label.lower().startswith("on "):
        cta_label = "Shop on Amazon"
    try:
        cbbox = font_cta.getbbox(cta_label)
        cw = cbbox[2] - cbbox[0]
        ch = cbbox[3] - cbbox[1]
    except Exception:
        cw, ch = 200, 30
    pill_w = cw + 90
    pill_h = ch + 30
    pill_x = (W - pill_w) // 2
    pill_y = CTA_TOP
    draw.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
        radius=pill_h // 2, fill=accent,
    )
    draw.text((pill_x + 45, pill_y + 15), cta_label, font=font_cta, fill=(255, 255, 255))

    # Bottom thin rule
    draw.rectangle([50, H - 20, W - 50, H - 17], fill=(220, 220, 225))

    # ── Save + upload ─────────────────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    fname = f"editorial_{uuid.uuid4().hex}.jpg"
    path  = os.path.join(OUTPUT_DIR, fname)
    canvas.save(path, "JPEG", quality=95)

    gcs_url = _upload_to_gcs(path)
    if gcs_url:
        logger.info(f"Editorial pin uploaded to GCS: {gcs_url}")
        return gcs_url
    return path


def _draw_centered_text(draw, text, font, canvas_w, y, color, letter_gap=0):
    """Draw horizontally centered text. Optionally letter-space it."""
    if letter_gap == 0:
        try:
            bbox = font.getbbox(text)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(text) * 12
        draw.text(((canvas_w - tw) // 2, y), text, font=font, fill=color)
    else:
        total_w = sum(
            (font.getbbox(ch)[2] - font.getbbox(ch)[0]) + letter_gap
            for ch in text
        )
        x = (canvas_w - total_w) // 2
        for ch in text:
            draw.text((x, y), ch, font=font, fill=color)
            try:
                bbox = font.getbbox(ch)
                x += (bbox[2] - bbox[0]) + letter_gap
            except Exception:
                x += 12 + letter_gap


def _wrap_text(text, font, max_width):
    """Break text into lines that fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        try:
            bbox = font.getbbox(test)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(test) * 45
        if tw <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


def _paste_with_alpha(canvas: "PILImage.Image", img: "PILImage.Image", x: int, y: int):
    """Paste an RGBA image onto an RGB canvas using its alpha channel as mask."""
    if img.mode == "RGBA":
        canvas.paste(img, (x, y), mask=img.split()[3])
    else:
        canvas.paste(img.convert("RGBA"), (x, y))


def generate_pin_perfect_pro_image(
    image_prompt: str,
) -> Optional[str]:
    """
    Generate a Pinterest pin image using Ideogram v2 via fal.ai.
    Takes a Claude-generated, product-specific image prompt.
    Returns a GCS URL or None on failure.
    """
    from config import Config

    if Config.FAL_API_KEY:
        result = _generate_ideogram_image(image_prompt)
        if result:
            return result
        logger.warning("Ideogram failed — falling back to Nano Banana.")
        result = _generate_fal_image_from_prompt(image_prompt)
        if result:
            return result

    return None


def generate_collage_image(
    products: list,
    theme: str,
    subtitle: str = "on Amazon",
    brand_name: str = "",
    cta_text: str = "shop here ♥",
) -> Optional[str]:
    """
    Generate a Pinterest pin image.
    Priority: Ideogram → Nano Banana → Gemini → PIL collage.
    Returns a GCS URL or local file path, or None on failure.
    """
    from config import Config

    products = [p for p in products if p][:8]
    if not products:
        return None

    # 1. Try Ideogram first (Pin Perfect Pro quality)
    if Config.FAL_API_KEY:
        from app.ai_writer import generate_ideogram_prompt
        categories = [getattr(p, "category", "beauty") for p in products]
        dominant = max(set(categories), key=categories.count) if categories else "beauty"
        product_names = [p.name for p in products[:6] if getattr(p, "name", None)]
        image_prompt = generate_ideogram_prompt(product_names, dominant, theme, subtitle)
        if image_prompt:
            result = _generate_ideogram_image(image_prompt)
            if result:
                return result
        logger.warning("Ideogram failed — falling back to Nano Banana.")

    # 2. Try fal.ai Nano Banana
    if Config.FAL_API_KEY:
        result = _generate_fal_image(products, theme, subtitle, brand_name, cta_text)
        if result:
            return result
        logger.warning("fal.ai Nano Banana failed — falling back to Gemini.")

    # 3. Try Gemini
    if Config.GEMINI_API_KEY:
        result = _generate_gemini_collage(products, theme, subtitle, brand_name, cta_text)
        if result:
            return result
        logger.warning("Gemini image generation failed — falling back to PIL collage.")

    # 4. Last resort: PIL collage
    return _generate_pil_collage(products, theme, subtitle, brand_name, cta_text)


def _generate_fal_image(
    products: list,
    theme: str,
    subtitle: str,
    brand_name: str,
    cta_text: str,
) -> Optional[str]:
    """
    Generate a Pinterest pin using fal.ai Nano Banana 2.
    Produces a photorealistic product collage on a clean background with
    title text and CTA baked directly into the image — no PIL overlay needed.
    """
    import requests as req
    from config import Config

    # Determine dominant niche
    categories = [getattr(p, "category", "beauty") for p in products]
    dominant = max(set(categories), key=categories.count) if categories else "beauty"

    # Build product description from approved product names
    product_names = [p.name for p in products[:8] if getattr(p, "name", None)]
    prompt = _build_fal_prompt(product_names, dominant, theme, subtitle, cta_text)

    logger.info(f"Generating fal.ai Nano Banana pin (niche: {dominant}, theme: {theme})")

    try:
        resp = req.post(
            "https://fal.run/fal-ai/nano-banana-2",
            headers={
                "Authorization": f"Key {Config.FAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "aspect_ratio": "2:3",
                "resolution": "1K",
                "num_images": 1,
                "output_format": "png",
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        image_url = data["images"][0]["url"]
        logger.info(f"fal.ai image generated: {image_url}")

        # Download the image
        img_resp = req.get(image_url, timeout=30)
        img_resp.raise_for_status()

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        fname = f"pin_{uuid.uuid4().hex}.png"
        path = os.path.join(OUTPUT_DIR, fname)
        with open(path, "wb") as f:
            f.write(img_resp.content)

        gcs_url = _upload_to_gcs(path)
        if gcs_url:
            logger.info(f"Uploaded to GCS: {gcs_url}")
            return gcs_url
        return path

    except Exception as e:
        logger.error(f"fal.ai image generation failed: {e}", exc_info=True)
        return None


def _generate_ideogram_image(image_prompt: str) -> Optional[str]:
    """
    Generate a Pinterest pin using Ideogram v2 via fal.ai.
    Ideogram excels at text-in-image and clean editorial Pinterest aesthetics.
    """
    import requests as req
    from config import Config

    logger.info(f"Generating Ideogram image (prompt length: {len(image_prompt)})")

    try:
        resp = req.post(
            "https://fal.run/fal-ai/ideogram/v2",
            headers={
                "Authorization": f"Key {Config.FAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": image_prompt,
                "aspect_ratio": "ASPECT_2_3",
                "model": "V_2",
                "magic_prompt_option": "OFF",
                "style_type": "REALISTIC",
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        image_url = data["images"][0]["url"]
        logger.info(f"Ideogram image generated: {image_url}")

        img_resp = req.get(image_url, timeout=30)
        img_resp.raise_for_status()

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        fname = f"pin_ideogram_{uuid.uuid4().hex}.png"
        path = os.path.join(OUTPUT_DIR, fname)
        with open(path, "wb") as f:
            f.write(img_resp.content)

        gcs_url = _upload_to_gcs(path)
        if gcs_url:
            logger.info(f"Ideogram image uploaded to GCS: {gcs_url}")
            return gcs_url
        return path

    except Exception as e:
        logger.error(f"Ideogram image generation failed: {e}", exc_info=True)
        return None


def generate_ideogram_remix_image(
    image_urls: list,
    prompt: str,
    niche: str = "beauty",
) -> Optional[str]:
    """
    Generate a Pinterest pin using Ideogram v2 Remix.
    Takes real product images (GCS URLs), creates a reference collage,
    then remixes it with the editorial Pinterest prompt so Ideogram
    sees the actual products instead of imagining them.
    """
    import io, requests as req
    from PIL import Image as PILImage
    from config import Config

    if not image_urls or not Config.FAL_API_KEY:
        return None

    logger.info(f"Building product reference collage from {len(image_urls)} images")

    # ── Download all product images ─────────────────────────────────────────
    pil_images = []
    for url in image_urls[:4]:
        try:
            resp = req.get(url, timeout=15)
            resp.raise_for_status()
            img = PILImage.open(io.BytesIO(resp.content)).convert("RGBA")
            pil_images.append(img)
        except Exception as e:
            logger.warning(f"Could not load product image {url}: {e}")

    if not pil_images:
        logger.error("No product images loaded — falling back to text-to-image")
        return _generate_ideogram_image(prompt)

    # ── Build a simple 2:3 reference collage on white ──────────────────────
    # Grid: 1 product → centered; 2 → side by side; 3-4 → 2x2 grid
    CELL = 500  # each product cell (px)
    cols = 2 if len(pil_images) > 1 else 1
    rows = math.ceil(len(pil_images) / cols)
    canvas_w = cols * CELL
    canvas_h = max(rows * CELL, int(canvas_w * 1.5))  # keep ≥2:3

    canvas = PILImage.new("RGB", (canvas_w, canvas_h), (255, 255, 255))

    for idx, img in enumerate(pil_images):
        col = idx % cols
        row = idx // cols
        # Fit image in cell with padding
        pad = 20
        cell_inner = CELL - pad * 2
        img.thumbnail((cell_inner, cell_inner), PILImage.LANCZOS)
        # Center in cell
        x = col * CELL + pad + (cell_inner - img.width) // 2
        y = row * CELL + pad + (cell_inner - img.height) // 2
        if img.mode == "RGBA":
            canvas.paste(img, (x, y), mask=img.split()[3])
        else:
            canvas.paste(img, (x, y))

    # ── Upload collage to GCS ───────────────────────────────────────────────
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=95)
    buf.seek(0)

    from google.cloud import storage as gcs_lib
    gcs_client = gcs_lib.Client()
    gcs_bucket = gcs_client.bucket(GCS_BUCKET)
    collage_name = f"product-collages/collage_{uuid.uuid4().hex}.jpg"
    collage_blob = gcs_bucket.blob(collage_name)
    collage_blob.upload_from_file(buf, content_type="image/jpeg")
    collage_gcs_url = f"{GCS_BASE_URL}/{collage_name}"
    logger.info(f"Product collage uploaded: {collage_gcs_url}")

    # ── Call Ideogram Remix ─────────────────────────────────────────────────
    logger.info("Calling Ideogram v2 Remix with real product reference")
    try:
        resp = req.post(
            "https://fal.run/fal-ai/ideogram/v2/remix",
            headers={
                "Authorization": f"Key {Config.FAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "image_url": collage_gcs_url,
                "strength": 0.70,        # 0=ignore reference, 1=copy exactly; 0.70 keeps product look
                "aspect_ratio": "ASPECT_2_3",
                "model": "V_2",
                "magic_prompt_option": "OFF",
                "style_type": "REALISTIC",
            },
            timeout=150,
        )
        resp.raise_for_status()
        data = resp.json()

        image_url = data["images"][0]["url"]
        logger.info(f"Ideogram Remix image generated: {image_url}")

        img_resp = req.get(image_url, timeout=30)
        img_resp.raise_for_status()

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        fname = f"pin_remix_{uuid.uuid4().hex}.jpg"
        path = os.path.join(OUTPUT_DIR, fname)
        with open(path, "wb") as f:
            f.write(img_resp.content)

        gcs_url = _upload_to_gcs(path)
        if gcs_url:
            logger.info(f"Remix pin uploaded to GCS: {gcs_url}")
            return gcs_url
        return path

    except Exception as e:
        logger.error(f"Ideogram Remix failed: {e}", exc_info=True)
        # Fallback to text-to-image with the same prompt
        return _generate_ideogram_image(prompt)


def _generate_fal_image_from_prompt(image_prompt: str) -> Optional[str]:
    """Nano Banana 2 fallback that takes a raw prompt string."""
    import requests as req
    from config import Config

    try:
        resp = req.post(
            "https://fal.run/fal-ai/nano-banana-2",
            headers={
                "Authorization": f"Key {Config.FAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": image_prompt,
                "aspect_ratio": "2:3",
                "resolution": "1K",
                "num_images": 1,
                "output_format": "png",
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        image_url = data["images"][0]["url"]

        img_resp = req.get(image_url, timeout=30)
        img_resp.raise_for_status()

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        fname = f"pin_nano_{uuid.uuid4().hex}.png"
        path = os.path.join(OUTPUT_DIR, fname)
        with open(path, "wb") as f:
            f.write(img_resp.content)

        gcs_url = _upload_to_gcs(path)
        return gcs_url or path
    except Exception as e:
        logger.error(f"Nano Banana fallback failed: {e}")
        return None


def _build_fal_prompt(
    product_names: list,
    niche: str,
    theme: str,
    subtitle: str,
    cta_text: str,
) -> str:
    """
    Build a Nano Banana 2 prompt for a Pinterest product collage pin.
    Describes the products, layout, and text overlays in detail.
    """
    niche_configs = {
        "home_decor": {
            "bg": "clean white background",
            "palette": "black and gold — every product must be black, gold, brass, or clear acrylic only. No other colors.",
            "style": "glam home aesthetic, luxurious and editorial",
            "products_default": "a gold sputnik chandelier, a black velvet tufted ottoman with clear acrylic legs, a gold bar cart with glass shelves, a black rattan sideboard cabinet with gold handles, two black curved velvet accent chairs with gold legs, a gold arc floor lamp",
            "cohesion_note": "All products share a strict black and gold color palette. They look like they belong in the same room.",
        },
        "beauty": {
            "bg": "soft blush pink background",
            "palette": "pink, rose, nude, and white tones — every product must be in blush, pink, white, nude, or rose gold only.",
            "style": "feminine luxury beauty aesthetic, soft and editorial",
            "products_default": "a glossy pink lip gloss set, a pink-labeled skincare serum bottle, a pastel pink press-on nail kit fanned open, a white lash serum with pink cap, a rose pink blush palette open showing powder, a rose gold jade facial roller",
            "cohesion_note": "All products are in the same blush pink and nude color family. They look like a curated beauty collection.",
        },
        "fitness": {
            "bg": "clean white background",
            "palette": "white, sage green, and soft mint — every product must be white, cream, sage, or mint only.",
            "style": "clean girl wellness aesthetic, minimal and aspirational",
            "products_default": "a white collagen supplement jar with clean label, a sage green insulated water bottle with straw lid, a slim white sunscreen stick, a white frosted vitamin bottle, a mint green resistance band set, a white foam roller",
            "cohesion_note": "All products are in the same white and sage green color family. They look like a curated wellness collection.",
        },
    }

    cfg = niche_configs.get(niche, niche_configs["beauty"])

    if product_names and len(product_names) >= 3:
        products_desc = ", ".join(product_names[:7])
    else:
        products_desc = cfg["products_default"]

    return (
        f"Pinterest product collage pin, vertical 2:3 portrait format, {cfg['bg']}. "
        f"IMPORTANT: strict color palette — {cfg['palette']} "
        f"All products must look cohesive and intentionally curated together, like they belong in the same collection. "
        f"Floating product images with no backgrounds, arranged naturally overlapping like a curated mood board — NOT in a grid. "
        f"Products fill the upper two-thirds of the image. Products to feature: {products_desc}. "
        f"{cfg['cohesion_note']} "
        f"Each product rendered photorealistically with soft studio lighting and natural shadows. "
        f"{cfg['style']}. Varied product sizes, organic flowing arrangement. "
        f"At the very top center, small elegant spaced uppercase label text: Aura Girl Essentials. "
        f"In the lower third of the image, large elegant mixed-case serif font title (NOT all caps): {theme}. "
        f"Below the title in small elegant italic font: {subtitle}. "
        f"At the very bottom center a dark rounded pill-shaped CTA button with white text: {cta_text}. "
        f"The text layout feels like a high-end magazine editorial. Products are the hero, text is elegant and understated. "
        f"High-end, aspirational, scroll-stopping Pinterest aesthetic. Photorealistic, not AI-looking. No watermarks."
    )


def _generate_blotato_image(
    products: list,
    theme: str,
    subtitle: str,
    brand_name: str,
    cta_text: str,
) -> Optional[str]:
    """
    Generate a Pinterest pin using Blotato's Product Scene Placement template.
    Passes real Amazon product image URLs so Blotato places the actual products
    in a beautiful styled lifestyle scene using Nano Banana AI.
    Polls until done, then downloads the result and uploads to GCS.
    """
    import time
    import requests as req
    from config import Config

    BLOTATO_TEMPLATE_ID = "f524614b-ba01-448c-967a-ce518c52a700"  # Product Scene Placement
    BLOTATO_API = "https://backend.blotato.com/v2"
    headers = {
        "blotato-api-key": Config.BLOTATO_API_KEY,
        "Content-Type": "application/json",
    }

    # Determine niche for scene styling
    categories = [getattr(p, "category", "beauty") for p in products]
    dominant = max(set(categories), key=categories.count) if categories else "beauty"

    niche_prompts = {
        "home_decor": (
            "luxury home decor Pinterest pin, warm cream and cognac aesthetic, "
            "cozy lifestyle scene on a marble surface with pampas grass and candles, "
            "warm golden lighting, aspirational interior styling"
        ),
        "beauty": (
            "beauty and skincare Pinterest pin, soft blush pink aesthetic, "
            "feminine editorial flat lay with rose petals and soft natural light, "
            "luxury glam lifestyle scene"
        ),
        "fitness": (
            "wellness and self-care Pinterest pin, clean sage green aesthetic, "
            "minimal lifestyle scene with eucalyptus and white linen, "
            "bright natural light, clean girl aesthetic"
        ),
    }
    scene_prompt = niche_prompts.get(dominant, niche_prompts["beauty"])
    full_prompt = f"{scene_prompt}. Pin title: {theme}."

    # Collect real product image URLs from approved products
    product_image_urls = [
        p.image_url for p in products[:4]
        if getattr(p, "image_url", None)
    ]

    logger.info(f"Generating Blotato pin (niche: {dominant}, theme: {theme}, products: {len(product_image_urls)})")

    try:
        # Create the visual
        payload = {
            "templateId": BLOTATO_TEMPLATE_ID,
            "inputs": {},
            "prompt": full_prompt,
            "render": True,
        }
        # If we have product images, add them as input
        if product_image_urls:
            payload["inputs"] = {
                "images": product_image_urls,
            }

        resp = req.post(f"{BLOTATO_API}/videos/from-templates", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        creation_id = resp.json()["item"]["id"]
        logger.info(f"Blotato creation started: {creation_id}")

        # Poll until done (max 3 minutes)
        for attempt in range(36):
            time.sleep(5)
            poll = req.get(f"{BLOTATO_API}/videos/creations/{creation_id}", headers=headers, timeout=15)
            poll.raise_for_status()
            item = poll.json()["item"]
            status = item["status"]
            logger.info(f"Blotato status: {status}")

            if status == "done":
                image_urls = item.get("imageUrls") or []
                if not image_urls:
                    logger.error("Blotato returned done but no imageUrls.")
                    return None

                # Download the generated image
                img_resp = req.get(image_urls[0], timeout=30)
                img_resp.raise_for_status()

                os.makedirs(OUTPUT_DIR, exist_ok=True)
                fname = f"pin_{uuid.uuid4().hex}.jpg"
                path = os.path.join(OUTPUT_DIR, fname)
                with open(path, "wb") as f:
                    f.write(img_resp.content)

                logger.info(f"Blotato image saved: {path}")

                gcs_url = _upload_to_gcs(path)
                if gcs_url:
                    logger.info(f"Uploaded to GCS: {gcs_url}")
                    return gcs_url
                return path

            if status in ("error", "failed"):
                logger.error(f"Blotato generation failed with status: {status}")
                return None

        logger.error("Blotato timed out after 3 minutes.")
        return None

    except Exception as e:
        logger.error(f"Blotato image generation failed: {e}", exc_info=True)
        return None


def _generate_gemini_collage(
    products: list,
    theme: str,
    subtitle: str,
    brand_name: str,
    cta_text: str,
) -> Optional[str]:
    """
    Generate a Pinterest pin using Gemini image-to-image.

    Passes real Amazon product photos as visual reference so Gemini knows
    the exact products to show. The prompt instructs Gemini to re-render
    each product with beautiful studio lighting (not paste it literally),
    remove backgrounds, and compose a styled lifestyle scene.
    Falls back to text-only if no product images can be downloaded.
    """
    try:
        import gc
        from google import genai
        from google.genai import types
        from config import Config

        client = genai.Client(
            vertexai=True,
            project=Config.GOOGLE_PROJECT_ID,
            location=Config.GOOGLE_LOCATION or "us-central1",
        )

        # Determine dominant niche
        categories = [getattr(p, "category", "beauty") for p in products]
        dominant = max(set(categories), key=categories.count) if categories else "beauty"

        # Download real Amazon product images — limit to 4 for memory
        product_images = _download_product_images(products[:4])

        product_names = [p.name for p in products[:6]]
        items_desc = _build_items_description(product_names, dominant)
        prompt = _build_gemini_prompt(
            theme, subtitle, dominant, items_desc, cta_text,
            has_reference_images=bool(product_images)
        )

        if product_images:
            logger.info(f"Generating Gemini image-to-image pin (niche: {dominant}, theme: {theme}, images: {len(product_images)})")
            # Reference images first, then the transformation prompt
            parts = []
            for img_bytes, mime_type in product_images:
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime_type))
            del product_images
            gc.collect()
            parts.append(types.Part.from_text(text=prompt))
            contents = parts
        else:
            logger.info(f"Generating Gemini text-to-image pin (niche: {dominant}, theme: {theme}) — no product images downloaded")
            contents = prompt

        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        # Extract generated image bytes
        image_bytes = None
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                image_bytes = part.inline_data.data
                break

        if not image_bytes:
            logger.error("Gemini returned no image data.")
            return None

        del response
        gc.collect()

        # Save locally
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        fname = f"pin_{uuid.uuid4().hex}.png"
        path  = os.path.join(OUTPUT_DIR, fname)
        with open(path, "wb") as f:
            f.write(image_bytes)
        del image_bytes
        gc.collect()

        logger.info(f"Gemini image saved: {path}")

        gcs_url = _upload_to_gcs(path)
        if gcs_url:
            logger.info(f"Uploaded to GCS: {gcs_url}")
            return gcs_url
        return path

    except Exception as e:
        logger.error(f"Gemini image generation failed: {e}", exc_info=True)
        return None


def _download_product_images(products: list) -> list[tuple]:
    """
    Download Amazon product images and return as (bytes, mime_type) tuples.
    Uses browser-like headers since Amazon blocks plain requests.
    """
    import requests as req

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.amazon.com/",
    }

    results = []
    for product in products:
        url = getattr(product, "image_url", None)
        if not url:
            continue
        try:
            resp = req.get(url, headers=headers, timeout=8)
            if resp.status_code == 200 and len(resp.content) > 1000:
                mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                results.append((resp.content, mime))
        except Exception as e:
            logger.debug(f"Failed to download product image: {e}")
            continue

    logger.info(f"Downloaded {len(results)}/{len(products)} product images for Gemini.")
    return results


def _build_items_description(product_names: list, niche: str) -> str:
    """
    Build a rich natural-language description of the products for the Gemini prompt.
    Converts product names into visual descriptions Gemini can generate beautifully.
    """
    if product_names and len(product_names) >= 2:
        # Use real product names — describe them visually for Gemini
        items = ", ".join(product_names[:5])
        return f"beautiful styled versions of: {items}"

    # Rich niche defaults when no real products exist
    defaults = {
        "beauty": (
            "a glossy pink lip gloss tube lying on its side, a sleek amber-glass skincare serum bottle, "
            "a pastel pink press-on nail kit fanned out, a white lash serum bottle standing upright, "
            "and an open blush palette showing peachy-pink powder"
        ),
        "home_decor": (
            "a tall cream ceramic vase with dried pampas grass, a round gold-framed wall mirror leaning slightly, "
            "a lit pillar candle in warm amber, a chunky knit cream throw blanket draped softly, "
            "and a minimalist black picture frame"
        ),
        "fitness": (
            "a white collagen supplement jar with a clean label, a pastel pink insulated water bottle with a straw lid, "
            "a slim white sunscreen stick, a frosted vitamin supplement bottle, "
            "and a rose gold jade roller on a white linen cloth"
        ),
    }
    return defaults.get(niche, defaults["beauty"])


def _build_gemini_prompt(
    theme: str,
    subtitle: str,
    niche: str,
    items_desc: str,
    cta_text: str,
    has_reference_images: bool = False,
) -> str:
    """
    Build a Pinterest-optimised text-to-image prompt for Gemini.
    Per-niche aesthetics:
      - Home decor: cream/cognac mood board, warm marble surfaces
      - Beauty: blush pink/white editorial flat lay, rose petals
      - Fitness: sage green/white clean editorial, wellness aesthetic
    """
    niche_configs = {
        "home_decor": {
            "bg": "warm ivory and cognac marble surface",
            "props": "soft dried pampas grass sprigs, a small cream candle flickering, a folded linen cloth",
            "lighting": "warm golden afternoon window light casting soft shadows",
            "palette": "cream, cognac, warm terracotta, dusty rose accents",
            "mood": "cozy luxury, aspirational home styling, Pinterest-worthy interior aesthetic",
        },
        "beauty": {
            "bg": "soft blush pink marble surface with a clean white backdrop",
            "props": "scattered fresh pink rose petals, a few dried flower stems, a small clear glass dish",
            "lighting": "soft natural diffused light, airy and bright",
            "palette": "blush pink, white, nude, soft gold",
            "mood": "feminine luxury, glam editorial, TikTok beauty aesthetic",
        },
        "fitness": {
            "bg": "light sage green and white clean surface",
            "props": "a sprig of eucalyptus, a small white linen towel rolled up, a clear glass water bottle",
            "lighting": "bright clean natural light, minimal shadows",
            "palette": "sage green, white, soft mint, warm cream",
            "mood": "clean girl aesthetic, wellness lifestyle, aspirational self-care",
        },
    }

    cfg = niche_configs.get(niche, niche_configs["beauty"])

    if has_reference_images:
        intro = (
            f"I'm giving you reference photos of real products. "
            f"Use these photos to understand WHAT each product looks like — its shape, color, design, and style. "
            f"Then RE-RENDER each product beautifully: remove its plain white background, add soft realistic studio lighting and natural shadows, "
            f"and compose ALL of them together into a stunning Pinterest lifestyle scene. "
            f"Do NOT paste the product photos as-is. Re-draw each product as if it were photographed by a professional stylist."
        )
    else:
        intro = (
            f"Create a stunning Pinterest pin featuring {items_desc}. "
            f"Render each product with beautiful realistic detail, professional studio lighting, and soft natural shadows."
        )

    return (
        f"{intro}"
        f"\n\nFORMAT: Vertical portrait 2:3 ratio (1000x1500px). "
        f"\n\nSCENE: Arrange the products on a {cfg['bg']}. "
        f"Styling props in the scene: {cfg['props']}. "
        f"Lighting: {cfg['lighting']}. "
        f"Color palette: {cfg['palette']}. "
        f"Products overlap naturally, some slightly angled — NOT arranged in a boring grid. "
        f"Mood: {cfg['mood']}. "
        f"\n\nTEXT (render directly in the image with clean fonts): "
        f"TOP CENTER: Bold elegant serif ALL-CAPS text '{theme.upper()}'. "
        f"BELOW TITLE: Thin decorative divider line (——✦——). "
        f"BELOW DIVIDER: Small italic serif text '{subtitle}'. "
        f"BOTTOM CENTER: Dark rounded pill-shaped button with white text '{cta_text}'. "
        f"\n\nQUALITY: Photorealistic, magazine-worthy, scroll-stopping. No watermarks. No distortions."
    )


def _generate_pil_collage(
    products: list,
    theme: str,
    subtitle: str = "on Amazon",
    brand_name: str = "",
    cta_text: str = "shop here ♥",
) -> Optional[str]:
    """
    PIL fallback collage — Jackie Aina editorial style.
    Used when Gemini is not configured or fails.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.error("Pillow not installed.")
        return None

    try:
        canvas = Image.new("RGB", (W, H), CREAM)
        draw   = ImageDraw.Draw(canvas)
        fonts  = _load_fonts()

        _draw_background(canvas, draw)
        _draw_header(canvas, draw, theme, subtitle, fonts)
        _draw_product_mosaic(canvas, products)
        _draw_footer(canvas, draw, brand_name, cta_text, fonts)

        fname = f"pin_{uuid.uuid4().hex}.png"
        path  = os.path.join(OUTPUT_DIR, fname)
        canvas.save(path, "PNG", optimize=True)
        logger.info(f"PIL collage saved: {path}  ({len(products)} products)")

        gcs_url = _upload_to_gcs(path)
        if gcs_url:
            logger.info(f"Uploaded to GCS: {gcs_url}")
            return gcs_url
        return path

    except Exception as exc:
        logger.error(f"PIL collage generation failed: {exc}", exc_info=True)
        return None


# ══════════════════════════════════════════════════════════════════════════
# BACKGROUND
# ══════════════════════════════════════════════════════════════════════════

def _draw_background(canvas, draw):
    """Warm cream canvas — solid fill (clean editorial look)."""
    draw.rectangle([0, 0, W, H], fill=CREAM)


# ══════════════════════════════════════════════════════════════════════════
# HEADER  — title + ornament + subtitle
# ══════════════════════════════════════════════════════════════════════════

def _draw_header(canvas, draw, theme: str, subtitle: str, fonts: dict):
    """
    Render the top section: large bold title, decorative ornament, italic subtitle.
    Matches the Jackie Aina 'MOST LOVED / WEEKLY FAVS' style.
    """
    cx = W // 2

    # ── Giant title ──────────────────────────────────────────────────────
    title_font = fonts["title_xl"]
    title = theme.upper()

    # Measure and possibly shrink to fit width
    title_font = _fit_font(draw, title, INNER_W, fonts["title_xl"], fonts["title_lg"],
                            fonts["title_md"])
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]

    title_y = 28
    draw.text((cx - tw // 2, title_y), title, font=title_font, fill=DARK_BROWN)

    # ── Decorative ornament (squiggle rule) ──────────────────────────────
    ornament_y = title_y + th + 16
    _draw_ornament(draw, cx, ornament_y)

    # ── Subtitle ("on Amazon") ───────────────────────────────────────────
    sub_font = fonts["subtitle"]
    sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
    sw = sub_bbox[2] - sub_bbox[0]
    sub_y = ornament_y + 30
    draw.text((cx - sw // 2, sub_y), subtitle, font=sub_font, fill=MID_BROWN)


def _draw_ornament(draw, cx: int, y: int):
    """
    Draw the decorative ~~~⌇⌇⌇~~~ flourish seen in Jackie Aina's pins.
    Implemented as a thin horizontal rule with a small centre wave pattern.
    """
    rule_half = 180
    wave_half = 45
    ry = y + 10   # vertical centre of ornament

    # Left arm
    draw.line([(cx - rule_half, ry), (cx - wave_half - 10, ry)],
              fill=DIVIDER, width=1)
    # Right arm
    draw.line([(cx + wave_half + 10, ry), (cx + rule_half, ry)],
              fill=DIVIDER, width=1)

    # Centre wave: series of small arcs (approximated as a Bézier-like polyline)
    # We draw a simple sine-wave zigzag across a 90-px span
    pts = []
    steps = 40
    for i in range(steps + 1):
        t  = i / steps
        px = cx - wave_half + int(t * wave_half * 2)
        py = ry + int(math.sin(t * math.pi * 4) * 4)   # ±4 px amplitude, 4 periods
        pts.append((px, py))

    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=DIVIDER, width=1)

    # Small diamond at the very centre
    ds = 4
    draw.polygon(
        [(cx, ry - ds), (cx + ds, ry), (cx, ry + ds), (cx - ds, ry)],
        fill=DARK_BROWN,
    )


# ══════════════════════════════════════════════════════════════════════════
# PRODUCT MOSAIC  — floating images, no card boxes
# ══════════════════════════════════════════════════════════════════════════

def _draw_product_mosaic(canvas, products: list):
    """
    Arrange product images in a clean 2-column floating layout.
    White/near-white backgrounds are removed so products appear to float
    on the cream canvas — exactly like Jackie Aina's style.
    """
    from PIL import Image

    n       = len(products)
    n_rows  = math.ceil(n / 2)
    pad     = MARGIN
    gap_x   = 20
    gap_y   = 18
    cell_w  = (W - 2 * pad - gap_x) // 2
    cell_h  = (PRODUCT_H - (n_rows - 1) * gap_y) // n_rows

    # Image area within each cell (leave a little breathing room)
    img_max_w = int(cell_w * 0.88)
    img_max_h = int(cell_h * 0.88)

    for idx, product in enumerate(products):
        row = idx // 2
        col = idx % 2

        # Centre the last item if the row is incomplete
        row_start  = row * 2
        row_count  = min(2, n - row_start)
        if row_count == 1:
            cell_cx = W // 2
        else:
            cell_cx = pad + col * (cell_w + gap_x) + cell_w // 2

        cell_cy = HEADER_H + row * (cell_h + gap_y) + cell_h // 2

        product_img = _load_product_image(product, img_max_w, img_max_h)
        if product_img is None:
            product_img = _make_placeholder(product, img_max_w, img_max_h)

        # Composite onto canvas (RGBA so transparent white areas blend in)
        px = cell_cx - product_img.width  // 2
        py = cell_cy - product_img.height // 2
        canvas.paste(product_img, (px, py), product_img)


# ══════════════════════════════════════════════════════════════════════════
# FOOTER  — CTA pill + brand signature
# ══════════════════════════════════════════════════════════════════════════

def _draw_footer(canvas, draw, brand_name: str, cta_text: str, fonts: dict):
    """
    Draw the dark CTA pill button and the elegant brand-name signature.
    """
    cx   = W // 2
    fy   = HEADER_H + PRODUCT_H   # top of footer band

    # ── CTA pill ─────────────────────────────────────────────────────────
    pill_text  = f"  \U0001F517 {cta_text}  "   # 🔗 link emoji
    pill_font  = fonts["pill"]
    pill_bbox  = draw.textbbox((0, 0), pill_text, font=pill_font)
    pw         = pill_bbox[2] - pill_bbox[0] + 40
    ph         = 48
    pill_y     = fy + 16
    pill_x     = cx - pw // 2

    draw.rounded_rectangle(
        [pill_x, pill_y, pill_x + pw, pill_y + ph],
        radius=ph // 2,
        fill=PILL_BG,
    )
    pt_bbox = draw.textbbox((0, 0), pill_text, font=pill_font)
    ptw = pt_bbox[2] - pt_bbox[0]
    pth = pt_bbox[3] - pt_bbox[1]
    draw.text(
        (cx - ptw // 2, pill_y + (ph - pth) // 2),
        pill_text, font=pill_font, fill=PILL_TEXT,
    )

    # ── Brand signature ───────────────────────────────────────────────────
    if brand_name:
        sig_font = fonts["signature"]
        sig_bbox = draw.textbbox((0, 0), brand_name, font=sig_font)
        sw       = sig_bbox[2] - sig_bbox[0]
        sig_y    = pill_y + ph + 20
        draw.text((cx - sw // 2, sig_y), brand_name, font=sig_font, fill=DARK_BROWN)


# ══════════════════════════════════════════════════════════════════════════
# IMAGE LOADING + WHITE BACKGROUND REMOVAL
# ══════════════════════════════════════════════════════════════════════════

def _load_product_image(product, max_w: int, max_h: int):
    """Download product image, remove white background, fit to slot."""
    if not product.image_url:
        return None

    try:
        import requests
        from PIL import Image

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.amazon.com/",
        }
        resp = requests.get(product.image_url, timeout=8, stream=True, headers=headers)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img = _remove_white_background(img)
        img = _fit_contain(img, max_w, max_h)
        return img

    except Exception as exc:
        logger.debug(f"Image fetch failed for '{product.name}': {exc}")
        return None


def _remove_white_background(img, threshold: int = 235):
    """
    Replace near-white pixels with transparency so products float on cream.
    Works best for typical Amazon product images on white backgrounds.
    """
    from PIL import Image

    data    = img.getdata()
    new_data = []
    for r, g, b, a in data:
        if r >= threshold and g >= threshold and b >= threshold:
            new_data.append((r, g, b, 0))    # transparent
        else:
            new_data.append((r, g, b, a))
    img.putdata(new_data)
    return img


def _fit_contain(img, max_w: int, max_h: int):
    """Scale image to fit within max_w × max_h while preserving aspect ratio."""
    from PIL import Image

    ratio = min(max_w / img.width, max_h / img.height)
    new_w = max(1, int(img.width  * ratio))
    new_h = max(1, int(img.height * ratio))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _make_placeholder(product, max_w: int, max_h: int):
    """Create a simple labelled placeholder when no image is available."""
    from PIL import Image, ImageDraw

    size   = min(max_w, max_h)
    img    = Image.new("RGBA", (size, size), (0, 0, 0, 0))   # transparent
    draw   = ImageDraw.Draw(img)

    # Soft rounded square
    color  = _category_color(getattr(product, "category", "general"))
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 8, fill=(*color, 220))

    # Initial letter
    try:
        from PIL import ImageFont
        font = ImageFont.load_default()
    except Exception:
        font = None

    initial = (product.name[0] if product.name else "?").upper()
    if font:
        bbox  = draw.textbbox((0, 0), initial, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((size - tw) // 2, (size - th) // 2), initial,
                  font=font, fill=(255, 255, 255, 255))

    return img


# ══════════════════════════════════════════════════════════════════════════
# FONT LOADING
# ══════════════════════════════════════════════════════════════════════════

def _load_fonts() -> dict:
    """
    Load fonts. Priority:
      1. Bundled fonts in /app/fonts/ (installed by Dockerfile)
      2. Liberation Serif (available in Docker image via apt)
      3. PIL default
    """
    from PIL import ImageFont

    FONT_DIRS = [
        "/app/fonts",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/freefont",
        "/usr/share/fonts",
    ]

    def find(name: str):
        for d in FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
        return None

    # Bold serif candidates for the huge title
    bold_serif = (
        find("PlayfairDisplay-Black.ttf")
        or find("PlayfairDisplay-Bold.ttf")
        or find("LiberationSerif-Bold.ttf")
        or find("DejaVuSerif-Bold.ttf")
        or find("FreeSerifBold.ttf")
    )

    # Regular/italic serif for subtitle & signature
    reg_serif = (
        find("PlayfairDisplay-Italic.ttf")
        or find("LiberationSerif-Italic.ttf")
        or find("DejaVuSerif-Italic.ttf")
        or find("FreeSerifItalic.ttf")
    )

    # Sans for pill button
    sans_bold = (
        find("LiberationSans-Bold.ttf")
        or find("DejaVuSans-Bold.ttf")
        or find("FreeSansBold.ttf")
    )

    def load(path, size):
        try:
            if path:
                return ImageFont.truetype(path, size)
        except Exception:
            pass
        return ImageFont.load_default()

    return {
        "title_xl": load(bold_serif, 110),
        "title_lg": load(bold_serif, 90),
        "title_md": load(bold_serif, 72),
        "subtitle": load(reg_serif,  34),
        "pill":     load(sans_bold,  26),
        "signature": load(reg_serif, 44),
    }


def _fit_font(draw, text: str, max_w: int, *fonts):
    """Return the largest font where text fits within max_w pixels."""
    for font in fonts:
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_w:
            return font
    return fonts[-1]


# ══════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _category_color(category: str) -> tuple:
    return {
        "home_decor": (212, 195, 180),
        "kitchen":    (185, 210, 195),
        "office":     (185, 195, 215),
        "fashion":    (220, 190, 200),
        "beauty":     (230, 200, 210),
        "fitness":    (190, 215, 200),
        "travel":     (185, 205, 220),
        "garden":     (180, 210, 185),
        "pets":       (215, 200, 180),
        "tech":       (185, 195, 210),
        "art":        (215, 195, 220),
    }.get(category, (210, 205, 200))


def image_path_to_url(image_path: str, base_url: str) -> Optional[str]:
    """Convert a local image path to a Flask-served URL."""
    if not image_path:
        return None
    filename = os.path.basename(image_path)
    return f"{base_url.rstrip('/')}/images/{filename}"


# ══════════════════════════════════════════════════════════════════════════
# VERTEX AI IMAGEN  (single-product fallback, kept for future use)
# ══════════════════════════════════════════════════════════════════════════

def generate_pin_image(
    prompt: str,
    product_name: str,
    style: str = "lifestyle",
) -> Optional[str]:
    """Generate a single-product lifestyle image via Vertex AI Imagen."""
    from config import Config

    if not Config.GOOGLE_PROJECT_ID:
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    full_prompt = (
        f"Professional Pinterest lifestyle photo featuring {product_name}. "
        f"{prompt}. Natural light, warm aesthetic, no text, no watermarks."
    )

    try:
        import vertexai
        from vertexai.preview.vision_models import ImageGenerationModel

        vertexai.init(project=Config.GOOGLE_PROJECT_ID, location=Config.GOOGLE_LOCATION)
        model  = ImageGenerationModel.from_pretrained("imagegeneration@006")
        images = model.generate_images(
            prompt=full_prompt,
            number_of_images=1,
            aspect_ratio="2:3",
            add_watermark=False,
            safety_filter_level="block_some",
        )
        if not images:
            return None

        fname = f"{uuid.uuid4().hex}.png"
        path  = os.path.join(OUTPUT_DIR, fname)
        images[0].save(location=path, include_generation_parameters=False)
        return path

    except Exception as exc:
        logger.error(f"Imagen failed: {exc}", exc_info=True)
        return None
