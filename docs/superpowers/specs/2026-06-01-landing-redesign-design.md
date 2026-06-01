# PrimusTrader Landing Page Redesign — Design Spec

**Date:** 2026-06-01
**Goal:** Redesign the landing page to feel premium/modern, show the real product, and drive purchases.

## Direction

Bento-grid, modern-2026-SaaS aesthetic. Dark theme. Premium and product-led. Real
dashboard screenshots embedded throughout, framed as paper-trading demos.

The current `landing.html` is competent but flat: all text and cards, zero product
imagery. The redesign keeps the good content and structure but (a) replaces the flat
centered hero with a bento grid, (b) injects real screenshot showcase rows, and
(c) unifies everything under a more premium, glowy, animated visual language.

## Visual language

- **Palette:** keep existing CSS variables (`--bg #060C14`, `--blue #3B82F6`,
  `--purple #8B5CF6`, `--green #10B981`, etc.). Dark, blue→purple gradients.
- **Font:** Inter (already loaded).
- **Tiles:** rounded 12–16px, `1px` borders, gradient-on-hover, soft shadows, subtle
  radial glow on hero/feature tiles.
- **Screenshots:** wrapped in a faux browser-chrome frame (three dots + faux URL bar),
  drop shadow, soft glow, slight float/parallax + fade-up on scroll. Each carries a
  small "Paper Trading" caption chip.
- **Motion:** keep the animated price ticker; add scroll-triggered fade/slide-up via
  `IntersectionObserver`; keep CTA hover lifts. Respect `prefers-reduced-motion`.

## Assets

Real screenshots captured from the running dashboard (read-only), stored in
`server/static/img/shots/`. **Source PNGs are kept; a WebP variant of each is generated
and referenced first** (PNGs total ~2.4MB which is too heavy — WebP cuts UI screenshots
60–80% at visually identical quality). Use `<img src="...webp">` directly (this is a
modern dark-SaaS page; no need for a `<picture>` PNG fallback, but the PNGs remain on disk
as the capture source of truth).

- `overview.png` — dashboard: balance $98K, daily P&L, KPI cards w/ sparklines, perf chart
- `performance.png` — strategy statistics table, top symbols, 256 signals
- `positions.png` — open positions, order history, manual order panel
- `risk.png` — kill switch, daily loss limit, PDT protection, take-profit
- `backtesting.png` — config panel + saved runs with returns/benchmarks
- `balances.png` — equity/cash KPIs, stock + crypto holdings

Screenshots contain real ticker symbols and P&L (incl. red/losing positions). These are
shown **as-is** but framed with "Paper Trading" labels so red numbers read as harmless
sandbox activity — honest, and doubles as a "test risk-free first" selling point.
No API keys, account numbers, or passwords are visible in any shot (verified).

## Page structure (top → bottom)

1. **Nav** — keep existing glassmorphic fixed nav. Add a small "Paper-safe" trust chip.
2. **Hero — bento grid** (centerpiece):
   - Large headline tile (radial glow): eyebrow "● Live · 24/7 · No code", headline
     *"Automated trading, on autopilot"*, subtext, primary CTA (`Get PrimusTrader — $249`)
     + ghost CTA (`See how it works`), paper-trading trust line.
   - Stat tiles: `14 Strategies`, `N Risk guards`, `24/7 Crypto`, `60s Tick` w/ sparklines
     (sparklines are decorative/static SVG, not real data). `N` must equal the actual number
     of guards shown in the risk checklist (see §8 — reconcile to a single honest number).
   - Large framed screenshot tile: overview shot in browser-chrome frame, "Paper Trading"
     badge, glow/shadow, float-on-scroll. **This is the above-the-fold LCP image** — load it
     **eager** with `fetchpriority="high"`, explicit `width`/`height` (prevent layout shift),
     and a `<link rel="preload" as="image">` in `<head>`. Do NOT lazy-load it.
   - Layout: balanced mosaic (headline shares row with tall screenshot; stat tiles fill
     the middle; wide screenshot anchors the bottom).
   - **Fixed-nav offset:** the nav is `position:fixed; height:60px`. The current first
     element (ticker) compensates with `margin-top:60px`. Whatever becomes the new first
     below-nav element (the bento hero) MUST reintroduce that 60px top offset or it renders
     under the nav.
   - **Mobile:** collapses to a single column with source order **headline → CTA → hero
     screenshot → stat tiles**, so the primary CTA stays above the fold on a ~667px-tall
     phone viewport. Faux browser-chrome frame must stay legible at 360px width; stat-tile
     sparklines are decorative and may simplify/hide on narrow screens.
   - **Above-fold motion budget:** hero float + ticker + scroll-fade all compete in the
     first viewport — keep simultaneous motion restrained so it reads premium, not busy.
3. **Ticker strip** — keep existing animated price ticker, placed under the hero.
4. **"See it in action" — screenshot showcase** (NEW): alternating left/right rows, each a
   real screenshot in a browser frame + a short benefit headline & blurb:
   - `performance.png` → "Know exactly what's working"
   - `positions.png` → "Every position, every order, one view"
   - `risk.png` → "10 guards between you and a bad trade"
   - `backtesting.png` → "Test before you risk a dollar"
   - `balances.png` → "Stocks and crypto, side by side"
   Each shot gets a "Paper Trading" caption chip and fades/slides up on scroll.
5. **Features grid** — keep existing 6 cards, restyle to new tile aesthetic.
6. **Strategies** — keep two-column strategy list, lightly restyled.
7. **How it works** — keep the 4-step row.
8. **Risk** — risk shot lives in the showcase (#4); keep the checklist grid here.
   **Fix the count discrepancy:** copy claims "10 guards" but the checklist renders only 9
   items. Reconcile on this page — either add the missing guard(s) to reach 10, or change the
   headline/stat to match what's shown. Don't carry the credibility gap forward silently.
9. **Pricing** — keep single pricing card, elevate (stronger glow, animated gradient border).
10. **FAQ → CTA banner → Footer → Disclaimer** — keep, restyle to match.

## Constraints / preserve

- Single self-contained `server/static/landing.html` (inline `<style>`/`<script>`), matching
  the current file's pattern. No build step, no external framework.
- Preserve all existing integrations:
  - `/api/buy-url` fetch + `BUY_URL_PLACEHOLDER` href injection for all buy buttons.
  - FAQ accordion behavior.
  - Smooth-scroll anchor nav.
  - Admin login link in footer (`/static/login.html`).
  - Disclaimer banner text (legal).
- Same route/URL. Replace `landing.html` **in place**; back up the original to
  `landing.old.html` first.
- Accessibility: real `alt` text on every screenshot; sufficient contrast; keyboard-operable
  FAQ; `prefers-reduced-motion` disables non-essential animation.
- Performance:
  - Screenshots served as **WebP** (PNG sources retained on disk). Add `loading="lazy"` to
    all **below-the-fold** images (the 5 showcase shots) so they don't block first paint.
  - The **above-the-fold hero shot is the exception**: eager + `fetchpriority="high"` +
    explicit dimensions + `<link rel="preload">` so it becomes a fast LCP, not a slow one.
  - Target LCP under ~2.5s on a typical broadband cold load.
- Typography: apply correct quotes/dashes/spacing throughout **by hand during implementation**
  (there is no build step).
- `<head>`: add Open Graph + Twitter card meta (`og:title`, `og:description`, `og:image`
  using the overview screenshot, `twitter:card=summary_large_image`). The page now has real
  product imagery worth previewing when shared — cheap win.

## Out of scope

- Dashboard/app code changes. Only `landing.html` + new image assets.
- Pricing/copy strategy changes beyond hero headline polish.
- Testimonials, blog, or new backend endpoints.

## Success criteria

- Page leads with a real dashboard screenshot above the fold.
- At least 5 distinct real screenshots appear, each framed + paper-labeled.
- Premium feel: bento hero, glow, gradient accents, scroll motion.
- All existing CTAs, buy-url injection, FAQ, smooth scroll, and disclaimer still work.
- Renders cleanly on mobile (single column) and desktop.
