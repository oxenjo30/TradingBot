from .base import Strategy, Signal
from .patterns.detectors import detect_all


def _ema(closes: list, period: int):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period
    for price in closes[period:]:
        val = price * k + val * (1 - k)
    return val


class ClassicPatterns(Strategy):
    name = "classic_patterns"
    label = "Classic Chart Patterns"
    description = (
        "Detects 21 classic patterns across candlestick, reversal, and continuation categories. "
        "Only trades patterns that align with the EMA200 trend. Position size scales with "
        "pattern confidence. Works on stocks (daily) and crypto (hourly)."
    )
    brokers = ["alpaca", "tradier", "binance"]
    default_params = {
        "symbols": [],
        "use_scanner": True,
        "timeframe": "day",
        "enable_candlestick": True,
        "enable_reversal": True,
        "enable_continuation": True,
        "min_confidence": 0.7,
        "scaled_sizing": True,
        "notional": 500,
        "ema_exit": "48",
        "max_positions": 5,
    }
    params_schema = [
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Comma-separated tickers to always include. Leave empty to use the scanner (stocks only)."},
        {"key": "use_scanner", "label": "Auto-discover Stocks", "type": "bool",
         "hint": "Add top active and gaining stocks each tick. Ignored for Binance accounts."},
        {"key": "timeframe", "label": "Timeframe", "type": "select",
         "options": ["day", "hour"],
         "hint": "Use 'day' for stocks (Alpaca) and 'hour' for crypto (Binance)."},
        {"key": "enable_candlestick", "label": "Candlestick Patterns", "type": "bool",
         "hint": "Enable 7 short-term candlestick patterns: engulfing, hammer, shooting star, morning/evening star, doji."},
        {"key": "enable_reversal", "label": "Reversal Patterns", "type": "bool",
         "hint": "Enable 7 reversal patterns: double/triple tops and bottoms, head-and-shoulders, V-bottom."},
        {"key": "enable_continuation", "label": "Continuation Patterns", "type": "bool",
         "hint": "Enable 8 continuation patterns: flags, triangles, pennant, rising/falling wedge."},
        {"key": "min_confidence", "label": "Min Pattern Confidence", "type": "select",
         "options": ["0.4", "0.7", "1.0"],
         "hint": "Minimum confidence to trade. 0.4 includes all patterns; 0.7 excludes doji/pennant/V-bottom; 1.0 only trades high-reliability reversal patterns."},
        {"key": "scaled_sizing", "label": "Scale Size by Confidence", "type": "bool",
         "hint": "When on: confidence 1.0 = 100% notional, 0.7 = 70%, 0.4 = 40%. When off, always uses the full amount."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "ai_tunable": False,
         "hint": "Max USD per trade at confidence 1.0."},
        {"key": "ema_exit", "label": "EMA Exit Period", "type": "select",
         "options": ["48", "200"],
         "hint": "EMA period used as trend exit fallback. Price dropping below this EMA exits the position."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 50,
         "ai_tunable": False,
         "hint": "Maximum simultaneous open positions."},
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

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        min_conf    = float(self.params.get("min_confidence", 0.7))
        scaled      = bool(self.params.get("scaled_sizing", True))
        notional    = float(self.params.get("notional", 500))
        ema_exit    = int(self.params.get("ema_exit", "48"))
        max_pos     = int(self.params.get("max_positions", 5))
        timeframe   = self.params.get("timeframe", "day")

        enabled_categories = [
            cat for cat, key in [
                ("candlestick",   "enable_candlestick"),
                ("reversal",      "enable_reversal"),
                ("continuation",  "enable_continuation"),
            ]
            if self.params.get(key, True)
        ]

        open_positions = sum(1 for v in positions.values() if v > 0)
        days = 10 if timeframe == "hour" else 500

        for sym in self._get_symbols():
            try:
                bars = self._get_bars(client, sym, days=days)
            except Exception:
                continue

            closes = [b["c"] for b in bars]
            e200 = _ema(closes, 200)
            if e200 is None:
                continue

            price = closes[-1]
            e_exit_val = _ema(closes, ema_exit)

            held = positions.get(sym, 0.0)

            if held > 0:
                hits = detect_all(bars, enabled_categories)
                bear_hits = [h for h in hits if h.direction == "bear"]
                if bear_hits:
                    top = max(bear_hits, key=lambda h: h.confidence)
                    reason = f"Chart exit: {top.name} -- bear pattern detected"
                    out.append(Signal(symbol=sym, side="sell", qty=held, reason=reason))
                elif e_exit_val is not None and price < e_exit_val:
                    reason = f"Chart exit: price {price:.2f} < EMA{ema_exit} {e_exit_val:.2f} -- trend invalidated"
                    out.append(Signal(symbol=sym, side="sell", qty=held, reason=reason))
                continue

            if open_positions >= max_pos:
                continue

            if price <= e200:
                continue

            hits = detect_all(bars, enabled_categories)
            bull_hits = [h for h in hits if h.direction == "bull" and h.confidence >= min_conf]
            if not bull_hits:
                continue

            top = max(bull_hits, key=lambda h: h.confidence)
            size = notional * top.confidence if scaled else notional
            reason = (
                f"Chart: {top.name} (conf {top.confidence:.0%}) | "
                f"price {price:.2f} > EMA200 {e200:.2f} | notional ${size:.0f}"
            )
            out.append(Signal(symbol=sym, side="buy", notional=size, reason=reason))
            open_positions += 1

        return out
