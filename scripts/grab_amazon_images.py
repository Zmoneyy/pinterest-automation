#!/usr/bin/env python3
"""
Download all product images from an Amazon product page.
Usage: python3 scripts/grab_amazon_images.py <amazon_url>

Images save to: ~/Downloads/amazon-images/<product-name>/
"""
import sys, re, json, os, urllib.parse
import requests
from pathlib import Path

def get_product_images(url: str) -> tuple[str, list[str]]:
    """Fetch Amazon page and extract all full-resolution image URLs."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    resp = requests.get(url, headers=headers, timeout=15)
    html = resp.text

    # ── Product name ──────────────────────────────────────────────
    name = ""
    for pattern in [
        r'<span id="productTitle"[^>]*>\s*(.+?)\s*</span>',
        r'"productTitle"\s*:\s*"([^"]+)"',
        r'<title>([^<]+)</title>',
    ]:
        m = re.search(pattern, html, re.DOTALL)
        if m:
            name = m.group(1).strip()
            if name.lower() not in ("amazon.com", ""):
                break

    # Clean name for use as folder name
    folder_name = re.sub(r'[^\w\s\-]', '', name)[:60].strip() or "amazon-product"

    # ── Image URLs ────────────────────────────────────────────────
    image_urls = []

    # Method 1: colorImages JS variable (most reliable — contains all gallery images)
    m = re.search(r"'colorImages'\s*:\s*\{\s*'initial'\s*:\s*(\[.+?\])\s*\}", html, re.DOTALL)
    if not m:
        m = re.search(r'"colorImages"\s*:\s*\{\s*"initial"\s*:\s*(\[.+?\])\s*\}', html, re.DOTALL)
    if m:
        try:
            images = json.loads(m.group(1))
            for img in images:
                # Prefer hiRes → large → main (in that order)
                for key in ("hiRes", "large", "main"):
                    src = img.get(key)
                    if src and src.startswith("http"):
                        image_urls.append(src)
                        break
        except Exception:
            pass

    # Method 2: data-a-dynamic-image attribute on the main image
    if not image_urls:
        m = re.search(r'data-a-dynamic-image="([^"]+)"', html)
        if m:
            try:
                data = json.loads(m.group(1).replace("&quot;", '"'))
                # Sort by resolution (largest first)
                sorted_urls = sorted(data.keys(), key=lambda u: data[u][0] * data[u][1], reverse=True)
                image_urls.extend(sorted_urls)
            except Exception:
                pass

    # Method 3: regex scan for Amazon CDN image URLs in the page
    if not image_urls:
        found = re.findall(r'https://m\.media-amazon\.com/images/I/[A-Za-z0-9%+\-_.]+\.jpg', html)
        seen = set()
        for u in found:
            if u not in seen:
                seen.add(u)
                image_urls.append(u)

    # Remove size constraints from URLs to get full resolution
    # e.g. ._AC_SL1500_ or ._AC_UL320_ → just the base image
    clean_urls = []
    seen = set()
    for u in image_urls:
        # Strip Amazon image size/crop suffixes
        clean = re.sub(r'\._[A-Z_0-9,]+_\.', '.', u)
        if clean not in seen:
            seen.add(clean)
            clean_urls.append(clean)

    return folder_name, clean_urls


def download_images(product_name: str, urls: list[str]) -> Path:
    """Download all images flat into ~/Downloads/amazon-images/ with product prefix."""
    save_dir = Path.home() / "Downloads" / "amazon-images"
    save_dir.mkdir(parents=True, exist_ok=True)

    # Short prefix so you can tell images apart when multiple products are in the folder
    prefix = re.sub(r'\s+', '_', product_name)[:30].strip('_')

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.amazon.com/",
    }

    downloaded = 0
    for i, url in enumerate(urls, 1):
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 2000:
                ext = "jpg" if "jpg" in url.lower() else "png"
                filename = save_dir / f"image_{i:02d}.{ext}"
                filename.write_bytes(resp.content)
                size_kb = len(resp.content) // 1024
                print(f"  ✅ image_{i:02d}.{ext}  ({size_kb} KB)")
                downloaded += 1
            else:
                print(f"  ⚠️  image {i} skipped (too small or error {resp.status_code})")
        except Exception as e:
            print(f"  ❌ image {i} failed: {e}")

    return save_dir, downloaded


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/grab_amazon_images.py <amazon_url>")
        print('Example: python3 scripts/grab_amazon_images.py "https://www.amazon.com/dp/B0XXXXXX"')
        sys.exit(1)

    url = sys.argv[1].strip()
    if "amazon.com" not in url:
        print("❌ That doesn't look like an Amazon URL.")
        sys.exit(1)

    print(f"\n🔍 Fetching product page…")
    try:
        folder_name, image_urls = get_product_images(url)
    except Exception as e:
        print(f"❌ Failed to fetch page: {e}")
        sys.exit(1)

    print(f"📦 Product: {folder_name}")
    print(f"🖼️  Found {len(image_urls)} image(s)\n")

    if not image_urls:
        print("❌ No images found. Amazon may have blocked the request — try again.")
        sys.exit(1)

    save_dir, downloaded = download_images(folder_name, image_urls)

    print(f"\n{'─'*50}")
    print(f"✅ {downloaded}/{len(image_urls)} images saved to:")
    print(f"   {save_dir}")

    # Open the folder in Finder automatically
    os.system(f'open "{save_dir}"')
    print("\n📂 Folder opened in Finder — drag images into ChatGPT!")


if __name__ == "__main__":
    main()
