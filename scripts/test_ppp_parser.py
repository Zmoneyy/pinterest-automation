#!/usr/bin/env python3
"""
Regression test for the PPP (Pin Perfect Pro) parser in templates/bulk_upload.html.

The parser has broken four times, each from a new paste format:
  1. Old markdown format (## headings, **bold labels**)
  2. Emoji-header format with line breaks (📍Pinterest SEO Title, ⸻ separators)
  3. Same format as a run-on single line (line breaks lost when copying from ChatGPT)
  4. Full markdown with emoji INSIDE headings ("# 📌 Pinterest Pin Title (SEO
     Optimized)") and values as standalone **bold** lines under the heading

This script extracts the real parsePPPText() from the template and runs all
three formats through node, asserting on title/description/board/hashtags.

Run: python3 scripts/test_ppp_parser.py   (requires node)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "templates", "bulk_upload.html")
RUNON_FIXTURE = os.path.join(ROOT, "scripts", "fixtures", "ppp_runon_paste.txt")
MARKDOWN_FULL_FIXTURE = os.path.join(ROOT, "scripts", "fixtures", "ppp_markdown_full.txt")


def extract_parser_js() -> str:
    """Pull the parsePPPText function out of the template by brace matching."""
    src = open(TEMPLATE, encoding="utf-8").read()
    start = src.index("function parsePPPText(text)")
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise RuntimeError("Could not brace-match parsePPPText in bulk_upload.html")


# ── Fixtures ──────────────────────────────────────────────────────────────

RUNON = open(RUNON_FIXTURE, encoding="utf-8").read().strip()
MARKDOWN_FULL = open(MARKDOWN_FULL_FIXTURE, encoding="utf-8").read().strip()

MULTILINE_EMOJI = """\
📌 Pinterest Pin: Charlotte Tilbury Airbrush Flawless Setting Spray

🎨 Pin Text Overlay

✨ Headline: The Setting Spray Everyone Is Obsessed With
📝 Subheadline: 16-Hour Makeup Hold + Airbrushed Glow

⸻

📍Pinterest SEO Title

Charlotte Tilbury Airbrush Flawless Setting Spray Review | Best Long-Lasting Makeup Setting Spray

⸻

📝 Pinterest Description

Looking for a setting spray that keeps your makeup fresh all day? Save this beauty favorite and shop now!

✨ Keywords:
* Charlotte Tilbury setting spray
* best makeup setting spray

⸻

📌 Board Ideas
* Luxury Beauty Finds
* Makeup Must Haves
"""

OLD_MARKDOWN = """\
## Optimized Pin Title
Retinol Serum 2026 — Best Anti-Aging Serum for Beginners

**Pin Description:** This pin is about the best retinol serum for 2026. Smooths fine lines fast. Visit the link to shop + https://benable.com/x

**Alt Text:** Bottle of retinol serum on marble counter

**Board Name:** Beauty Finds & Skincare

### Supporting Keywords
- retinol serum
- anti aging skincare
- best serum 2026
"""

EXPECTED_TITLE = (
    "Charlotte Tilbury Airbrush Flawless Setting Spray Review | "
    "Best Long-Lasting Makeup Setting Spray"
)

HARNESS = """
const CASES = __CASES__;
let failures = 0;

function check(label, cond, got) {
  if (cond) { console.log("  ✅ " + label); }
  else      { console.log("  ❌ " + label + " — got: " + JSON.stringify(got)); failures++; }
}

for (const c of CASES) {
  console.log("\\n=== " + c.name + " ===");
  const r = parsePPPText(c.text);
  for (const [field, exp] of Object.entries(c.expect)) {
    const got = r[field] || "";
    if (exp.equals !== undefined)    check(field + " equals",   got === exp.equals, got);
    if (exp.startsWith)              check(field + " starts",   got.startsWith(exp.startsWith), got.slice(0, 60));
    for (const s of exp.includes || [])    check(field + " includes '" + s + "'", got.includes(s), got.slice(0, 80));
    for (const s of exp.notIncludes || []) check(field + " excludes '" + s + "'", !got.includes(s), got.slice(0, 80));
    if (exp.nonEmpty)                check(field + " non-empty", got.trim().length > 0, got);
  }
}

console.log(failures ? "\\n❌ " + failures + " check(s) FAILED" : "\\n✅ All PPP parser checks passed");
process.exit(failures ? 1 : 0);
"""


def main():
    cases = [
        {
            "name": "Run-on single-line paste (line breaks lost)",
            "text": RUNON,
            "expect": {
                "title": {"equals": EXPECTED_TITLE},
                "description": {
                    "startsWith": "Looking for a setting spray",
                    "includes": ["shop now!"],
                    # Image-design sections must never leak into the description
                    "notIncludes": ["Photorealistic", "Canva", "Headline", "League Spartan"],
                },
                "board_name": {"equals": "Luxury Beauty Finds"},
                "hashtags": {
                    "includes": ["#charlottetilburysettingspray", "#bestmakeupsettingspray"],
                    "notIncludes": ["#2", "#3"],
                },
            },
        },
        {
            "name": "Emoji-header format with line breaks",
            "text": MULTILINE_EMOJI,
            "expect": {
                "title": {"equals": EXPECTED_TITLE},
                "description": {"startsWith": "Looking for a setting spray"},
                "board_name": {"equals": "Luxury Beauty Finds"},
                "hashtags": {"includes": ["#charlottetilburysettingspray"]},
            },
        },
        {
            "name": "Full markdown with emoji headings + standalone bold values",
            "text": MARKDOWN_FULL,
            "expect": {
                "title": {
                    "equals": "Charlotte Tilbury Magic Cream Review: The Luxury Moisturizer for Glowing Skin"
                },
                "description": {
                    "startsWith": "Discover why Charlotte Tilbury Magic Cream",
                    "includes": ["beauty upgrade!"],
                    # Design/citation noise must never leak into the description
                    "notIncludes": ["Amazon][1]", "Canvas", "characters)", "Talking About"],
                },
                "alt_text": {"startsWith": "Gold jar of Charlotte Tilbury Magic Cream"},
                "board_name": {"equals": "Luxury Skincare Favorites"},
                "hashtags": {"includes": ["#CharlotteTilbury", "#LuxurySkincare"]},
                "amazon_url": {"equals": "https://www.amazon.com/dp/B0GFWLDP4W?tag=auragirlcreat-20"},
            },
        },
        {
            "name": "Old markdown PPP format",
            "text": OLD_MARKDOWN,
            "expect": {
                "title": {"equals": "Retinol Serum 2026 — Best Anti-Aging Serum for Beginners"},
                "description": {"startsWith": "This pin is about the best retinol serum"},
                "alt_text": {"equals": "Bottle of retinol serum on marble counter"},
                "board_name": {"equals": "Beauty Finds & Skincare"},
                "hashtags": {"includes": ["#retinolserum", "#antiagingskincare"]},
            },
        },
    ]

    js = extract_parser_js() + "\n" + HARNESS.replace("__CASES__", json.dumps(cases))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        result = subprocess.run(["node", path], capture_output=True, text=True)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        return result.returncode
    finally:
        os.unlink(path)


if __name__ == "__main__":
    sys.exit(main())
