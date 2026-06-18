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
BOLD_LABELS_FIXTURE = os.path.join(ROOT, "scripts", "fixtures", "ppp_bold_labels.txt")
RECOMMENDED_FIXTURE = os.path.join(ROOT, "scripts", "fixtures", "ppp_recommended_format.txt")
EMOJI_H1_FIXTURE = os.path.join(ROOT, "scripts", "fixtures", "ppp_emoji_h1_parenthetical.txt")
SEO_INFIX_FIXTURE = os.path.join(ROOT, "scripts", "fixtures", "ppp_seo_infix_headers.txt")


def extract_js_function(decl: str) -> str:
    """Pull a named JS function out of the template by brace matching."""
    src = open(TEMPLATE, encoding="utf-8").read()
    start = src.index(decl)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise RuntimeError(f"Could not brace-match {decl!r} in bulk_upload.html")


def extract_parser_js() -> str:
    """Both functions exercised by the suite: the parser and the description fitter."""
    return (
        extract_js_function("function fitDescriptionToLimit(desc, hashtags, limit)")
        + "\n"
        + extract_js_function("function parsePPPText(text)")
    )


# ── Fixtures ──────────────────────────────────────────────────────────────

RUNON = open(RUNON_FIXTURE, encoding="utf-8").read().strip()
MARKDOWN_FULL = open(MARKDOWN_FULL_FIXTURE, encoding="utf-8").read().strip()
BOLD_LABELS = open(BOLD_LABELS_FIXTURE, encoding="utf-8").read().strip()
RECOMMENDED = open(RECOMMENDED_FIXTURE, encoding="utf-8").read().strip()
EMOJI_H1 = open(EMOJI_H1_FIXTURE, encoding="utf-8").read().strip()
SEO_INFIX = open(SEO_INFIX_FIXTURE, encoding="utf-8").read().strip()

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
const FIT_CASES = __FIT_CASES__;
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

const FTC = "As an Amazon Associate, I may earn from qualifying purchases.";
for (const c of FIT_CASES) {
  const tags = c.hashtags || "";
  console.log("\\n=== fit: " + c.name + " (desc " + c.text.length + ", tags " + tags.length + ") ===");
  const out = fitDescriptionToLimit(c.text, tags, 500);
  console.log("  → " + out.length + " chars");
  check("fits within 500", out.length <= 500, out.length);
  check("includes FTC disclosure", out.includes(FTC), out.slice(-40));
  check("body is not empty", out.length > FTC.length + tags.length + 5, out);
  check("preserves the keyword opening", out.startsWith(c.text.slice(0, 18)), out.slice(0, 30));
  if (c.mustInclude) for (const s of c.mustInclude) check("keeps '" + s + "'", out.includes(s), out);
  if (tags) {
    check("hashtags present VERBATIM (unmodified)", out.includes(tags), out.slice(-tags.length - 5));
    check("hashtags at the very end", out.endsWith(tags), out.slice(-30));
  } else {
    check("ends with FTC disclosure", out.endsWith(FTC), out.slice(-30));
    const body = out.slice(0, out.length - FTC.length).trim();
    check("body ends cleanly (. ! ? or …)", /[.!?…]$/.test(body), body.slice(-25));
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
            # The exact format the in-app prompt now tells ChatGPT to produce.
            # This MUST always parse — it is the format we recommend to the user.
            "name": "Recommended in-app prompt format (**Label:** value)",
            "text": RECOMMENDED,
            "expect": {
                "title": {
                    "equals": "CeraVe Hydrating Facial Cleanser | Gentle Daily Face Wash for Dry Skin"
                },
                "description": {
                    "startsWith": "Wash away dirt and makeup",
                    "includes": ["grab yours."],
                    # FTC disclosure stripped (app re-adds it); overlay text not leaked
                    "notIncludes": ["Amazon Associate", "#CeraVe", "DERMATOLOGISTS"],
                },
                "alt_text": {"startsWith": "White bottle of CeraVe Hydrating Facial Cleanser"},
                "board_name": {"equals": "Skincare Routine Essentials"},
                "hashtags": {"includes": ["#CeraVe", "#FacialCleanser"]},
                "amazon_url": {"equals": "https://www.amazon.com/dp/B01N1LL62W?tag=auragirlcreat-20"},
            },
        },
        {
            "name": "Standalone bold labels + hashtag block + scheme-less Amazon URL",
            "text": BOLD_LABELS,
            "expect": {
                "title": {
                    "equals": "TATCHA The Water Cream Moisturizer | Poreless Hydration for Glowing Skin"
                },
                "description": {
                    "startsWith": "Upgrade your skincare routine with TATCHA",
                    "includes": ["grab yours."],
                    # Hashtag block and design/prompt text must not leak in
                    "notIncludes": ["#TatchaWaterCream", "Visual Concept", "AI Image", "aspect ratio"],
                },
                "alt_text": {"startsWith": "Elegant Pinterest pin featuring TATCHA"},
                "board_name": {
                    "equals": "Luxury Skincare Essentials | Face Moisturizers & Glowing Skin"
                },
                "hashtags": {"includes": ["#TatchaWaterCream", "#LuxurySkincare"]},
                # URL had no https:// and no affiliate tag — must be canonicalized
                "amazon_url": {"equals": "https://www.amazon.com/dp/B0FNQD9666?tag=auragirlcreat-20"},
            },
        },
        {
            # '# 📍Pinterest Title (SEO + Buyer Intent)' — emoji H1 headers with
            # parenthetical qualifiers, value as a standalone bold on the next
            # line, plus an explicit hashtag block that must be used verbatim.
            "name": "Emoji H1 headers with parenthetical qualifiers + verbatim hashtags",
            "text": EMOJI_H1,
            "expect": {
                "title": {
                    "equals": "ILIA Balmy Tint Lip Balm Review: The Clean Girl Lip Color You'll Wear Every Day"
                },
                "description": {
                    "startsWith": "If you're looking for the perfect everyday lip product",
                    # A/B titles, on-pin text and AI prompt must not leak in
                    "notIncludes": ["A/B", "Main Headline", "aspect ratio", "Balmy Tint Lip Balm Review"],
                },
                "alt_text": {"startsWith": "ILIA Balmy Tint hydrating lip balm"},
                "board_name": {"equals": "Clean Girl Makeup Must Haves"},
                "hashtags": {
                    # Exactly the user's tags — no synthesized "#iliabalmytintlipbalm" prepended
                    "equals": "#ILIABeauty #TintedLipBalm #CleanGirlMakeup #EverydayMakeup #LipProducts #CleanBeauty #NaturalMakeup #BeautyFavorites #HydratingLipBalm #SephoraFinds",
                },
            },
        },
        {
            # '# ✨ Pinterest SEO Description' — an "SEO" word inserted in the
            # middle of the header broke substring matching; token-subset lookup
            # fixes it. Also has a ([site][1]) citation that must be stripped.
            "name": "SEO-infix headers (Pinterest SEO Description / Title)",
            "text": SEO_INFIX,
            "expect": {
                "title": {
                    "equals": "Best Volumizing Mascara Duo for Long, Dramatic Lashes That Last All Day"
                },
                "description": {
                    "startsWith": "Searching for the best volumizing mascara?",
                    "includes": ["transformation for yourself."],
                    "notIncludes": ["globalhealingweb", "][1]", "Alt Text", "Board Name"],
                },
                "alt_text": {"startsWith": "Luxury beauty flat lay featuring two black"},
                "board_name": {"equals": "Viral Makeup Finds | Best Mascaras & Beauty Must Haves"},
                "hashtags": {
                    "equals": "#BenefitCosmetics #BADgalBANG #VolumizingMascara #DramaticLashes #MakeupFinds"
                },
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

    # Over-limit descriptions that must be smart-fitted to 500 chars on paste.
    fit_cases = [
        {
            "name": "Multi-sentence, drops middle sentences, keeps CTA",
            "text": (
                "TATCHA The Water Cream is the lightweight gel moisturizer beauty editors keep "
                "repurchasing for poreless-looking, glowing skin. Infused with Japanese botanicals, "
                "it absorbs instantly to hydrate, smooth texture, and balance oily or combination "
                "skin without any greasy residue. Wear it alone for a dewy finish or layer it under "
                "makeup as the perfect primer for all-day radiance. Loved for visibly softer, "
                "plumper, more luminous skin after just one use. This luxury Japanese skincare staple "
                "belongs in every glow-focused routine. Tap the link to grab yours before it sells out."
            ),
            "mustInclude": ["TATCHA The Water Cream", "grab yours"],
        },
        {
            "name": "One giant run-on sentence, no CTA, trims at word boundary",
            "text": (
                "The CeraVe Hydrating Facial Cleanser is a gentle non-foaming face wash formulated "
                "with three essential ceramides and hyaluronic acid that cleanses and removes makeup "
                "while helping restore the protective skin barrier and locking in lasting moisture "
                "for normal to dry skin without stripping or leaving any tight uncomfortable feeling "
                "behind which is exactly why dermatologists recommend it for sensitive skin types "
                "every single day morning and night"
            ),
        },
        {
            "name": "Already short — left intact",
            "text": "Short and sweet keyword-rich description. Tap the link to grab yours.",
            "mustInclude": ["Short and sweet", "grab yours"],
        },
        {
            # Over-limit description PLUS hashtags that must be appended verbatim.
            # Only the body may shrink — hashtags and disclosure are never touched.
            "name": "Long description + verbatim hashtags appended at end",
            "text": (
                "TATCHA The Water Cream is the lightweight gel moisturizer beauty editors keep "
                "repurchasing for poreless-looking, glowing skin. Infused with Japanese botanicals, "
                "it absorbs instantly to hydrate, smooth texture, and balance oily or combination "
                "skin without greasy residue. Wear it alone for a dewy finish or layer it under "
                "makeup as the perfect primer for all-day radiance. Loved for visibly softer, "
                "plumper skin after one use. Tap the link to grab yours."
            ),
            "hashtags": (
                "#TatchaWaterCream #FaceMoisturizer #LuxurySkincare #HydratingMoisturizer "
                "#GlowingSkin #PorelessSkin #SkincareMustHaves #BeautyFavorites"
            ),
            "mustInclude": ["TATCHA The Water Cream", "grab yours"],
        },
        {
            # Hashtags that contain a substring of the body must still be exact.
            "name": "Short description + hashtags (no trimming needed)",
            "text": "Glow-boosting vitamin C serum for brighter skin. Tap the link to grab yours.",
            "hashtags": "#VitaminCSerum #GlowSkin #BeautyFinds",
            "mustInclude": ["Glow-boosting vitamin C serum"],
        },
    ]

    js = (
        extract_parser_js()
        + "\n"
        + HARNESS.replace("__CASES__", json.dumps(cases)).replace("__FIT_CASES__", json.dumps(fit_cases))
    )
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
