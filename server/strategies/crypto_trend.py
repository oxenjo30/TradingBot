import math
from typing import ClassVar
from .base import Strategy, Signal


def _ema(closes: list[float], period: int) -> list[float]:
    if len(closes) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(closes[:period]) / period]
    for price in closes[period:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


class CryptoTrend(Strategy):
    name = "crypto_trend"
    label = "Crypto EMA Trend"
    brokers: ClassVar[list[str]] = ["crypto"]
    description = (
        "Trend-following strategy for crypto pairs. Buys when the fast EMA crosses above "
        "the slow EMA (uptrend confirmed), sells when it crosses back below. "
        "Designed for BTC/USDT, ETH/USDT and other USDT pairs on Binance. "
        "Set notional (USD) per trade."
    )
    default_params = {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"],
        "fast_ema": 9,
        "slow_ema": 21,
        "notional": 500,
        "max_positions": 3,
    }
    params_schema = [
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Crypto pairs to watch (e.g. BTC/USDT, ETH/USDT). Use USDT pairs for Binance."},
        {"key": "fast_ema", "label": "Fast EMA Period (days)", "type": "number", "min": 2, "max": 50,
         "hint": "Short moving average period. A crossover above the slow EMA signals an uptrend. Default is 9."},
        {"key": "slow_ema", "label": "Slow EMA Period (days)", "type": "number", "min": 5, "max": 200,
         "hint": "Long moving average period. Default is 21. Must be greater than Fast EMA."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "ai_tunable": False,
         "hint": "Dollar amount to spend on each buy signal."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 20,
         "ai_tunable": False,
         "hint": "Maximum number of crypto pairs to hold at once."},
    ]

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        fast_n  = int(self.params.get("fast_ema", 9))
        slow_n  = int(self.params.get("slow_ema", 21))
        max_pos = int(self.params.get("max_positions", 3))
        symbols = [s.strip() for s in (self.params.get("symbols") or []) if s]

        open_positions = sum(1 for v in positions.values() if v > 0)

        for sym in symbols:
            try:
                bars = self._get_bars(client, sym, days=max(slow_n * 3, 90))
            except Exception:
                continue
            closes = [b["c"] for b in bars]

            fast_ema = _ema(closes, fast_n)
            slow_ema = _ema(closes, slow_n)

            # Need at least 2 points on each series to detect a crossover
            if len(fast_ema) < 2 or len(slow_ema) < 2:
                continue

            fast_cur, fast_prev = fast_ema[-1], fast_ema[-2]
            slow_cur, slow_prev = slow_ema[-1], slow_ema[-2]

            held = positions.get(sym, 0.0)

            if held > 0:
                if fast_prev >= slow_prev and fast_cur < slow_cur:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"EMA{fast_n} {fast_cur:.4f} crossed below EMA{slow_n} {slow_cur:.4f}"))
            else:
                if open_positions >= max_pos:
                    continue
                if fast_prev <= slow_prev and fast_cur > slow_cur:
                    out.append(self._signal(sym, "buy",
                        f"EMA{fast_n} {fast_cur:.4f} crossed above EMA{slow_n} {slow_cur:.4f}"))
                    open_positions += 1

        return out
