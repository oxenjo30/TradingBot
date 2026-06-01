# Landing Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat PrimusTrader landing page (`server/static/landing.html`) with a premium, bento-grid, product-led redesign that embeds real dashboard screenshots framed as paper-trading demos.

**Architecture:** A single self-contained HTML file (inline `<style>` + `<script>`, no build step, matching the existing pattern). Real dashboard screenshots (already captured in `server/static/img/shots/`) are converted to WebP and embedded throughout. All existing integrations (`/api/buy-url` injection, FAQ accordion, smooth-scroll, admin link, disclaimer, animated ticker) are preserved verbatim. Scroll-reveal animation via `IntersectionObserver`.

**Tech Stack:** Plain HTML/CSS/JS. Pillow (already installed, v12.2.0) for WebP conversion. Playwright + system Chrome (already installed) for visual verification. FastAPI/uvicorn already serves the page at `/` and `/static/landing.html`.

> **Verification note:** This is static HTML, not unit-testable code. Each task's "verify" step uses a concrete check instead of a unit test: convert+inspect assets, serve the page, screenshot it with Playwright (headless Chrome, 1440×900 and 390×844 mobile), and confirm specific elements render and integrations work. The app is already running on `http://localhost:8000`.

---

## File Structure

- **Create:** `server/static/img/shots/*.webp` — WebP variants of the 6 PNG screenshots (PNG sources retained).
- **Create:** `scripts/convert_shots_to_webp.py` — one-off, reusable converter (kept in repo for re-running if screenshots are re-captured).
- **Create:** `server/static/landing.old.html` — backup of the current landing page (safety net for in-place replacement).
- **Modify (full rewrite):** `server/static/landing.html` — the redesigned page.
- **Create (temp, deleted at end):** `verify_landing.py` — Playwright verification script.

There is no test directory for static assets; verification scripts live at repo root and are deleted after use (except the WebP converter, which is kept).

---

## Task 1: Convert screenshots to WebP

**Files:**
- Create: `scripts/convert_shots_to_webp.py`
- Create: `server/static/img/shots/{overview,performance,positions,risk,backtesting,balances}.webp`

- [ ] **Step 1: Write the converter script**

Create `scripts/convert_shots_to_webp.py`:

```python
"""Convert dashboard screenshot PNGs to WebP for the landing page.
Re-runnable: safe to run again if screenshots are re-captured.
PNG sources are kept as the capture source of truth."""
from pathlib import Path
from PIL import Image

SHOTS = Path(__file__).resolve().parent.parent / "server" / "static" / "img" / "shots"
NAMES = ["overview", "performance", "positions", "risk", "backtesting", "balances"]

def main():
    total_png = total_webp = 0
    for name in NAMES:
        png = SHOTS / f"{name}.png"
        webp = SHOTS / f"{name}.webp"
        if not png.exists():
            print(f"  SKIP {name}: {png} missing")
            continue
        img = Image.open(png).convert("RGB")
        img.save(webp, "WEBP", quality=82, method=6)
        p, w = png.stat().st_size, webp.stat().st_size
        total_png += p; total_webp += w
        print(f"  {name}: {p//1024}KB PNG -> {w//1024}KB WebP ({100 - w*100//p}% smaller)")
    print(f"TOTAL: {total_png//1024}KB PNG -> {total_webp//1024}KB WebP")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the converter**

Run: `.venv/Scripts/python.exe scripts/convert_shots_to_webp.py`
Expected: 6 lines like `overview: 384KB PNG -> ~90KB WebP (76% smaller)`, ending with a TOTAL line showing the WebP total well under 1MB.

- [ ] **Step 3: Verify the WebP files exist and are valid**

Run: `.venv/Scripts/python.exe -c "from PIL import Image; import pathlib; [print(p.name, Image.open(p).size) for p in sorted(pathlib.Path('server/static/img/shots').glob('*.webp'))]"`
Expected: 6 lines, each printing a `.webp` filename and a size tuple like `(1440, 900)` (or `(2880, 1800)` if @2x). No errors.

- [ ] **Step 4: Commit**

```bash
git add scripts/convert_shots_to_webp.py server/static/img/shots/
git commit -m "feat(landing): add dashboard screenshots + WebP converter"
```

> Note: `server/static/img/` is not gitignored (verified), so a plain `git add` works. This commits the 6 source PNGs + 6 WebP variants + the converter script.

---

## Task 2: Back up current landing page

**Files:**
- Create: `server/static/landing.old.html`

- [ ] **Step 1: Copy the current landing page to a backup**

Run: `cp server/static/landing.html server/static/landing.old.html`

- [ ] **Step 2: Verify the backup is byte-identical**

Run: `diff server/static/landing.html server/static/landing.old.html && echo "IDENTICAL"`
Expected: prints `IDENTICAL` (no diff output).

- [ ] **Step 3: Commit**

```bash
git add server/static/landing.old.html
git commit -m "chore(landing): back up current landing page before redesign"
```

---

## Task 3: Scaffold the new landing.html — head, theme, nav, hero bento

This task writes the **top half** of the new file: `<head>` (with OG meta + hero preload), the `:root` theme + base CSS, the nav, and the bento hero. The rest of the page is added in Task 4. The file is valid HTML after this task (closing `</body></html>` included, sections appended later).

**Files:**
- Modify (rewrite): `server/static/landing.html`

- [ ] **Step 1: Write the head + theme + nav + hero**

Replace the **entire** `server/static/landing.html` with the new document. Build it in this order (full code assembled by the implementer using the existing file's CSS variables and the snippets below — reuse the existing palette verbatim from `landing.old.html` `:root`):

`<head>` — keep existing title/description/font/preconnect, and ADD:

```html
  <!-- Open Graph / Twitter -->
  <meta property="og:title" content="PrimusTrader — Automated Trading Bot for Stocks & Crypto">
  <meta property="og:description" content="14 algorithmic strategies on stocks and crypto, risk-managed automatically. Test risk-free on paper, then go live.">
  <meta property="og:type" content="website">
  <meta property="og:image" content="/static/img/shots/overview.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="/static/img/shots/overview.png">
  <!-- Preload the above-the-fold hero screenshot (LCP element) -->
  <link rel="preload" as="image" href="/static/img/shots/overview.webp" fetchpriority="high">
```

Reuse the existing `:root` block and base styles from `landing.old.html` verbatim. ADD these new component styles (browser-frame, bento, scroll-reveal):

```css
    /* ── Browser-chrome frame for screenshots ──────────────────────────── */
    .shot-frame { border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
      background: var(--card); box-shadow: 0 30px 80px rgba(0,0,0,.55); position: relative; }
    .shot-frame .chrome { display: flex; align-items: center; gap: 6px; padding: 9px 12px;
      background: var(--bg2); border-bottom: 1px solid var(--border); }
    .shot-frame .chrome i { width: 10px; height: 10px; border-radius: 50%; background: #2a3b55; }
    .shot-frame .chrome .url { margin-left: 10px; font-size: 11px; color: var(--muted2);
      background: var(--card); border-radius: 6px; padding: 3px 12px; flex: 1; max-width: 260px; }
    .shot-frame img { display: block; width: 100%; height: auto; }
    .paper-chip { position: absolute; top: 52px; right: 14px; z-index: 2;
      font-size: 10px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
      color: var(--blue); background: rgba(59,130,246,.14); border: 1px solid rgba(59,130,246,.34);
      padding: 4px 10px; border-radius: 20px; backdrop-filter: blur(4px); }

    /* ── Bento hero ─────────────────────────────────────────────────────── */
    .bento { display: grid; grid-template-columns: 1.25fr 1fr; gap: 14px; margin-top: 24px; }
    .bento .tile { background: var(--card); border: 1px solid var(--border);
      border-radius: 16px; padding: 26px; }
    .bento .tile-hero { grid-row: span 2; display: flex; flex-direction: column;
      justify-content: center;
      background: radial-gradient(120% 90% at 18% 0%, rgba(139,92,246,.18), transparent 60%), var(--card); }
    .bento .tile-shot { grid-column: 1 / -1; padding: 0; border: none; background: none; }
    .bento .stat-tile .stat-num { font-size: 38px; }
    @media (max-width: 860px) {
      .bento { grid-template-columns: 1fr; }
      /* mobile source order: hero (headline+CTA) -> shot -> stats. Achieve with order. */
      .bento .tile-hero { order: 1; } .bento .tile-shot { order: 2; }
      .bento .stat-tile { order: 3; }
    }

    /* ── Scroll reveal ──────────────────────────────────────────────────── */
    .reveal { opacity: 0; transform: translateY(24px); transition: opacity .6s ease, transform .6s ease; }
    .reveal.in { opacity: 1; transform: none; }
    @media (prefers-reduced-motion: reduce) {
      .reveal { opacity: 1; transform: none; transition: none; }
      .ticker-track { animation: none; }
    }
```

Keep the existing nav verbatim (logo, links, `BUY_URL_PLACEHOLDER` CTA).

Replace the old `.hero` section with the bento hero. **The hero must reintroduce the 60px fixed-nav offset** (the old ticker did this; the bento is now first). Wrap the hero container with `style="padding-top: 84px;"` (60px nav + 24px breathing room):

```html
<section class="hero-bento" style="padding-top:84px;">
  <div class="container">
    <div class="bento">
      <div class="tile tile-hero">
        <div class="hero-eyebrow">
          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><circle cx="5" cy="5" r="5"/></svg>
          Live · 24/7 · No coding required
        </div>
        <h1 class="hero-title" style="font-size:clamp(32px,4.5vw,52px);">
          Automated trading,<br><span class="grad">on autopilot</span>
        </h1>
        <p class="hero-sub" style="margin:18px 0 26px;">
          PrimusTrader runs 14 strategies on stocks and crypto, manages risk for you,
          and lets you test everything risk-free on paper before going live.
        </p>
        <div class="hero-actions" style="justify-content:flex-start;">
          <a href="BUY_URL_PLACEHOLDER" class="btn-primary" id="hero-buy-btn">Get PrimusTrader — $249</a>
          <a href="#showcase" class="btn-ghost">See it in action</a>
        </div>
        <p class="hero-note" style="text-align:left;">Test on paper first · Lifetime license · Windows &amp; Linux</p>
      </div>

      <div class="tile stat-tile"><div class="stat-num">14</div><div class="stat-label">Built-in strategies</div></div>
      <div class="tile stat-tile"><div class="stat-num">9</div><div class="stat-label">Risk guards</div></div>

      <div class="tile-shot">
        <div class="shot-frame">
          <div class="chrome"><i></i><i></i><i></i><span class="url">localhost:8000 — Dashboard</span></div>
          <span class="paper-chip">Paper Trading</span>
          <img src="/static/img/shots/overview.webp" width="1440" height="900"
               fetchpriority="high" decoding="async"
               alt="PrimusTrader dashboard showing total balance, daily P&L, KPI cards and a performance chart">
        </div>
      </div>
    </div>
  </div>
</section>
```

> **Risk-guard count:** The hero stat tile uses `9` (the actual number of guards shown in the risk checklist — verified: `risk-text-title` appears 9× in `landing.old.html`). The "10 guards" copy elsewhere will be reconciled to 9 in Task 4 (Risk section). Keep the number consistent at **9** across the whole page.

Then place the existing **ticker** block immediately after the hero (remove its old inline `margin-top:60px` since it's no longer the first element):

```html
<div class="ticker-wrap"><!-- existing ticker-track content, unchanged --></div>
```

End the file for now with the existing `<script>` block and `</body></html>` so it stays valid. (Task 4 inserts sections before the script.)

- [ ] **Step 2: Verify the page serves and the hero renders**

Run: `.venv/Scripts/python.exe -c "import urllib.request; h=urllib.request.urlopen('http://localhost:8000/static/landing.html').read().decode(); assert 'tile-hero' in h and 'overview.webp' in h and 'preload' in h and 'BUY_URL_PLACEHOLDER' in h; print('OK: hero, webp, preload, buy-placeholder all present')"`
Expected: prints `OK: ...`. (Confirms the new markup is being served and the buy-url placeholder is intact.)

- [ ] **Step 3: Commit**

```bash
git add server/static/landing.html
git commit -m "feat(landing): bento hero, browser-framed hero screenshot, OG meta, LCP preload"
```

---

## Task 4: Build the screenshot showcase + restyle remaining sections

Insert all remaining sections **between the ticker and the closing `<script>`**, in this order: Showcase (NEW) → Features → Strategies → How it works → Risk → Pricing → FAQ → CTA banner → Footer → Disclaimer. Reuse the existing markup for Features/Strategies/Steps/Pricing/FAQ/CTA/Footer/Disclaimer verbatim from `landing.old.html`; only ADD the showcase and apply the risk-count fix.

**Files:**
- Modify: `server/static/landing.html`

- [ ] **Step 1: Add the showcase section CSS** (inside the existing `<style>`)

```css
    /* ── Screenshot showcase ────────────────────────────────────────────── */
    #showcase .show-row { display: grid; grid-template-columns: 1fr 1fr; gap: 44px;
      align-items: center; margin-top: 64px; }
    #showcase .show-row:nth-child(even) .show-text { order: 2; }
    #showcase .show-eyebrow { font-size: 11px; font-weight: 700; color: var(--blue);
      text-transform: uppercase; letter-spacing: .12em; margin-bottom: 12px; }
    #showcase .show-title { font-size: clamp(22px, 3vw, 32px); font-weight: 800;
      letter-spacing: -.02em; line-height: 1.18; margin-bottom: 12px; }
    #showcase .show-desc { font-size: 15px; color: var(--muted); line-height: 1.65; }
    @media (max-width: 760px) {
      #showcase .show-row { grid-template-columns: 1fr; gap: 22px; }
      #showcase .show-row .show-text { order: 1 !important; }
    }
```

- [ ] **Step 2: Add the showcase section markup** (immediately after the ticker)

```html
<section id="showcase">
  <div class="container">
    <div class="section-eyebrow text-center">See it in action</div>
    <h2 class="section-title text-center">The whole product, before you buy</h2>
    <p class="section-sub text-center" style="margin:0 auto;">Real screenshots from the dashboard, running in paper-trading mode.</p>
```

Then 5 `.show-row` blocks. Each follows this exact template — substitute the per-row values from the table below:

```html
    <div class="show-row reveal">
      <div class="show-text">
        <div class="show-eyebrow">{EYEBROW}</div>
        <h3 class="show-title">{TITLE}</h3>
        <p class="show-desc">{DESC}</p>
      </div>
      <div class="shot-frame">
        <div class="chrome"><i></i><i></i><i></i><span class="url">localhost:8000 — {URLLABEL}</span></div>
        <span class="paper-chip">Paper Trading</span>
        <img src="/static/img/shots/{FILE}.webp" width="1440" height="900" loading="lazy" decoding="async" alt="{ALT}">
      </div>
    </div>
```

Row values:

| FILE | EYEBROW | TITLE | DESC | URLLABEL | ALT |
|------|---------|-------|------|----------|-----|
| performance | Performance | Know exactly what's working | Per-strategy statistics, top symbols, and signal counts — see which of your strategies are pulling their weight at a glance. | Performance | Performance page with strategy statistics table and top traded symbols |
| positions | Positions & orders | Every position, every order, one view | Open positions with live P&L, full order history, and a manual order ticket — all on a single screen. | Positions | Positions and orders page showing open positions and order history |
| risk | Risk management | 9 guards between you and a bad trade | Kill switch, daily loss limits, PDT protection, take-profit and more. Every signal passes all guards before an order is placed. | Risk | Risk management page showing kill switch, loss limits and trading guards |
| backtesting | Backtesting | Test before you risk a dollar | Run any strategy against historical data with slippage and commissions. Save runs and compare returns against a benchmark. | Backtesting | Backtesting studio with configuration panel and saved run results |
| balances | Balances | Stocks and crypto, side by side | Equity, cash and buying power up top; stock and crypto holdings below — across every connected broker. | Balances | Balances page showing equity KPIs with stock and crypto holdings |

Close the section: `  </div></section>`

- [ ] **Step 3: Append the remaining sections verbatim from `landing.old.html`**

Copy these sections **unchanged** from `landing.old.html`, in order, after the showcase: `#features`, `#strategies`, How-it-works, Risk, `#pricing`, `#faq`, CTA banner, footer, disclaimer. Then the existing `<script>` and `</body></html>`.

> **Do NOT copy the old `.stats-bar` block** (the standalone "14 / 10 / 24/7 / 60s" grid, ~lines 503-523 of `landing.old.html`). Those four numbers now live in the bento hero as stat tiles (`14`, `9`, plus you may add `24/7 Crypto` and `60s Tick` tiles if desired). Copying the stats-bar too would duplicate them. The bento hero in Task 3 includes only two stat tiles (`14`, `9`); if you want all four, add `24/7`/`60s` tiles there instead of reusing the old bar.

**One edit during the copy — reconcile the risk-guard count to 9:**
- In the Risk section heading, change `10 guards between you<br>and a bad trade` → `9 guards between you<br>and a bad trade`.
- In the features grid, change the `10-Layer Risk Engine` feature title → `9-Layer Risk Engine` and its description "and per-account controls." stays.
- Search the file for the string `10` near risk/guard copy and ensure no remaining "10 guards"/"10-layer"/"10 Risk guard" text. (The stats-bar "10 / Risk guard layers" item, if copied, → `9`.)

Run after editing: `grep -n "10.\{0,12\}[Gg]uard\|10-[Ll]ayer\|10-[Ll]evel" server/static/landing.html`
Expected: **no matches** (empty output).

- [ ] **Step 4: Add `reveal` class to showcase rows and section headers**

Ensure each `.show-row` has class `reveal` (already in template). Optionally add `reveal` to `.feat-card` and `.section-title` blocks for the scroll-in effect. Keep it tasteful — not every element.

- [ ] **Step 5: Verify all 5 showcase images + sections are present**

Run: `.venv/Scripts/python.exe -c "import urllib.request; h=urllib.request.urlopen('http://localhost:8000/static/landing.html').read().decode(); [print(n, n in h) for n in ['performance.webp','positions.webp','risk.webp','backtesting.webp','balances.webp']]; assert all(s in h for s in ['id=\"features\"','id=\"strategies\"','id=\"pricing\"','id=\"faq\"','disclaimer']); print('ALL SECTIONS PRESENT')"`
Expected: 5 `True` lines + `ALL SECTIONS PRESENT`.

- [ ] **Step 6: Commit**

```bash
git add server/static/landing.html
git commit -m "feat(landing): add real-screenshot showcase, restyle sections, reconcile guard count to 9"
```

---

## Task 5: Wire the scroll-reveal JS and preserve existing scripts

**Files:**
- Modify: `server/static/landing.html` (the `<script>` block)

- [ ] **Step 1: Confirm the three existing scripts are intact**

Run: `.venv/Scripts/python.exe -c "import urllib.request; h=urllib.request.urlopen('http://localhost:8000/static/landing.html').read().decode(); assert '/api/buy-url' in h and 'faq-q' in h and \"a[href^='#']\".replace(chr(39),chr(34)) in h or 'a[href^=' in h; print('buy-url, faq, smooth-scroll scripts present')"`
Expected: `buy-url, faq, smooth-scroll scripts present`.

- [ ] **Step 2: Add the IntersectionObserver reveal script** (inside the existing `<script>`, after the smooth-scroll block)

```javascript
  // ── Scroll reveal ─────────────────────────────────────────────────────────
  (() => {
    const els = document.querySelectorAll('.reveal');
    if (!('IntersectionObserver' in window) || !els.length) {
      els.forEach(el => el.classList.add('in'));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    els.forEach(el => io.observe(el));
  })();
```

- [ ] **Step 3: Verify the reveal script is served**

Run: `.venv/Scripts/python.exe -c "import urllib.request; h=urllib.request.urlopen('http://localhost:8000/static/landing.html').read().decode(); assert 'IntersectionObserver' in h and 'reveal' in h; print('reveal script present')"`
Expected: `reveal script present`.

- [ ] **Step 4: Commit**

```bash
git add server/static/landing.html
git commit -m "feat(landing): scroll-reveal animation via IntersectionObserver"
```

---

## Task 6: Visual verification (desktop + mobile) and buy-url integration check

**Files:**
- Create (temp): `verify_landing.py`

- [ ] **Step 1: Write the verification script**

Create `verify_landing.py`:

```python
"""Visual + integration verification for the redesigned landing page. Temp — delete after."""
from playwright.sync_api import sync_playwright

URL = "http://localhost:8000/static/landing.html"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--force-color-profile=srgb"])

    # Desktop full-page
    d = b.new_context(viewport={"width":1440,"height":900}, device_scale_factor=2, color_scheme="dark")
    pg = d.new_page(); pg.goto(URL, wait_until="domcontentloaded"); pg.wait_for_timeout(1800)
    # buy-url must be injected (no placeholder left in any href)
    placeholders = pg.eval_on_selector_all("[href='BUY_URL_PLACEHOLDER']", "els => els.length")
    print("unresolved buy-url placeholders:", placeholders, "(expect 0 if /api/buy-url responds, else 4)")
    # hero image loaded?
    hero_ok = pg.eval_on_selector(".tile-shot img", "img => img.complete && img.naturalWidth > 0")
    print("hero screenshot loaded:", hero_ok)
    # all showcase images loaded?
    imgs_ok = pg.eval_on_selector_all("#showcase img", "els => els.every(i => i.complete && i.naturalWidth>0)")
    print("all showcase images loaded:", imgs_ok)
    pg.screenshot(path="landing_desktop.png", full_page=True)

    # Mobile — CTA above the fold?
    m = b.new_context(viewport={"width":390,"height":844}, device_scale_factor=2, color_scheme="dark")
    mp = m.new_page(); mp.goto(URL, wait_until="domcontentloaded"); mp.wait_for_timeout(1500)
    box = mp.eval_on_selector("#hero-buy-btn", "el => { const r = el.getBoundingClientRect(); return r.top; }")
    print("mobile primary CTA top (px from viewport top):", round(box), "(want < 844 = above fold)")
    mp.screenshot(path="landing_mobile.png")  # viewport only

    b.close()
print("DONE")
```

- [ ] **Step 2: Run verification**

Run: `.venv/Scripts/python.exe verify_landing.py`
Expected output includes:
- `hero screenshot loaded: True`
- `all showcase images loaded: True`
- `mobile primary CTA top ...: <some number under 844>`
- `unresolved buy-url placeholders: 0` (if the dev server's `/api/buy-url` returns a URL) **or** `4` (if it returns nothing — acceptable, means the JS ran but there was no URL to inject; the fallback URL is applied client-side either way). If it's neither 0 nor 4, the injection script broke — investigate.

- [ ] **Step 3: Inspect the screenshots**

Read `landing_desktop.png` and `landing_mobile.png` (use the Read tool to view them). Confirm:
- Desktop: bento hero with framed dashboard screenshot, "Paper Trading" chips visible, 5 showcase rows with real screenshots alternating sides, pricing card, no layout breakage, hero not hidden under the nav.
- Mobile: single column, headline + CTA before the screenshot, nothing overflowing, CTA reachable near the top.

If anything is broken, fix `landing.html` and re-run Step 2 before continuing.

- [ ] **Step 4: Clean up the temp verification artifacts**

Run: `rm -f verify_landing.py landing_desktop.png landing_mobile.png`
Expected: no error.

- [ ] **Step 5: Commit (only if landing.html changed during fixes)**

```bash
git add server/static/landing.html
git commit -m "fix(landing): visual verification adjustments" || echo "no changes to commit"
```

---

## Task 7: Final cleanup and full-page review

**Files:** none created; review only.

- [ ] **Step 1: Confirm no temp/capture scripts remain at repo root**

Run: `ls capture_*.py verify_landing.py 2>/dev/null && echo "TEMP FILES STILL PRESENT — remove them" || echo "clean"`
Expected: `clean`.

- [ ] **Step 2: Confirm the old page is preserved and the WebP converter is kept**

Run: `ls server/static/landing.old.html scripts/convert_shots_to_webp.py && echo "OK"`
Expected: both paths listed + `OK`.

- [ ] **Step 3: Final diff review**

Run: `git log --oneline 343d96f..HEAD`
Expected: a clean sequence of the redesign commits (spec, WebP, backup, hero, showcase, reveal, optional fixes).

- [ ] **Step 4: Reload the real page in a browser to eyeball it**

Open `http://localhost:8000/` (the root route serves the landing page). Confirm it looks premium, the screenshots load, the FAQ accordion opens/closes, nav links smooth-scroll, and the buy buttons point at a real URL (hover to check the href).

---

## Self-Review Checklist (completed by plan author)

- **Spec coverage:** bento hero ✓(T3), real screenshots throughout ✓(T1,T3,T4), paper-trading framing ✓(chips in T3/T4), WebP + LCP strategy ✓(T1,T3), fixed-nav offset ✓(T3 padding-top:84px), mobile CTA-first order ✓(T3 CSS order + T6 check), guard-count reconciliation to 9 ✓(T4 S3), OG meta ✓(T3), preserve buy-url/FAQ/smooth-scroll/admin/disclaimer/ticker ✓(T3,T4,T5), scroll reveal ✓(T5), backup landing.old.html ✓(T2), prefers-reduced-motion ✓(T3 CSS).
- **Placeholder scan:** showcase row template uses `{TOKENS}` filled from an explicit table — not vague placeholders. No "TODO"/"handle later".
- **Type/name consistency:** class names (`shot-frame`, `chrome`, `url`, `paper-chip`, `tile-hero`, `tile-shot`, `stat-tile`, `reveal`, `in`, `show-row`, `show-text`) used identically across CSS, markup, and JS. Image filenames match the 6 captured shots. Hero CTA id `hero-buy-btn` reused in T6 verification.
