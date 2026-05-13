"""
Golden Cross / Death Cross  (SMA 50 / SMA 200)
- Classic long-term trend-following strategy used by institutional traders
- Golden Cross: SMA50 crosses above SMA200 → strong uptrend signal → BUY
- Death Cross:  SMA50 crosses below SMA200 → downtrend confirmed → SELL
- Slower, fewer signals, but high-conviction — best for long-term positions
- Backtested CAGR on SPY: ~7–10% but with significantly lower drawdowns than buy-and-hold
"""
from .base import Strategy, Signal
from .. import alpaca_client


class GoldenCross(Strategy):
    name = "golden_cross"
    label = "Golden Cross (SMA 50/200)"
    description = (
        "Classic institutional strategy: buys when SMA50 crosses above SMA200 "
        "(Golden Cross) and sells when it crosses below (Death Cross). "
        "Long-term, high-conviction signals — few trades but strong trend confirmation. "
        "Set notional or qty per trade."
    )
    default_params = {
        "symbols": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"],
        "use_scanner": False,
        "scanner_top_actives": 20,
        "scanner_min_price": 10.0,
        "scanner_max_price": 1000.0,
        "fast": 50,
        "slow": 200,
        "notional": 1000,   # larger notional — long-term holds
        "qty": None,
    }
    params_schema = [
        {"key": "use_scanner", "label": "Auto-discover Stocks", "type": "bool",
         "hint": "When enabled, replaces the symbol list with the most actively traded stocks from the market scanner. Because this is a long-term strategy, a fixed list is usually preferred."},
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Comma-separated ticker symbols to watch (e.g. SPY, QQQ, AAPL). This strategy works best on large, liquid stocks with long price histories."},
        {"key": "fast", "label": "Fast SMA Period (days)", "type": "number", "min": 10, "max": 300,
         "hint": "The shorter moving average. The classic Golden Cross uses 50 days. When this crosses above the slow SMA, a buy signal is generated."},
        {"key": "slow", "label": "Slow SMA Period (days)", "type": "number", "min": 20, "max": 500,
         "hint": "The longer moving average. The classic Golden Cross uses 200 days. Must be larger than the fast period. This line represents the long-term trend."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Dollar amount to spend on each buy signal. Because this strategy holds positions for weeks or months, a larger amount is common (e.g. $1000)."},
    ]

    def _get_symbols(self):
        if self.params.get("use_scanner"):
            from .. import scanner
            return scanner.get_most_actives(
                top_n=int(self.params.get("scanner_top_actives", 20)),
                min_price=float(self.params.get("scanner_min_price", 10.0)),
                max_price=float(self.params.get("scanner_max_price", 1000.0)),
            )
        return [s.upper().strip() for s in (self.params.get("symbols") or []) if s]

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        fast = int(self.params.get("fast", 50))
        slow = int(self.params.get("slow", 200))

        for sym in self._get_symbols():
            try:
                # need 200 + a few extra days of history
                bars = self._get_bars(client, sym, days=slow + 30)
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

            golden = fast_prev <= slow_prev and fast_now > slow_now   # crossover up
            death  = fast_prev >= slow_prev and fast_now < slow_now   # crossover down
            held   = positions.get(sym, 0.0)

            if golden and held <= 0:
                out.append(self._signal(sym, "buy",
                    f"Golden Cross: SMA{fast}={fast_now:.2f} crossed above SMA{slow}={slow_now:.2f}"))
            elif death and held > 0:
                out.append(Signal(symbol=sym, side="sell", qty=held,
                    reason=f"Death Cross: SMA{fast}={fast_now:.2f} crossed below SMA{slow}={slow_now:.2f}"))
        return out
