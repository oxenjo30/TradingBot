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
`server/static/img/shots/`:

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
   - Stat tiles: `14 Strategies`, `10 Risk guards`, `24/7 Crypto`, `60s Tick` w/ sparklines.
   - Large framed screenshot tile: `overview.png` in browser-chrome frame, "Paper Trading"
     badge, glow/shadow, float-on-scroll.
   - Layout: balanced mosaic (headline shares row with tall screenshot; stat tiles fill
     the middle; wide screenshot anchors the bottom). Collapses to single column on mobile.
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
- Performance: PNG screenshots are 350–500KB each (retina @2x). Add `loading="lazy"` to all
  below-the-fold images so they don't block first paint.
- Typography: apply correct quotes/dashes/spacing throughout (handled during build).

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
