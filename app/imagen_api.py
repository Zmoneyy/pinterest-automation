"""
Google Vertex AI Imagen integration for generating Pinterest-style images.
Uses the imagegeneration@006 model (Imagen 3).
"""
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

IMAGEN_MODEL = "imagegeneration@006"
OUTPUT_DIR = "/tmp/generated_images"

STYLE_PROMPTS = {
    "lifestyle": (
        "lifestyle photography, natural light, warm and inviting atmosphere, "
        "real home setting, candid and authentic, editorial style, "
        "shallow depth of field, soft bokeh background"
    ),
    "flat_lay": (
        "flat lay photography, top-down view, clean white or marble surface, "
        "carefully arranged props, natural daylight, professional food and product photography style, "
        "minimal and elegant composition"
    ),
    "product_hero": (
        "product photography, clean background, professional studio lighting, "
        "crisp details, commercial advertising style, premium look and feel, "
        "centered composition, high resolution"
    ),
    "aesthetic_room": (
        "interior design photography, cozy aesthetic room, natural light from window, "
        "hygge atmosphere, neutral tones with warm accents, Pinterest home decor style, "
        "realistic interior photography"
    ),
    "outdoor": (
        "outdoor lifestyle photography, golden hour lighting, natural setting, "
        "bright and airy, adventure and travel aesthetic, candid moment, "
        "real people in authentic environments"
    ),
}

NEGATIVE_PROMPT = (
    "cartoon, illustration, drawing, painting, anime, low quality, blurry, "
    "text overlay, watermark, logo, collage, distorted, unrealistic, "
    "oversaturated, generic stock photo look"
)


def _ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def generate_pin_image(
    prompt: str,
    product_name: str,
    style: str = "lifestyle",
) -> Optional[str]:
    """
    Generate a Pinterest-style image using Vertex AI Imagen.

    Args:
        prompt: Additional context about what to generate
        product_name: Name of the product (used in the prompt)
        style: One of 'lifestyle', 'flat_lay', 'product_hero', 'aesthetic_room', 'outdoor'

    Returns:
        Local file path to the generated image, or None on failure.
    """
    from config import Config

    if not Config.GOOGLE_PROJECT_ID:
        logger.warning("GOOGLE_PROJECT_ID not set. Using placeholder image.")
        return _create_placeholder_image(product_name, style)

    _ensure_output_dir()

    style_desc = STYLE_PROMPTS.get(style, STYLE_PROMPTS["lifestyle"])
    full_prompt = _build_prompt(product_name, prompt, style_desc)

    try:
        import vertexai
        from vertexai.preview.vision_models import ImageGenerationModel

        vertexai.init(
            project=Config.GOOGLE_PROJECT_ID,
            location=Config.GOOGLE_LOCATION,
        )

        model = ImageGenerationModel.from_pretrained(IMAGEN_MODEL)

        images = model.generate_images(
            prompt=full_prompt,
            number_of_images=1,
            aspect_ratio="2:3",  # Pinterest portrait format
            negative_prompt=NEGATIVE_PROMPT,
            add_watermark=False,
            safety_filter_level="block_some",
            person_generation="allow_adult",
        )

        if not images or len(images) == 0:
            logger.warning(f"Imagen returned no images for product: {product_name}")
            return _create_placeholder_image(product_name, style)

        filename = f"{uuid.uuid4().hex}.png"
        output_path = os.path.join(OUTPUT_DIR, filename)
        images[0].save(location=output_path, include_generation_parameters=False)

        logger.info(f"Image generated successfully: {output_path}")
        return output_path

    except ImportError:
        logger.error("google-cloud-aiplatform not installed or vertexai not available.")
        return _create_placeholder_image(product_name, style)
    except Exception as e:
        logger.error(f"Imagen generation failed for '{product_name}': {e}", exc_info=True)
        return _create_placeholder_image(product_name, style)


def _build_prompt(product_name: str, extra_context: str, style_desc: str) -> str:
    """Build a rich, specific prompt for Imagen."""
    base = (
        f"A beautiful Pinterest-worthy photo featuring {product_name}. "
        f"{extra_context}. "
        f"{style_desc}. "
        "High quality, photorealistic, suitable for Pinterest home and lifestyle boards. "
        "No text, no watermarks, no logos in the image."
    )
    return base


def _create_placeholder_image(product_name: str, style: str) -> Optional[str]:
    """
    Create a simple placeholder image using Pillow when Imagen is unavailable.
    Returns the path to the placeholder, or None if even Pillow fails.
    """
    _ensure_output_dir()

    try:
        from PIL import Image, ImageDraw, ImageFont

        # Pinterest portrait ratio: 1000x1500
        width, height = 1000, 1500
        img = Image.new("RGB", (width, height), color=(245, 245, 245))
        draw = ImageDraw.Draw(img)

        # Pinterest red accent bar at top
        draw.rectangle([0, 0, width, 80], fill=(230, 0, 35))

        # Center text
        text_lines = [
            "📌 Pinterest Automation",
            "",
            product_name,
            "",
            f"Style: {style}",
            "",
            "Image pending generation",
        ]

        y_start = height // 3
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
        except (IOError, OSError):
            font_large = ImageFont.load_default()
            font_small = font_large

        for i, line in enumerate(text_lines):
            if not line:
                y_start += 20
                continue
            font = font_large if i == 2 else font_small
            color = (30, 30, 30) if i != 2 else (230, 0, 35)
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (width - text_width) // 2
            draw.text((x, y_start), line, fill=color, font=font)
            y_start += 60

        filename = f"placeholder_{uuid.uuid4().hex}.png"
        output_path = os.path.join(OUTPUT_DIR, filename)
        img.save(output_path, "PNG")
        logger.info(f"Placeholder image created: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Failed to create placeholder image: {e}")
        return None


def image_path_to_url(image_path: str, base_url: str) -> Optional[str]:
    """
    Convert a local image path to a publicly accessible URL.
    In Cloud Run, images should be uploaded to GCS; here we serve via Flask route.
    """
    if not image_path:
        return None
    filename = os.path.basename(image_path)
    return f"{base_url.rstrip('/')}/images/{filename}"
