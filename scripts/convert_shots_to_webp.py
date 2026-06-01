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
