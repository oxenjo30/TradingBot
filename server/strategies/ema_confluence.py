from .base import Strategy, Signal


def _ema(closes: list, period: int):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period
    for price in closes[period:]:
        val = price * k + val * (1 - k)
    return val


_SCALE = {4: 1.0, 3: 0.70, 2: 0.40}


class EMAConfluence(Strategy):
    name = "ema_confluence"
    label = "4-EMA Confluence"
    description = (
        "Scores EMA 8/13/48/200 alignment to find high-conviction trend entries. "
        "Requires all scored EMAs to agree -- no mixed signals. Position size scales "
        "with confluence score when enabled. Works on stocks (daily) and crypto (hourly)."
    )
    brokers = ["alpaca", "binance"]
    default_params = {
        "symbols": [],
        "use_scanner": True,
        "timeframe": "day",
        "min_confluence": 3,
        "scaled_sizing": True,
        "notional": 500,
        "avoid_earnings": False,
        "max_positions": 5,
    }
    params_schema = [
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Comma-separated tickers to always include. Leave empty to rely on the scanner (stocks) or provide a list (crypto)."},
        {"key": "use_scanner", "label": "Auto-discover Stocks", "type": "bool",
         "hint": "When enabled, top active and gaining stocks are added automatically each tick. Ignored for Binance accounts."},
        {"key": "timeframe", "label": "Timeframe", "type": "select",
         "options": ["day", "hour"],
         "hint": "Use 'day' for stocks (Alpaca) and 'hour' for crypto (Binance)."},
        {"key": "min_confluence", "label": "Min Confluence Score", "type": "number", "min": 2, "max": 4,
         "hint": "How many of the 4 EMAs must agree for a signal. 4 = all four aligned (highest conviction), 2 = any two. Mixed signals always block a trade."},
        {"key": "scaled_sizing", "label": "Scale Size by Score", "type": "bool",
         "hint": "When on: score 4 uses 100% of the notional amount, score 3 uses 70%, score 2 uses 40%. When off, always trades the full amount."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "ai_tunable": False,
         "hint": "Maximum USD to spend on a single buy. At confluence score 4 the full amount is used; lower scores use a fraction when scaled sizing is on."},
        {"key": "avoid_earnings", "label": "Skip Earnings Days", "type": "bool",
         "hint": "Skip symbols that have an earnings announcement within 2 days. Alpaca only -- crypto is always exempt."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 50,
         "ai_tunable": False,
         "hint": "Maximum number of symbols this strategy can hold at the same time."},
    ]

    def _get_symbols(self) -> list:
        fixed = [s.upper().strip() for s in (self.params.get("symbols") or []) if s]
        if self.params.get("use_scanner", True):
            try:
                from .. import scanner
                scanned = scanner.get_scanner_universe(
                    min_price=5.0, max_price=500.0, top_actives=25, top_gainers=15
                )
                seen = set(fixed)
                for s in scanned:
                    if s not in seen:
                        fixed.append(s)
                        seen.add(s)
            except Exception:
                pass
        return fixed

    def _near_earnings(self, client, symbol: str) -> bool:
        try:
            return client.has_earnings_soon(symbol, days=2)
        except Exception:
            return False

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        min_conf  = int(self.params.get("min_confluence", 3))
        scaled    = bool(self.params.get("scaled_sizing", True))
        notional  = float(self.params.get("notional", 500))
        max_pos   = int(self.params.get("max_positions", 5))
        avoid_e   = bool(self.params.get("avoid_earnings", False))
        timeframe = self.params.get("timeframe", "day")

        is_crypto = (
            client is not None
            and hasattr(client, "exchange")
            and "binance" in str(getattr(client, "exchange", "")).lower()
        )

        open_positions = sum(1 for v in positions.values() if v > 0)
        days = 10 if timeframe == "hour" else 500

        for sym in self._get_symbols():
            try:
                bars = self._get_bars(client, sym, days=days)
            except Exception:
                continue

            closes = [b["c"] for b in bars]
            e8   = _ema(closes, 8)
            e13  = _ema(closes, 13)
            e48  = _ema(closes, 48)
            e200 = _ema(closes, 200)

            if any(v is None for v in (e8, e13, e48, e200)):
                continue

            price = closes[-1]
            bull_score = sum(1 for e in (e8, e13, e48, e200) if price > e)
            bear_score = sum(1 for e in (e8, e13, e48, e200) if price < e)

            held = positions.get(sym, 0.0)

            if held > 0:
                if bear_score >= min_conf or price < e48:
                    if bear_score >= min_conf:
                        below = "/".join(
                            n for n, e in [("EMA8", e8), ("EMA13", e13), ("EMA48", e48), ("EMA200", e200)]
                            if price < e
                        )
                        reason = f"4-EMA bear score {bear_score}/4: price below {below} | exit full position"
                    else:
                        reason = f"4-EMA exit: price {price:.2f} < EMA48 {e48:.2f} -- trend invalidated"
                    out.append(Signal(symbol=sym, side="sell", qty=held, reason=reason))
                continue

            if open_positions >= max_pos:
                continue

            if bull_score >= min_conf and bear_score == 0:
                if avoid_e and not is_crypto and client is not None:
                    if self._near_earnings(client, sym):
                        continue

                size = notional * _SCALE.get(bull_score, 1.0) if scaled else notional
                reason = (
                    f"4-EMA bull score {bull_score}/4: price {price:.2f} above "
                    f"EMA8 {e8:.2f}, EMA13 {e13:.2f}, EMA48 {e48:.2f}, EMA200 {e200:.2f} "
                    f"| notional ${size:.0f}"
                )
                out.append(Signal(symbol=sym, side="buy", notional=size, reason=reason))
                open_positions += 1

        return out
