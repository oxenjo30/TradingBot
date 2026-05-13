from .base import Strategy, Signal
from .. import alpaca_client


def _sma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _rsi(closes, period):
    if len(closes) < period + 1:
        return None
    avg_g = avg_l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0: avg_g += d
        else:      avg_l -= d
    avg_g /= period
    avg_l /= period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + (d if d > 0 else 0)) / period
        avg_l = (avg_l * (period - 1) + (-d if d < 0 else 0)) / period
    return 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)


class MomentumBreakout(Strategy):
    name = "momentum"
    label = "Momentum Breakout"
    description = (
        "Scans most-active and top-gaining stocks. Buys when price is above SMA20 "
        "and RSI is in the momentum zone (50–70). Exits when overbought (RSI>75) "
        "or price drops below SMA20. Set notional (USD) or qty per trade."
    )
    default_params = {
        "use_scanner": True,
        "symbols": [],
        "scanner_top_actives": 25,
        "scanner_top_gainers": 15,
        "scanner_min_price": 5.0,
        "scanner_max_price": 500.0,
        "sma_period": 20,
        "rsi_period": 14,
        "rsi_min": 50,
        "rsi_max_entry": 70,
        "rsi_exit_overbought": 75,
        "notional": 500,
        "qty": None,
        "max_positions": 5,
    }
    params_schema = [
        {"key": "use_scanner", "label": "Auto-discover Stocks", "type": "bool",
         "hint": "When enabled, the strategy adds market scanner results to your symbol list, finding stocks with strong momentum automatically."},
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Optional comma-separated tickers to always include (e.g. AAPL, TSLA). Leave empty to rely entirely on the scanner."},
        {"key": "sma_period", "label": "SMA Period (days)", "type": "number", "min": 5, "max": 200,
         "hint": "The moving average window used to confirm the trend. A stock must be trading above this average to be considered for a buy."},
        {"key": "rsi_period", "label": "RSI Period (days)", "type": "number", "min": 2, "max": 100,
         "hint": "Number of days used to calculate RSI. The standard value is 14."},
        {"key": "rsi_min", "label": "RSI Entry Minimum", "type": "number", "min": 1, "max": 99,
         "hint": "RSI must be at least this value to signal a buy. Values above 50 indicate upward momentum is building."},
        {"key": "rsi_max_entry", "label": "RSI Entry Maximum", "type": "number", "min": 1, "max": 99,
         "hint": "RSI must be below this value to signal a buy. Prevents entering stocks that are already overbought."},
        {"key": "rsi_exit_overbought", "label": "RSI Exit (Overbought)", "type": "number", "min": 50, "max": 99,
         "hint": "If RSI rises above this level while holding a position, the strategy sells — the stock is considered overextended."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Dollar amount to spend on each buy signal. Example: 500 buys $500 worth of the stock."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 50,
         "hint": "Maximum number of stocks this strategy can hold at the same time. Helps manage risk and spread capital."},
    ]

    def _get_symbols(self):
        fixed = [s.upper().strip() for s in (self.params.get("symbols") or []) if s]
        if self.params.get("use_scanner", True):
            from .. import scanner
            scanned = scanner.get_scanner_universe(
                min_price=float(self.params.get("scanner_min_price", 5.0)),
                max_price=float(self.params.get("scanner_max_price", 500.0)),
                top_actives=int(self.params.get("scanner_top_actives", 25)),
                top_gainers=int(self.params.get("scanner_top_gainers", 15)),
            )
            seen = set(fixed)
            for s in scanned:
                if s not in seen:
                    fixed.append(s)
                    seen.add(s)
        return fixed

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        sma_n   = int(self.params.get("sma_period", 20))
        rsi_n   = int(self.params.get("rsi_period", 14))
        rsi_min = float(self.params.get("rsi_min", 50))
        rsi_max = float(self.params.get("rsi_max_entry", 70))
        rsi_ob  = float(self.params.get("rsi_exit_overbought", 75))
        max_pos = int(self.params.get("max_positions", 5))

        open_positions = sum(1 for v in positions.values() if v > 0)

        for sym in self._get_symbols():
            try:
                bars = self._get_bars(client, sym, days=max(sma_n * 4, 90))
            except Exception:
                continue
            closes = [b["c"] for b in bars]
            sma = _sma(closes, sma_n)
            rsi = _rsi(closes, rsi_n)
            if sma is None or rsi is None:
                continue

            price = closes[-1]
            held  = positions.get(sym, 0.0)

            if held > 0:
                if rsi > rsi_ob:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"RSI({rsi_n})={rsi:.1f} overbought>{rsi_ob}"))
                elif price < sma:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"price {price:.2f} < SMA{sma_n} {sma:.2f}"))
                continue

            if open_positions >= max_pos:
                continue
            if rsi_min <= rsi <= rsi_max and price > sma:
                out.append(self._signal(sym, "buy",
                    f"RSI({rsi_n})={rsi:.1f} momentum + price {price:.2f} > SMA{sma_n} {sma:.2f}"))
                open_positions += 1

        return out
