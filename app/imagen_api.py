"""
Pinterest collage image generator — Jackie Aina editorial style.

Produces a 1000×1500 pin with:
  • Warm cream background
  • Giant bold serif title (ALL CAPS) with decorative ornament
  • Italic subtitle ("on Amazon")
  • Product images floating on the canvas (no card boxes, white bg removed)
  • Dark rounded CTA pill button
  • Elegant script-style brand signature at the bottom
"""
import io
import logging
import math
import os
import random
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

OUTPUT_DIR = "/tmp/generated_images"

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

def generate_collage_image(
    products: list,
    theme: str,
    subtitle: str = "on Amazon",
    brand_name: str = "",
    cta_text: str = "shop here ♥",
) -> Optional[str]:
    """
    Build a Jackie Aina style Pinterest mood-board collage.

    Returns a local file path to the generated PNG, or None on failure.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.error("Pillow not installed.")
        return None

    products = [p for p in products if p][:8]
    if not products:
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
        logger.info(f"Collage saved: {path}  ({len(products)} products)")
        return path

    except Exception as exc:
        logger.error(f"Collage generation failed: {exc}", exc_info=True)
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
