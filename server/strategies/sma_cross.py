from .base import Strategy, Signal
from .. import alpaca_client


class SMACrossover(Strategy):
    name = "sma_cross"
    label = "SMA Crossover"
    description = (
        "Buys when the fast SMA crosses above the slow SMA, sells when it crosses below. "
        "Set notional (USD) to trade by dollar amount, or qty for fixed shares. "
        "Enable use_scanner to auto-discover high-volume stocks."
    )
    default_params = {
        "symbols": ["SPY", "AAPL", "MSFT", "NVDA", "AMZN"],
        "use_scanner": False,
        "scanner_top_actives": 20,
        "scanner_top_gainers": 10,
        "scanner_min_price": 5.0,
        "scanner_max_price": 1000.0,
        "fast": 10,
        "slow": 30,
        "notional": 500,
        "qty": None,
    }
    params_schema = [
        {"key": "use_scanner", "label": "Auto-discover Stocks", "type": "bool",
         "hint": "When enabled, the strategy ignores the symbol list below and instead pulls the most-active and top-gaining stocks from the market each time it runs."},
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Comma-separated ticker symbols to watch when Auto-discover is off (e.g. SPY, AAPL, MSFT)."},
        {"key": "fast", "label": "Fast SMA Period (days)", "type": "number", "min": 2, "max": 100,
         "hint": "Number of days used to calculate the fast moving average. A shorter period reacts more quickly to price changes."},
        {"key": "slow", "label": "Slow SMA Period (days)", "type": "number", "min": 5, "max": 500,
         "hint": "Number of days used to calculate the slow moving average. Must be larger than the fast period. A crossover between the two lines triggers a trade."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Dollar amount to spend on each buy signal. Leave qty blank to use this. Example: 500 buys $500 worth of the stock."},
        {"key": "qty", "label": "Shares per Trade", "type": "number", "min": 1, "max": 10000,
         "hint": "Fixed number of shares to buy per signal. If you set a dollar amount above, leave this blank."},
        {"key": "scanner_top_actives", "label": "Scanner: Top Actives", "type": "number", "min": 1, "max": 100,
         "hint": "How many of the most-traded (highest volume) stocks to pull from the market scanner. Only used when Auto-discover is on."},
        {"key": "scanner_top_gainers", "label": "Scanner: Top Gainers", "type": "number", "min": 1, "max": 100,
         "hint": "How many of the biggest daily price-gainers to pull from the market scanner. Only used when Auto-discover is on."},
        {"key": "scanner_min_price", "label": "Scanner: Min Price ($)", "type": "number", "min": 0.01, "max": 10000,
         "hint": "Ignore stocks trading below this price. Helps filter out very cheap or volatile penny stocks."},
        {"key": "scanner_max_price", "label": "Scanner: Max Price ($)", "type": "number", "min": 1, "max": 100000,
         "hint": "Ignore stocks trading above this price. Useful to stay within a comfortable price range."},
    ]

    def _get_symbols(self) -> list[str]:
        if self.params.get("use_scanner"):
            from .. import scanner
            return scanner.get_scanner_universe(
                min_price=float(self.params.get("scanner_min_price", 5.0)),
                max_price=float(self.params.get("scanner_max_price", 1000.0)),
                top_actives=int(self.params.get("scanner_top_actives", 20)),
                top_gainers=int(self.params.get("scanner_top_gainers", 10)),
            )
        return [s.upper().strip() for s in (self.params.get("symbols") or []) if s]

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        fast = int(self.params.get("fast", 10))
        slow = int(self.params.get("slow", 30))

        for sym in self._get_symbols():
            try:
                bars = self._get_bars(client, sym, days=max(slow * 3, 90))
            except Exception:
                continue
            closes = [b["c"] for b in bars]
            if len(closes) < slow + 2:
                continue

            def sma(values, n, offset=0):
                window = values[-(n + offset): len(values) - offset or None] if offset else values[-n:]
                return sum(window) / n if len(window) >= n else None

            fast_now  = sma(closes, fast)
            slow_now  = sma(closes, slow)
            fast_prev = sma(closes, fast, offset=1)
            slow_prev = sma(closes, slow, offset=1)

            if any(v is None for v in (fast_now, slow_now, fast_prev, slow_prev)):
                continue

            crossed_up = fast_prev <= slow_prev and fast_now > slow_now
            crossed_dn = fast_prev >= slow_prev and fast_now < slow_now
            held = positions.get(sym, 0.0)

            if crossed_up and held <= 0:
                out.append(self._signal(sym, "buy",
                    f"SMA{fast}={fast_now:.2f} crossed above SMA{slow}={slow_now:.2f}"))
            elif crossed_dn and held > 0:
                # sell full held position
                out.append(Signal(symbol=sym, side="sell", qty=held,
                    reason=f"SMA{fast}={fast_now:.2f} crossed below SMA{slow}={slow_now:.2f}"))
        return out
