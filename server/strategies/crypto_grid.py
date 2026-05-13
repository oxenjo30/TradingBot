from .base import Strategy, Signal


class CryptoGrid(Strategy):
    name = "crypto_grid"
    label = "Crypto Grid Trading"
    description = (
        "Replicates Binance's grid trading strategy. Divides a price range into equal bands "
        "and buys when price is in the lower portion of a band, sells when it reaches the upper "
        "portion — profiting from price oscillation. Set grid_lower and grid_upper to define the "
        "range, or leave both at 0 to auto-detect from recent price history (like Binance's AI range). "
        "Designed for USDT pairs on Binance."
    )
    default_params = {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "grid_lower": 0.0,
        "grid_upper": 0.0,
        "grid_levels": 5,
        "lookback_days": 30,
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
        {"key": "lookback_days", "label": "Auto-Range Lookback (days)", "type": "number", "min": 7, "max": 90,
         "hint": "When bounds are 0, uses the highest and lowest price over this many days to set the grid. Like Binance's AI range."},
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
        lookback    = int(self.params.get("lookback_days", 30))
        max_pos     = int(self.params.get("max_positions", 3))
        symbols     = [s.strip() for s in (self.params.get("symbols") or []) if s]

        open_positions = sum(1 for v in positions.values() if v > 0)

        for sym in symbols:
            try:
                bars = self._get_bars(client, sym, days=max(lookback * 2, 60))
            except Exception:
                continue
            closes = [b["c"] for b in bars]
            if not closes:
                continue

            price = closes[-1]

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
            band_mid  = (band_low + band_high) / 2

            held = positions.get(sym, 0.0)

            if held > 0:
                # Sell when price reaches the upper half of its band or exits grid top
                if price >= band_mid or price >= upper:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"grid sell: price {price:.4f} in upper zone "
                               f"[{band_mid:.4f}–{band_high:.4f}] "
                               f"(grid {lower:.2f}–{upper:.2f}, {grid_levels} levels)"))
            else:
                if open_positions >= max_pos:
                    continue
                # Buy when price is in the lower half of its band and within grid range
                if lower <= price < band_mid:
                    out.append(self._signal(sym, "buy",
                        f"grid buy: price {price:.4f} in lower zone "
                        f"[{band_low:.4f}–{band_mid:.4f}] "
                        f"(grid {lower:.2f}–{upper:.2f}, {grid_levels} levels)"))
                    open_positions += 1

        return out
