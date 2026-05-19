# Check for Updates — Design Spec

## Goal

Add a "Software Updates" card to the Settings page that lets TradeBot users check whether a newer version has been published on GitHub. The check is manual (button-triggered), reads from the GitHub Releases API, and displays the installed version alongside the latest release with release notes when an update is available.

---

## Background

TradeBot is sold as a self-hosted script. Users install a version and run it locally; there is no automatic update mechanism. This feature gives buyers a one-click way to see whether they are running the latest release without leaving the app.

---

## Design

### Installed Version

A constant `INSTALLED_VERSION = "v1.0.0"` is defined in `server/version.py`. This is the single source of truth — the backend reads it and the frontend receives it from the API. When a new release is prepared, the developer bumps this constant.

### Backend — `GET /api/update/check`

- Protected by `_require_auth` (same as all other authenticated endpoints).
- Reads `INSTALLED_VERSION` from `server/version.py`.
- Makes an outbound HTTPS GET to:
  ```
  https://api.github.com/repos/oxenjo30/TradingBot/releases/latest
  ```
  with `User-Agent: TradeBot-UpdateCheck/1.0` and a 10-second timeout.
- Parses `tag_name` (latest version) and `body` (release notes markdown, trimmed to 1000 chars).
- Returns JSON:
  ```json
  {
    "installed": "v1.0.0",
    "latest": "v1.2.0",
    "up_to_date": false,
    "release_notes": "- Feature A\n- Feature B",
    "release_url": "https://github.com/oxenjo30/TradingBot/releases/tag/v1.2.0"
  }
  ```
- If the GitHub API call fails (network error, non-200 response, JSON parse error), returns HTTP 502 with `{"detail": "Unable to reach GitHub"}`.
- Version comparison is a simple string equality check (`installed == latest`). No semver parsing — the GitHub tag is authoritative.

### Frontend — Settings page card

The card is appended after the existing cards in `settings.html`, just before the Save Bar / bottom of `<main>`.

**Four UI states (mutually exclusive, managed by JS):**

| State | Trigger | UI |
|---|---|---|
| **default** | Page load | Blue "Check for Updates" button, no badge |
| **checking** | Button clicked | Blue spinning "Checking…" badge, button hidden |
| **up-to-date** | API returns `up_to_date: true` | Green "Up to date" badge + ghost "Check Again" button |
| **update-available** | API returns `up_to_date: false` | Amber "Update available" badge + ghost "Check Again" button + release notes box |

The "Check for Updates" / "Check Again" button calls `GET /api/update/check`. On error, it shows a red inline message: "Unable to reach GitHub. Try again later."

The release notes box (shown only when an update is available):
- Title: "What's new in `{latest}`" with a "Latest release" blue tag.
- Release notes text from the API (plain text rendered as-is in a `<pre>`-style div).
- A "View full release on GitHub →" external link pointing to `release_url`.

**CSS:** Uses existing CSS variables (`var(--bg)`, `var(--card)`, `var(--border)`, `var(--text)`, `var(--muted)`, `var(--green)`, `var(--orange)`, `var(--blue)`) so dark/light mode works automatically. Uses existing `.card`, `.btn`, `.btn-primary`, `.btn-ghost`, `.badge`, `.icon-circle` classes where possible. New classes scoped under `#update-card` to avoid conflicts.

**No persistence:** The check result is not cached or stored. Each button click makes a fresh API call.

---

## Files

| File | Change |
|---|---|
| `server/version.py` | New — defines `INSTALLED_VERSION = "v1.0.0"` |
| `server/main.py` | Add `GET /api/update/check` endpoint (~25 lines) |
| `server/static/settings.html` | Add Software Updates card HTML block |
| `server/static/app.js` | Add `initUpdateCard()` function and call at page init |
| `server/static/styles.css` | Add minimal scoped styles for the update card states |

No new dependencies — outbound HTTP uses Python's `httpx` (already a project dependency via FastAPI).

---

## Error Handling

- GitHub unreachable or returns non-200: backend returns 502; frontend shows inline red error message.
- GitHub returns a release with no `body`: `release_notes` is `""` and the release notes box is omitted.
- `INSTALLED_VERSION` missing/malformed: impossible at runtime (it's a constant); no guard needed.

---

## Out of Scope

- Automatic update download or installation.
- Semver comparison or pre-release filtering.
- Caching the last-checked result across page loads.
- Auto-checking on page load.
