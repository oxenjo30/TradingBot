"""Market scanner — fetches most-active and top-gaining stocks from Alpaca screener."""
import logging
import time
import httpx

log = logging.getLogger("scanner")

_BASE = "https://data.alpaca.markets/v1beta1/screener/stocks"


def _headers() -> dict:
    from .alpaca_client import _db_alpaca_creds
    key, secret, _ = _db_alpaca_creds()
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

_cache: dict = {"ts": 0.0, "actives": [], "gainers": [], "losers": []}
_TTL = 300  # 5-min cache


def _is_valid(symbol: str, price: float, min_price: float, max_price: float) -> bool:
    if price < min_price or price > max_price:
        return False
    # skip warrants, rights, units — they have dots, numbers, or trailing W/R
    if not symbol.isalpha():
        return False
    if len(symbol) > 5:
        return False
    return True


def _fetch():
    global _cache
    now = time.time()
    if now - _cache["ts"] < _TTL:
        return

    hdrs = _headers()
    try:
        r1 = httpx.get(f"{_BASE}/most-actives", headers=hdrs,
                        params={"by": "volume", "top": 100}, timeout=15)
        r1.raise_for_status()
        actives_raw = r1.json().get("most_actives", [])
    except Exception as e:
        log.warning("most-actives fetch failed: %s", e)
        actives_raw = []

    try:
        # Alpaca's /movers endpoint caps `top` at 50 (returns 400 above that),
        # unlike /most-actives which allows 100.
        r2 = httpx.get(f"{_BASE}/movers", headers=hdrs,
                        params={"top": 50}, timeout=15)
        r2.raise_for_status()
        data = r2.json()
        gainers_raw = data.get("gainers", [])
        losers_raw = data.get("losers", [])
    except Exception as e:
        log.warning("movers fetch failed: %s", e)
        gainers_raw = []
        losers_raw = []

    _cache = {
        "ts": now,
        "actives": actives_raw,
        "gainers": gainers_raw,
        "losers": losers_raw,
    }


def get_most_actives(top_n: int = 30, min_price: float = 5.0,
                     max_price: float = 1000.0) -> list[str]:
    _fetch()
    out = []
    for s in _cache["actives"]:
        sym = s.get("symbol", "")
        price = s.get("price") or 0.0
        # most-actives endpoint doesn't return price; we filter after
        if not sym.isalpha() or len(sym) > 5:
            continue
        out.append(sym)
        if len(out) >= top_n:
            break
    return out


def get_top_gainers(top_n: int = 20, min_price: float = 5.0,
                    max_price: float = 1000.0) -> list[str]:
    _fetch()
    out = []
    for s in _cache["gainers"]:
        sym = s.get("symbol", "")
        price = float(s.get("price") or 0)
        if not _is_valid(sym, price, min_price, max_price):
            continue
        out.append(sym)
        if len(out) >= top_n:
            break
    return out


def get_top_losers(top_n: int = 20, min_price: float = 5.0,
                   max_price: float = 1000.0) -> list[str]:
    _fetch()
    out = []
    for s in _cache["losers"]:
        sym = s.get("symbol", "")
        price = float(s.get("price") or 0)
        if not _is_valid(sym, price, min_price, max_price):
            continue
        out.append(sym)
        if len(out) >= top_n:
            break
    return out


def get_scanner_universe(min_price: float = 5.0, max_price: float = 1000.0,
                         top_actives: int = 20, top_gainers: int = 10) -> list[str]:
    """Merged deduplicated list: most-active + top-gaining stocks."""
    seen: set[str] = set()
    out: list[str] = []
    for sym in get_most_actives(top_actives, min_price, max_price) + \
               get_top_gainers(top_gainers, min_price, max_price):
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def get_raw() -> dict:
    """Return raw screener data for dashboard display."""
    _fetch()
    return {
        "gainers": _cache["gainers"][:20],
        "losers": _cache["losers"][:20],
        "actives": _cache["actives"][:20],
        "cached_at": _cache["ts"],
    }
