import math
from typing import ClassVar
from .base import Strategy, Signal


def _bollinger(closes: list[float], period: int, num_std: float):
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((c - sma) ** 2 for c in window) / period
    std = math.sqrt(variance)
    return sma, sma + num_std * std, sma - num_std * std  # mid, upper, lower


class CryptoVolatilityBreakout(Strategy):
    name = "crypto_volatility_breakout"
    label = "Crypto Volatility Breakout"
    brokers: ClassVar[list[str]] = ["binance"]
    description = (
        "Buys when price closes above the upper Bollinger Band — a momentum breakout signal. "
        "Sells when price drops back below the middle band (SMA), locking in gains early. "
        "Band width defaults to 2.0 std deviations, wider to handle crypto's natural volatility. "
        "Designed for USDT pairs on Binance."
    )
    default_params = {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"],
        "bb_period": 20,
        "bb_std": 2.0,
        "notional": 500,
        "max_positions": 3,
    }
    params_schema = [
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Crypto pairs to watch (e.g. BTC/USDT, ETH/USDT). Use USDT pairs for Binance."},
        {"key": "bb_period", "label": "Bollinger Band Period (days)", "type": "number", "min": 5, "max": 100,
         "hint": "Number of bars for the Bollinger Band calculation. Standard is 20."},
        {"key": "bb_std", "label": "Band Width (Std Deviations)", "type": "number", "min": 0.5, "max": 4.0,
         "hint": "Width of the bands in standard deviations. 2.0 is standard. Higher = fewer but stronger signals."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Dollar amount to spend on each buy signal."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 20,
         "hint": "Maximum number of crypto pairs to hold at once."},
    ]

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        period  = int(self.params.get("bb_period", 20))
        num_std = float(self.params.get("bb_std", 2.0))
        max_pos = int(self.params.get("max_positions", 3))
        symbols = [s.strip() for s in (self.params.get("symbols") or []) if s]

        open_positions = sum(1 for v in positions.values() if v > 0)

        for sym in symbols:
            try:
                bars = self._get_bars(client, sym, days=max(period * 4, 90))
            except Exception:
                continue
            closes = [b["c"] for b in bars]
            mid, upper, lower = _bollinger(closes, period, num_std)
            if mid is None:
                continue

            price = closes[-1]
            held  = positions.get(sym, 0.0)

            if held > 0:
                if price < mid:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"price {price:.4f} < SMA{period} {mid:.4f} - exit breakout"))
            else:
                if open_positions >= max_pos:
                    continue
                if price > upper:
                    out.append(self._signal(sym, "buy",
                        f"price {price:.4f} > upper band {upper:.4f} (BB{period} +/-{num_std}std)"))
                    open_positions += 1

        return out
