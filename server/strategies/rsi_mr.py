from .base import Strategy, Signal
from .. import alpaca_client


def _rsi(closes: list[float], period: int) -> float | None:
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


class RSIMeanReversion(Strategy):
    name = "rsi_mr"
    label = "RSI Mean Reversion"
    description = (
        "Buys when RSI dips below oversold, exits when RSI rises above exit threshold. "
        "Set notional (USD) to trade by dollar amount, or qty for fixed shares. "
        "Enable use_scanner to screen the broader market automatically."
    )
    default_params = {
        "symbols": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"],
        "use_scanner": False,
        "scanner_top_actives": 20,
        "scanner_top_gainers": 10,
        "scanner_min_price": 5.0,
        "scanner_max_price": 1000.0,
        "period": 14,
        "oversold": 30,
        "exit": 55,
        "notional": 500,
        "qty": None,
    }
    params_schema = [
        {"key": "use_scanner", "label": "Auto-discover Stocks", "type": "bool",
         "hint": "When enabled, the strategy ignores the symbol list and scans the market for the most-active and top-gaining stocks automatically."},
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Comma-separated ticker symbols to watch when Auto-discover is off (e.g. SPY, QQQ, AAPL)."},
        {"key": "period", "label": "RSI Period (days)", "type": "number", "min": 2, "max": 100,
         "hint": "Number of days used to calculate RSI (Relative Strength Index). The standard value is 14. Shorter periods are more sensitive."},
        {"key": "oversold", "label": "Oversold Threshold", "type": "number", "min": 1, "max": 50,
         "hint": "RSI level below which a stock is considered oversold and a buy signal is triggered. Common values: 30 (standard) or 25 (more selective)."},
        {"key": "exit", "label": "Exit RSI Level", "type": "number", "min": 40, "max": 99,
         "hint": "RSI level above which the strategy sells the position. The stock has recovered enough — time to take profit."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "ai_tunable": False,
         "hint": "Dollar amount to spend on each buy signal. Example: 500 buys $500 worth of the stock."},
        {"key": "qty", "label": "Shares per Trade", "type": "number", "min": 1, "max": 10000,
         "ai_tunable": False,
         "hint": "Fixed number of shares to buy per signal. If you set a dollar amount above, leave this blank."},
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
        period   = int(self.params.get("period", 14))
        oversold = float(self.params.get("oversold", 30))
        exit_lvl = float(self.params.get("exit", 55))

        for sym in self._get_symbols():
            try:
                bars = self._get_bars(client, sym, days=max(period * 4, 60))
            except Exception:
                continue
            closes = [b["c"] for b in bars]
            rsi = _rsi(closes, period)
            if rsi is None:
                continue
            held = positions.get(sym, 0.0)

            if rsi < oversold and held <= 0:
                out.append(self._signal(sym, "buy",
                    f"RSI({period})={rsi:.1f} < {oversold}"))
            elif rsi > exit_lvl and held > 0:
                out.append(Signal(symbol=sym, side="sell", qty=held,
                    reason=f"RSI({period})={rsi:.1f} > {exit_lvl}"))
        return out
