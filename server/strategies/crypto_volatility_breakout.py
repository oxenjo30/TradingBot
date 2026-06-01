import math
from typing import ClassVar
from .base import Strategy, Signal
from .. import db


def _bollinger(closes: list[float], period: int, num_std: float):
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((c - sma) ** 2 for c in window) / period
    std = math.sqrt(variance)
    return sma, sma + num_std * std, sma - num_std * std  # mid, upper, lower


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0  # flat prices — neither overbought nor oversold
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class CryptoVolatilityBreakout(Strategy):
    name = "crypto_volatility_breakout"
    label = "Crypto Mean Reversion"
    brokers: ClassVar[list[str]] = ["crypto"]
    description = (
        "Buys when price touches the lower Bollinger Band AND RSI is oversold (< 35) — "
        "a mean reversion entry with momentum confirmation. "
        "Sells when price returns to the middle band (SMA) for a profit, or cuts loss "
        "if price falls more than stop_pct% below entry. "
        "Designed for USDT pairs on Binance."
    )
    default_params = {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_oversold": 35,
        "stop_pct": 3.0,
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
        {"key": "rsi_period", "label": "RSI Period", "type": "number", "min": 5, "max": 30,
         "hint": "Period for RSI calculation. Standard is 14."},
        {"key": "rsi_oversold", "label": "RSI Oversold Threshold", "type": "number", "min": 20, "max": 45,
         "hint": "Buy only when RSI is below this level. Lower = more selective (stronger oversold signal)."},
        {"key": "stop_pct", "label": "Stop Loss %", "type": "number", "min": 1.0, "max": 10.0,
         "hint": "Sell if price drops this % below entry price to limit losses."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "ai_tunable": False,
         "hint": "Dollar amount to spend on each buy signal."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 20,
         "ai_tunable": False,
         "hint": "Maximum number of crypto pairs to hold at once."},
    ]

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        period     = int(self.params.get("bb_period", 20))
        num_std    = float(self.params.get("bb_std", 2.0))
        rsi_period = int(self.params.get("rsi_period", 14))
        rsi_os     = float(self.params.get("rsi_oversold", 35))
        stop_pct   = float(self.params.get("stop_pct", 3.0))
        max_pos    = int(self.params.get("max_positions", 3))
        symbols    = [s.strip() for s in (self.params.get("symbols") or []) if s]

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
                # Entry price read from open_trades — instance state is lost each tick
                entry_price = db.get_open_trade_entry_price(self.name, sym)
                stop_hit = entry_price and price < entry_price * (1 - stop_pct / 100)
                if price >= mid:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"mean reversion complete: price {price:.4f} >= SMA{period} {mid:.4f}"))
                elif stop_hit:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"stop loss: price {price:.4f} < entry {entry_price:.4f} - {stop_pct}%"))
            else:
                if open_positions >= max_pos:
                    continue
                rsi = _rsi(closes, rsi_period)
                # Buy: price at/below lower band AND RSI oversold = high-probability mean reversion.
                # Guard: skip if we already hold this symbol via open_trades (any strategy),
                # so we don't pyramid into the same coin when the signal persists for many ticks.
                already_open = db.count_open_trades_for_symbol(sym)
                if price <= lower and rsi is not None and rsi < rsi_os and already_open == 0:
                    out.append(self._signal(sym, "buy",
                        f"lower band touch {price:.4f} <= {lower:.4f}, RSI={rsi:.1f} < {rsi_os}"))
                    open_positions += 1

        return out
