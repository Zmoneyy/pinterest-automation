# Pinterest Automation — Troubleshooting Log

Each issue includes: what the symptom was, what was tried, what actually fixed it, and the root cause.

---

## 1. AI Strategy Brief showing raw `## headers` and `**bold**` text

**Symptom:** The AI Strategy Brief card shows literal `## 1. Audience Intent` and `**bold**` instead of formatted HTML.

**What was tried (wrong):**
- Added `marked.js` CDN script in `{% block head %}` and used `marked.parse()` in inline JS
- Used `data-raw` attribute with Jinja2 escaping + client-side JS to render on page load

**Why those failed:**
- CDN scripts load asynchronously — by the time the inline `{% block scripts %}` JS ran, `marked` wasn't defined yet
- Fallback was `el.textContent = raw` which showed raw markdown
- Appeared to "flash correct then revert" because marked loaded just after the fallback ran

**What actually fixed it:**
- Server-side Python markdown conversion using a Jinja2 filter (`| md`) registered in `app/__init__.py`
- Uses only Python's built-in `re` module — no CDN, no timing, no fallback
- File: `app/__init__.py` → `md_to_html()` filter, `templates/trends.html` → `{{ e.insight | md }}`

**Rule:** Never use CDN scripts for content that must render on page load. Do it server-side.

---

## 2. All JavaScript on Trends page silently broken

**Symptom:** Save Data button did nothing, "+X more" expand didn't work, "Add Category" button didn't open panel. No JS errors visible to user.

**Root cause:** A broken `async/await` block was left inside the CSV upload form's `submit` event listener (non-async arrow function with `await` inside = JS parse error). The entire `<script>` block failed to parse, killing every function on the page.

**What actually fixed it:**
- Removed the broken server-side extraction attempt from the upload submit handler
- Reduced it to just `btn.disabled = true; btn.textContent = 'Analyzing…';`
- File: `templates/trends.html` lines ~461-500

**Rule:** A single syntax error in a `<script>` block silently kills ALL JS on the page. Always check for orphaned `async/await` in non-async functions.

---

## 3. `togglePastePanel` not defined — "Add Category" button did nothing

**Symptom:** Clicking "Add Category Data" button had no effect.

**Root cause:** The function `togglePastePanel()` was called in `onclick` but never defined in the script block.

**What actually fixed it:**
- Added `function togglePastePanel() { document.getElementById('pastePanel').classList.toggle('open'); }` to the scripts block
- File: `templates/trends.html`

---

## 4. Top Products empty — products not being saved to TrendEntry

**Symptom:** Entry cards showed Search Queries correctly but Top Products section was missing entirely.

**Root causes (multiple, over multiple sessions):**

### 4a. JS was broken (see Issue #2)
When the JS parse error was present, `submitPastedKeywords()` never ran, so pin URL extraction and form submission never happened. Products were never sent to the server.

### 4b. Pin URLs being passed as products
User pasted Pinterest pin URLs into the Top Products box. Server correctly skipped lines starting with `http`, so box was empty after filtering.

### 4c. `clean_kw()` dropping long product names
The full page dump parser used `clean_kw(max_len=50)` on all lines. Product names like "2 gal bloodgood japanese maple tree - cold hardy" (>50 chars) were silently dropped.

**What fixed 4c:**
- Added `clean_product()` function (150 char max, preserves case) for product names
- Changed full page parser: lines >25 chars → `top_products_kws` via `clean_product()`, lines ≤25 chars → `full_page_context_kws` via `clean_kw()`
- File: `app/routes.py` → `trends_paste()` function

### 4d. `tp_match` regex not finding "Top Products" section
Full page dump "Top products" section header regex wasn't matching, so products fell through to the generic context parser (and got dropped by max_len=50).

**What fixed 4d:**
- Made regex more permissive: `r'top products?\b[^\n]*\n([\s\S]+?)(?=\n\s*(?:other product|...))'`
- Combined with 4c fix so even unmatched products get picked up by length heuristic

---

## 5. Pinterest Pin URL extraction — removed and restored multiple times

**Symptom:** Pin URL extraction box was present, then removed, then re-added.

**What happened:**
- Extraction works **client-side in the user's browser** using `fetch()` + JSON-LD parsing
- It does NOT work server-side (Cloud Run IPs are blocked by Pinterest)
- Was wrongly assumed to "not work" and removed — user correctly pushed back

**The working code:**
```javascript
const r = await fetch(url, { credentials: 'omit' });
const html = await r.text();
const m = html.match(/application\/ld\+json">([\s\S]*?)<\/script>/);
if (m) {
  const d = JSON.parse(m[1]);
  const name = d.headline || d?.sharedContent?.headline || d?.name || '';
  if (name && name.length > 3) extracted.push(name.trim());
}
```

**Rule:** Client-side browser fetch of `pinterest.com/pin/*` URLs WORKS. Server-side fetch of the same URLs does NOT work. Never remove this feature.

---

## 6. Infinite page refresh after product discovery

**Symptom:** After clicking "Find Products", the page refreshed itself in a loop.

**Root cause:** After discovery completed, code used `location.reload()` which kept `?discovering=1` in the URL, re-triggering the discovery banner, which triggered another reload.

**What fixed it:**
- Changed `location.reload()` to `location.href = '/products'` (clean URL, no query param)
- File: `templates/products.html`

---

## 7. "What I Understood" panel disappeared too fast

**Symptom:** After clicking Save Data, the confirmation panel briefly appeared then vanished.

**Root cause:** `setTimeout(() => location.href = '/trends', 1500)` — 1.5 seconds was too short to read the panel.

**What fixed it:**
- Removed the auto-reload entirely
- After save, button changes to "✓ Saved" (green) and a "View All Entries ↓" button appears
- User manually navigates when ready
- File: `templates/trends.html` → `submitPastedKeywords()`

---

## 8. SerpAPI key in Setup UI instead of environment

**Symptom:** User had to paste API key into the UI on every session.

**Root cause:** Key was stored in the DB via the Setup page, not in environment variables.

**What fixed it:**
- Added `SERPAPI_KEY` to `.env.yaml` (local) and `.env` (local dev)
- Removed the SerpAPI UI field from `templates/setup.html`
- File: `.env.yaml`

---

## 9. Auto-discovery draining SerpAPI quota

**Symptom:** SerpAPI free plan (250/month) was getting exhausted by automated daily discovery.

**What fixed it:**
- Removed auto-discovery from the daily scheduler job in `app/scheduler.py`
- Discovery is now manual-only (user clicks "Find Products" button)
- Comment in code: `# Auto-discovery disabled to preserve SerpAPI quota (250/month free plan)`

---

## 10. Discovery using wrong search queries (luxury brands instead of trend data)

**Symptom:** Product discovery was searching for hardcoded luxury brands instead of keywords from TrendEntry data.

**Root cause:** `_run_discovery_background()` had a hardcoded `LUXURY_SEARCHES` fallback that was always being used.

**What fixed it:**
- Rewrote to build search list from `TrendEntry.tp_list() + TrendEntry.sq_list()` first
- Hardcoded fallback only used if no TrendEntry data exists
- File: `app/routes.py` → `_run_discovery_background()`

---

## 11. Noise in Top Products (retailer names, UI text)

**Symptom:** Entries like "Plant Addicts", "; Opens a new tab", "Showing 12 pins", "preview" appearing in Top Products pills.

**Root cause:** `ui_noise` regex wasn't comprehensive enough.

**What fixed it:**
- Expanded `ui_noise` regex to catch: retailer names (Plant Addicts, Nature Hills, Fast Growing Trees, Gurney's, Burpee's, Etsy, Wayfair), UI chrome text (opens a new tab, showing X pins, preview, merchant, product name, past X months)
- File: `app/routes.py` → `trends_paste()` → `ui_noise` pattern

---

## General Rules Learned

| Rule | Detail |
|------|--------|
| JS parse errors kill the whole page silently | One `await` in a non-async function = entire script block fails |
| CDN scripts race with inline scripts | Always render content server-side if it must appear on page load |
| Pinterest blocks Cloud Run IPs | Server-side fetch of pinterest.com fails; browser-side fetch works |
| Pin URL extraction works client-side | `fetch(pinUrl, {credentials:'omit'})` + JSON-LD `headline` field |
| Product names need `clean_product()` | `clean_kw()` has 80-char max and lowercases — kills product names |
| Long strings from full page = products | Lines >25 chars in full page dump are product names, not keywords |
| `location.reload()` preserves query params | Use `location.href = '/path'` for clean navigation |
| SerpAPI is 250/month free, resets May 10 | Do not run auto-discovery; manual only |
