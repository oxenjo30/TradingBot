from .base import Strategy, Signal


def _rsi(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    avg_g = avg_l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            avg_g += d
        else:
            avg_l -= d
    avg_g /= period
    avg_l /= period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + (d if d > 0 else 0)) / period
        avg_l = (avg_l * (period - 1) + (-d if d < 0 else 0)) / period
    return 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)


class CryptoRSIBounce(Strategy):
    name = "crypto_rsi_bounce"
    label = "Crypto RSI Bounce"
    description = (
        "Mean-reversion strategy for crypto. Buys when RSI bounces back above the oversold "
        "level (confirms the bottom, not just the dip). Sells when RSI reaches overbought. "
        "Tuned with tighter thresholds (35/65) for crypto's faster swings vs stocks (30/70). "
        "Designed for USDT pairs on Binance."
    )
    default_params = {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"],
        "rsi_period": 14,
        "rsi_oversold": 35,
        "rsi_overbought": 65,
        "notional": 500,
        "max_positions": 3,
    }
    params_schema = [
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Crypto pairs to watch (e.g. BTC/USDT, ETH/USDT). Use USDT pairs for Binance."},
        {"key": "rsi_period", "label": "RSI Period (days)", "type": "number", "min": 2, "max": 50,
         "hint": "Number of bars used to calculate RSI. Standard is 14."},
        {"key": "rsi_oversold", "label": "RSI Oversold Entry", "type": "number", "min": 10, "max": 49,
         "hint": "RSI must drop below this level then bounce above it to trigger a buy. Default 35 (tighter than stock's 30)."},
        {"key": "rsi_overbought", "label": "RSI Overbought Exit", "type": "number", "min": 51, "max": 90,
         "hint": "RSI above this level while holding triggers a sell. Default 65 (tighter than stock's 70)."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Dollar amount to spend on each buy signal."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 20,
         "hint": "Maximum number of crypto pairs to hold at once."},
    ]

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        rsi_n   = int(self.params.get("rsi_period", 14))
        rsi_os  = float(self.params.get("rsi_oversold", 35))
        rsi_ob  = float(self.params.get("rsi_overbought", 65))
        max_pos = int(self.params.get("max_positions", 3))
        symbols = [s.strip() for s in (self.params.get("symbols") or []) if s]

        open_positions = sum(1 for v in positions.values() if v > 0)

        for sym in symbols:
            try:
                bars = self._get_bars(client, sym, days=max(rsi_n * 5, 90))
            except Exception:
                continue
            closes = [b["c"] for b in bars]

            if len(closes) < rsi_n + 2:
                continue

            rsi_cur  = _rsi(closes, rsi_n)
            rsi_prev = _rsi(closes[:-1], rsi_n)

            if rsi_cur is None or rsi_prev is None:
                continue

            held = positions.get(sym, 0.0)

            if held > 0:
                if rsi_cur > rsi_ob:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"RSI({rsi_n})={rsi_cur:.1f} overbought > {rsi_ob}"))
            else:
                if open_positions >= max_pos:
                    continue
                # Bounce confirmed: RSI was below oversold, now recovered above it
                if rsi_prev < rsi_os and rsi_cur >= rsi_os:
                    out.append(self._signal(sym, "buy",
                        f"RSI({rsi_n}) bounced {rsi_prev:.1f}→{rsi_cur:.1f} above oversold {rsi_os}"))
                    open_positions += 1

        return out
