#!/usr/bin/env python3
"""Build the customer-facing PrimusTrader.zip from the current repo.

The customer build is the SAME codebase as the seller instance, minus all seller
secrets and tooling. Admin vs customer is a runtime-config distinction
(TRADEBOT_OWNER_MODE / TRADEBOT_LICENSE_PRIVATE_KEY); a buyer build simply omits
those and can only verify keys, not mint them (server/license.py).

This uses an ALLOWLIST — only the paths we explicitly name ship — so a secret can
never leak by being forgotten in a denylist. A forbidden-path assertion runs at the
end as a second safety net.

Usage:
    python scripts/build_customer_zip.py [--out DIR]

Produces, in --out (default <repo>/dist):
    PrimusTrader.zip            stable name served by /download/{token}
    PrimusTrader-v1.2.3.zip     versioned copy for records

Exit non-zero on any failure (missing file, forbidden path) — callers should treat
a non-zero exit as "do not ship".
"""
import argparse
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── What ships (allowlist) ──────────────────────────────────────────────────────
# Directories are copied recursively; files are copied as-is. Anything not listed
# here does NOT go in the zip.
INCLUDE_DIRS = [
    "server",   # the app code + static assets (filtered below)
]
INCLUDE_FILES = [
    "requirements.txt",
    "setup.bat",
    "start.bat",
    "CHANGELOG.md",   # curated, customer-facing release notes (no secrets)
    "TradeBot_Installation_Guide.pdf",
    "TradeBot_Setup_Guide.pdf",
]

# Within included dirs, skip these (bytecode, dev-only, the temp Whop dump, etc.)
SKIP_DIR_NAMES = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

# Seller-only files that live under server/ but must NOT ship to customers:
#   - dev mockups (design scratch)
#   - the seller's public marketing/legal pages served on primustrader.com
#     (a customer's local bot has no use for the landing or legal pages)
#   - the temp Whop payload dump
SKIP_FILE_NAMES = {
    "whop_debug.log",
    "mockup-bots.html", "mockup-bots-b.html", "mockup-crypto.html",
    "mockup-manual-order.html",
    # Seller's public legal pages (served on primustrader.com only). landing.html
    # IS kept — the customer's local bot serves it as its entry page.
    "privacy.html", "refund.html", "terms.html",
}

# ── Hard guard: none of these may ever appear in the artifact ────────────────────
FORBIDDEN_SUBSTRINGS = [
    ".env",            # any env file (also catches .env.example — fine, buyers don't need it)
    "trading.db",      # the live database
    "private",         # private key material
    "license_private",
    "/.git",
    "generate_license",
    "gen_license",
    "deploy.sh",
    "vps-setup",
    "whop_debug",
    "/scripts/",       # build + license tooling never ships
    "/legal/",         # seller legal docs
    "/tests/",
]


def _version() -> str:
    """Read INSTALLED_VERSION from server/version.py (reuse bump_version logic)."""
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import bump_version  # noqa: WPS433
        major, minor, patch = bump_version.read_version()
        return f"v{major}.{minor}.{patch}"
    except Exception:
        # Fallback: parse the file directly
        import re
        text = (REPO / "server" / "version.py").read_text(encoding="utf-8")
        m = re.search(r'["\']v?(\d+\.\d+\.\d+)["\']', text)
        return f"v{m.group(1)}" if m else "v0.0.0"


def _should_skip(path: Path) -> bool:
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix in SKIP_SUFFIXES:
        return True
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    return False


def collect_files() -> list[tuple[Path, str]]:
    """Return [(absolute_source_path, arcname), ...] for everything that ships."""
    items: list[tuple[Path, str]] = []

    for rel in INCLUDE_FILES:
        src = REPO / rel
        if not src.exists():
            raise SystemExit(f"ERROR: required file missing from repo: {rel}")
        items.append((src, rel))

    for rel_dir in INCLUDE_DIRS:
        base = REPO / rel_dir
        if not base.is_dir():
            raise SystemExit(f"ERROR: required dir missing from repo: {rel_dir}")
        for src in sorted(base.rglob("*")):
            if src.is_dir() or _should_skip(src):
                continue
            arc = str(src.relative_to(REPO)).replace("\\", "/")
            items.append((src, arc))

    return items


def assert_no_secrets(items: list[tuple[Path, str]]) -> None:
    """Fail loudly if any forbidden path slipped into the build list."""
    offenders = []
    for _src, arc in items:
        a = "/" + arc.lower()
        if any(bad in a for bad in FORBIDDEN_SUBSTRINGS):
            offenders.append(arc)
    if offenders:
        raise SystemExit(
            "ERROR: forbidden paths in customer build — refusing to ship:\n  "
            + "\n  ".join(offenders)
        )


def build(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    items = collect_files()
    assert_no_secrets(items)

    version = _version()
    stable = out_dir / "PrimusTrader.zip"
    versioned = out_dir / f"PrimusTrader-{version}.zip"

    # Write the versioned zip, then copy to the stable name.
    if versioned.exists():
        versioned.unlink()
    with zipfile.ZipFile(versioned, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arc in items:
            zf.write(src, arc)

    # Copy to stable name (the one /download serves)
    import shutil
    shutil.copy2(versioned, stable)

    print(f"Built customer zip {version}: {len(items)} files")
    print(f"  {versioned}")
    print(f"  {stable}")
    return stable


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Build the customer PrimusTrader.zip")
    ap.add_argument("--out", default=str(REPO / "dist"),
                    help="output directory (default: <repo>/dist)")
    ap.add_argument("--list", action="store_true",
                    help="print the file list and exit without zipping")
    args = ap.parse_args(argv)

    if args.list:
        items = collect_files()
        assert_no_secrets(items)
        for _src, arc in items:
            print(arc)
        print(f"\n{len(items)} files")
        return 0

    build(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
