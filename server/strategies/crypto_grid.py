from typing import ClassVar
from .base import Strategy, Signal


def _sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


class CryptoGrid(Strategy):
    name = "crypto_grid"
    label = "Crypto Grid Trading"
    brokers: ClassVar[list[str]] = ["binance"]
    description = (
        "Grid trading strategy that buys near band lows and sells near band highs. "
        "Adds a trend filter: only buys when price is above the long-term SMA (uptrend), "
        "avoiding entries in a downtrend. Set grid_lower/grid_upper to define the range, "
        "or leave both at 0 to auto-detect from recent price history. "
        "Designed for USDT pairs on Binance."
    )
    default_params = {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "grid_lower": 0.0,
        "grid_upper": 0.0,
        "grid_levels": 5,
        "lookback_days": 14,
        "trend_sma": 50,
        "notional": 500,
        "max_positions": 3,
    }
    params_schema = [
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Crypto pairs to watch (e.g. BTC/USDT, ETH/USDT). Use USDT pairs for Binance."},
        {"key": "grid_lower", "label": "Grid Lower Bound (USD)", "type": "number", "min": 0,
         "hint": "Lowest price of the grid range. Set to 0 to auto-detect from recent price history."},
        {"key": "grid_upper", "label": "Grid Upper Bound (USD)", "type": "number", "min": 0,
         "hint": "Highest price of the grid range. Set to 0 to auto-detect from recent price history."},
        {"key": "grid_levels", "label": "Grid Lines", "type": "number", "min": 2, "max": 20,
         "hint": "Number of grid lines (bands). More lines = more frequent trades, smaller profit per trade."},
        {"key": "lookback_days", "label": "Auto-Range Lookback (days)", "type": "number", "min": 7, "max": 30,
         "hint": "When bounds are 0, uses the high/low over this many days. Shorter = tighter, more relevant range."},
        {"key": "trend_sma", "label": "Trend Filter SMA (days)", "type": "number", "min": 20, "max": 200,
         "hint": "Only buy when price is above this SMA (uptrend filter). Set to 0 to disable."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Dollar amount to spend on each buy signal."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 20,
         "hint": "Maximum number of crypto pairs to hold at once."},
    ]

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        grid_lower  = float(self.params.get("grid_lower", 0.0))
        grid_upper  = float(self.params.get("grid_upper", 0.0))
        grid_levels = int(self.params.get("grid_levels", 5))
        lookback    = int(self.params.get("lookback_days", 14))
        trend_sma   = int(self.params.get("trend_sma", 50))
        max_pos     = int(self.params.get("max_positions", 3))
        symbols     = [s.strip() for s in (self.params.get("symbols") or []) if s]

        open_positions = sum(1 for v in positions.values() if v > 0)

        for sym in symbols:
            try:
                bars = self._get_bars(client, sym, days=max(trend_sma * 2, lookback * 3, 120))
            except Exception:
                continue
            closes = [b["c"] for b in bars]
            if not closes:
                continue

            price = closes[-1]

            # Trend filter: skip buys in downtrend
            if trend_sma > 0:
                sma = _sma(closes, trend_sma)
                if sma and price < sma:
                    # In downtrend — exit any held position immediately, no new buys
                    held = positions.get(sym, 0.0)
                    if held > 0:
                        out.append(Signal(symbol=sym, side="sell", qty=held,
                            reason=f"downtrend exit: price {price:.4f} < SMA{trend_sma} {sma:.4f}"))
                    continue

            # Auto-detect range from recent lookback bars when bounds not set
            lower = grid_lower
            upper = grid_upper
            if lower == 0.0 or upper == 0.0:
                recent = closes[-lookback:] if len(closes) >= lookback else closes
                lower = min(recent)
                upper = max(recent)

            if upper <= lower or grid_levels < 2:
                continue

            band_width = (upper - lower) / grid_levels
            band_idx   = int((price - lower) / band_width)
            band_idx   = max(0, min(band_idx, grid_levels - 1))

            band_low  = lower + band_idx * band_width
            band_high = band_low + band_width
            # Use upper 40% of band as sell zone (not just midpoint) to give more room
            sell_trigger = band_low + band_width * 0.6

            held = positions.get(sym, 0.0)

            if held > 0:
                # Sell when price reaches upper 40% of its band or exits grid top
                if price >= sell_trigger or price >= upper:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"grid sell: price {price:.4f} >= sell zone "
                               f"{sell_trigger:.4f} "
                               f"(grid {lower:.2f}-{upper:.2f}, {grid_levels} levels)"))
            else:
                if open_positions >= max_pos:
                    continue
                # Buy only in the bottom 30% of a band (tighter entry = better fill)
                buy_limit = band_low + band_width * 0.3
                if lower <= price <= buy_limit:
                    out.append(self._signal(sym, "buy",
                        f"grid buy: price {price:.4f} in bottom zone "
                        f"[{band_low:.4f}-{buy_limit:.4f}] "
                        f"(grid {lower:.2f}-{upper:.2f}, {grid_levels} levels)"))
                    open_positions += 1

        return out
