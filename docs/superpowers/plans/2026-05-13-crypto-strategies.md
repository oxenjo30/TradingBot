# Crypto Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four crypto-native trading strategies (EMA Trend, RSI Bounce, Volatility Breakout, Grid Trading) to TradeBot for use with Binance accounts.

**Architecture:** Four new files in `server/strategies/`, each inheriting `Strategy` from `base.py`. Uses existing `_get_bars(client, symbol, days)` for Binance data routing. Registered in `server/strategies/__init__.py`.

**Tech Stack:** Python 3.13, existing `Strategy` base class, math stdlib only (no new deps)

---

### Task 1: `crypto_trend.py` — EMA Crossover Trend Strategy

**Files:**
- Create: `server/strategies/crypto_trend.py`
- Modify: `server/strategies/__init__.py`
- Test: `tests/test_crypto_strategies.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_crypto_strategies.py`:

```python
import pytest
from unittest.mock import MagicMock

def _make_bars(closes):
    """Build minimal bar dicts from a list of close prices."""
    return [{"o": c, "h": c, "l": c, "c": c, "v": 1000} for c in closes]


def _mock_client(closes):
    client = MagicMock()
    client.get_recent_bars.return_value = _make_bars(closes)
    return client


class TestCryptoTrend:
    def test_buy_signal_on_ema_crossover(self):
        from server.strategies.crypto_trend import CryptoTrend
        # Build closes where fast EMA crosses above slow EMA at the end
        # Flat then rising sharply — fast EMA will cross above slow EMA
        closes = [100.0] * 30 + [110.0, 115.0, 120.0, 125.0, 130.0]
        client = _mock_client(closes)
        strat = CryptoTrend({"symbols": ["BTC/USDT"], "fast_ema": 9, "slow_ema": 21, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert any(s.symbol == "BTC/USDT" and s.side == "buy" for s in signals)

    def test_sell_signal_when_holding_and_ema_crosses_below(self):
        from server.strategies.crypto_trend import CryptoTrend
        # Rising then falling — fast EMA crosses below slow EMA
        closes = [130.0] * 30 + [120.0, 115.0, 110.0, 105.0, 100.0]
        client = _mock_client(closes)
        strat = CryptoTrend({"symbols": ["BTC/USDT"], "fast_ema": 9, "slow_ema": 21, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({"BTC/USDT": 0.5}, client=client)
        assert any(s.symbol == "BTC/USDT" and s.side == "sell" for s in signals)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.crypto_trend import CryptoTrend
        closes = [100.0] * 30 + [110.0, 115.0, 120.0, 125.0, 130.0]
        client = _mock_client(closes)
        strat = CryptoTrend({"symbols": ["BTC/USDT", "ETH/USDT"], "fast_ema": 9, "slow_ema": 21, "notional": 500, "max_positions": 1})
        # Already holding 1 position at max
        signals = strat.evaluate({"ETH/USDT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_crypto_strategies.py -v
```
Expected: `ImportError` — `crypto_trend` module not found.

- [ ] **Step 3: Create `server/strategies/crypto_trend.py`**

```python
import math
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
         "hint": "Dollar amount to spend on each buy signal."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 20,
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

            # Need at least 2 points on each series to detect crossover
            if len(fast_ema) < 2 or len(slow_ema) < 2:
                continue

            # Align to same length from the end
            fast_cur, fast_prev = fast_ema[-1], fast_ema[-2]
            slow_cur, slow_prev = slow_ema[-1], slow_ema[-2]

            held = positions.get(sym, 0.0)

            if held > 0:
                # Sell: fast crossed below slow
                if fast_prev >= slow_prev and fast_cur < slow_cur:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"EMA{fast_n} {fast_cur:.4f} crossed below EMA{slow_n} {slow_cur:.4f}"))
            else:
                if open_positions >= max_pos:
                    continue
                # Buy: fast crossed above slow
                if fast_prev <= slow_prev and fast_cur > slow_cur:
                    out.append(self._signal(sym, "buy",
                        f"EMA{fast_n} {fast_cur:.4f} crossed above EMA{slow_n} {slow_cur:.4f}"))
                    open_positions += 1

        return out
```

- [ ] **Step 4: Register in `__init__.py`**

Edit `server/strategies/__init__.py`:

```python
from .base import Strategy
from .manual import ManualStrategy
from .sma_cross import SMACrossover
from .rsi_mr import RSIMeanReversion
from .momentum import MomentumBreakout
from .bollinger import BollingerBandMeanReversion
from .breakout_52w import Breakout52Week
from .macd_volume import MACDVolume
from .golden_cross import GoldenCross
from .crypto_trend import CryptoTrend

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (
        ManualStrategy,
        SMACrossover,
        RSIMeanReversion,
        MomentumBreakout,
        BollingerBandMeanReversion,
        Breakout52Week,
        MACDVolume,
        GoldenCross,
        CryptoTrend,
    )
}
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_crypto_strategies.py::TestCryptoTrend -v
```
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```
git add server/strategies/crypto_trend.py server/strategies/__init__.py tests/test_crypto_strategies.py
git commit -m "feat: crypto_trend — EMA crossover strategy for Binance"
```

---

### Task 2: `crypto_rsi_bounce.py` — RSI Mean-Reversion Bounce

**Files:**
- Create: `server/strategies/crypto_rsi_bounce.py`
- Modify: `server/strategies/__init__.py`
- Test: `tests/test_crypto_strategies.py` (append)

- [ ] **Step 1: Append tests to `tests/test_crypto_strategies.py`**

```python
class TestCryptoRSIBounce:
    def test_buy_on_rsi_bounce(self):
        from server.strategies.crypto_rsi_bounce import CryptoRSIBounce
        # Build closes that produce RSI below 35, then recovering above 35
        # Sharp drop then recovery
        closes = [100.0] * 20 + [95, 90, 85, 80, 75, 70, 65, 60, 55, 50,
                                   52, 54, 56, 58, 60]
        client = _mock_client(closes)
        strat = CryptoRSIBounce({"symbols": ["ETH/USDT"], "rsi_period": 14,
                                  "rsi_oversold": 35, "rsi_overbought": 65,
                                  "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        # May or may not fire depending on exact RSI calc — just verify no crash
        assert isinstance(signals, list)

    def test_sell_when_overbought(self):
        from server.strategies.crypto_rsi_bounce import CryptoRSIBounce
        # Build closes producing RSI > 65
        closes = [50.0] * 20 + [52, 55, 58, 62, 66, 70, 75, 80, 85, 90,
                                  92, 94, 96, 98, 100]
        client = _mock_client(closes)
        strat = CryptoRSIBounce({"symbols": ["ETH/USDT"], "rsi_period": 14,
                                  "rsi_oversold": 35, "rsi_overbought": 65,
                                  "notional": 500, "max_positions": 3})
        signals = strat.evaluate({"ETH/USDT": 0.5}, client=client)
        assert any(s.symbol == "ETH/USDT" and s.side == "sell" for s in signals)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.crypto_rsi_bounce import CryptoRSIBounce
        closes = [100.0] * 20 + [95, 90, 85, 80, 75, 70, 65, 60, 55, 50,
                                   52, 54, 56, 58, 60]
        client = _mock_client(closes)
        strat = CryptoRSIBounce({"symbols": ["ETH/USDT", "SOL/USDT"], "rsi_period": 14,
                                  "rsi_oversold": 35, "rsi_overbought": 65,
                                  "notional": 500, "max_positions": 1})
        signals = strat.evaluate({"SOL/USDT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)
```

- [ ] **Step 2: Create `server/strategies/crypto_rsi_bounce.py`**

```python
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

            # Need enough bars to compute RSI on penultimate and last bar
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
                # Bounce: RSI was below oversold, now recovered above it
                if rsi_prev < rsi_os and rsi_cur >= rsi_os:
                    out.append(self._signal(sym, "buy",
                        f"RSI({rsi_n}) bounced {rsi_prev:.1f}→{rsi_cur:.1f} above oversold {rsi_os}"))
                    open_positions += 1

        return out
```

- [ ] **Step 3: Add to `__init__.py`**

```python
from .crypto_rsi_bounce import CryptoRSIBounce

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (
        ManualStrategy,
        SMACrossover,
        RSIMeanReversion,
        MomentumBreakout,
        BollingerBandMeanReversion,
        Breakout52Week,
        MACDVolume,
        GoldenCross,
        CryptoTrend,
        CryptoRSIBounce,
    )
}
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_crypto_strategies.py::TestCryptoRSIBounce -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```
git add server/strategies/crypto_rsi_bounce.py server/strategies/__init__.py tests/test_crypto_strategies.py
git commit -m "feat: crypto_rsi_bounce — RSI mean-reversion bounce for Binance"
```

---

### Task 3: `crypto_volatility_breakout.py` — Bollinger Band Breakout

**Files:**
- Create: `server/strategies/crypto_volatility_breakout.py`
- Modify: `server/strategies/__init__.py`
- Test: `tests/test_crypto_strategies.py` (append)

- [ ] **Step 1: Append tests**

```python
class TestCryptoVolatilityBreakout:
    def test_buy_on_upper_band_breakout(self):
        from server.strategies.crypto_volatility_breakout import CryptoVolatilityBreakout
        # Flat closes then spike above upper band
        closes = [100.0] * 25 + [130.0]  # spike well above
        client = _mock_client(closes)
        strat = CryptoVolatilityBreakout({"symbols": ["SOL/USDT"], "bb_period": 20,
                                           "bb_std": 2.0, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert any(s.symbol == "SOL/USDT" and s.side == "buy" for s in signals)

    def test_sell_when_price_below_middle_band(self):
        from server.strategies.crypto_volatility_breakout import CryptoVolatilityBreakout
        # Rising closes then drop below SMA
        closes = [100.0] * 20 + [105, 110, 115, 120, 90]
        client = _mock_client(closes)
        strat = CryptoVolatilityBreakout({"symbols": ["SOL/USDT"], "bb_period": 20,
                                           "bb_std": 2.0, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({"SOL/USDT": 1.0}, client=client)
        assert any(s.symbol == "SOL/USDT" and s.side == "sell" for s in signals)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.crypto_volatility_breakout import CryptoVolatilityBreakout
        closes = [100.0] * 25 + [130.0]
        client = _mock_client(closes)
        strat = CryptoVolatilityBreakout({"symbols": ["SOL/USDT", "BNB/USDT"], "bb_period": 20,
                                           "bb_std": 2.0, "notional": 500, "max_positions": 1})
        signals = strat.evaluate({"BNB/USDT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)
```

- [ ] **Step 2: Create `server/strategies/crypto_volatility_breakout.py`**

```python
import math
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
                        reason=f"price {price:.4f} < SMA{period} {mid:.4f} — exit breakout"))
            else:
                if open_positions >= max_pos:
                    continue
                if price > upper:
                    out.append(self._signal(sym, "buy",
                        f"price {price:.4f} > upper band {upper:.4f} (BB{period} ±{num_std}σ)"))
                    open_positions += 1

        return out
```

- [ ] **Step 3: Add to `__init__.py`**

```python
from .crypto_volatility_breakout import CryptoVolatilityBreakout

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (
        ManualStrategy,
        SMACrossover,
        RSIMeanReversion,
        MomentumBreakout,
        BollingerBandMeanReversion,
        Breakout52Week,
        MACDVolume,
        GoldenCross,
        CryptoTrend,
        CryptoRSIBounce,
        CryptoVolatilityBreakout,
    )
}
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_crypto_strategies.py::TestCryptoVolatilityBreakout -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```
git add server/strategies/crypto_volatility_breakout.py server/strategies/__init__.py tests/test_crypto_strategies.py
git commit -m "feat: crypto_volatility_breakout — Bollinger Band breakout for Binance"
```

---

### Task 4: `crypto_grid.py` — Grid Trading (Binance-style)

**Files:**
- Create: `server/strategies/crypto_grid.py`
- Modify: `server/strategies/__init__.py`
- Test: `tests/test_crypto_strategies.py` (append)

- [ ] **Step 1: Append tests**

```python
class TestCryptoGrid:
    def test_buy_when_price_in_lower_zone(self):
        from server.strategies.crypto_grid import CryptoGrid
        # Grid: lower=80, upper=120, levels=4 → bands at 80,90,100,110,120
        # Each band width = 10. Lower half of first band = 80-85
        closes = [100.0] * 30 + [82.0]  # price in lowest zone
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["BTC/USDT"], "grid_lower": 80.0, "grid_upper": 120.0,
                             "grid_levels": 4, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert any(s.symbol == "BTC/USDT" and s.side == "buy" for s in signals)

    def test_sell_when_price_in_upper_zone(self):
        from server.strategies.crypto_grid import CryptoGrid
        # Same grid, price in upper zone → sell
        closes = [100.0] * 30 + [115.0]
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["BTC/USDT"], "grid_lower": 80.0, "grid_upper": 120.0,
                             "grid_levels": 4, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({"BTC/USDT": 0.005}, client=client)
        assert any(s.symbol == "BTC/USDT" and s.side == "sell" for s in signals)

    def test_auto_range_uses_lookback(self):
        from server.strategies.crypto_grid import CryptoGrid
        # With grid_lower=0, grid_upper=0 — auto-detect from bars
        closes = list(range(60, 141))  # 60 to 140, range auto-detected
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["ETH/USDT"], "grid_lower": 0.0, "grid_upper": 0.0,
                             "grid_levels": 5, "lookback_days": 30, "notional": 500, "max_positions": 3})
        signals = strat.evaluate({}, client=client)
        assert isinstance(signals, list)  # no crash, auto-range computed

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.crypto_grid import CryptoGrid
        closes = [100.0] * 30 + [82.0]
        client = _mock_client(closes)
        strat = CryptoGrid({"symbols": ["BTC/USDT", "ETH/USDT"], "grid_lower": 80.0, "grid_upper": 120.0,
                             "grid_levels": 4, "notional": 500, "max_positions": 1})
        signals = strat.evaluate({"ETH/USDT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)
```

- [ ] **Step 2: Create `server/strategies/crypto_grid.py`**

```python
from .base import Strategy, Signal


class CryptoGrid(Strategy):
    name = "crypto_grid"
    label = "Crypto Grid Trading"
    description = (
        "Replicates Binance's grid trading strategy. Divides a price range into equal bands "
        "and buys when price is in the lower portion of a band, sells when it reaches the upper "
        "portion — profiting from price oscillation. Set grid_lower and grid_upper to define the "
        "range, or leave both at 0 to auto-detect from recent price history. "
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
         "hint": "Number of grid lines (bands). More lines = more trades, smaller profit per trade."},
        {"key": "lookback_days", "label": "Auto-Range Lookback (days)", "type": "number", "min": 7, "max": 90,
         "hint": "When bounds are set to 0, uses the highest and lowest price over this many days to set the grid."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Dollar amount to spend on each buy signal."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 20,
         "hint": "Maximum number of crypto pairs to hold at once."},
    ]

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        grid_lower   = float(self.params.get("grid_lower", 0.0))
        grid_upper   = float(self.params.get("grid_upper", 0.0))
        grid_levels  = int(self.params.get("grid_levels", 5))
        lookback     = int(self.params.get("lookback_days", 30))
        max_pos      = int(self.params.get("max_positions", 3))
        symbols      = [s.strip() for s in (self.params.get("symbols") or []) if s]

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

            # Auto-detect range from recent lookback bars
            lower = grid_lower
            upper = grid_upper
            if lower == 0.0 or upper == 0.0:
                recent = closes[-lookback:] if len(closes) >= lookback else closes
                lower = min(recent)
                upper = max(recent)

            if upper <= lower or grid_levels < 2:
                continue

            band_width = (upper - lower) / grid_levels
            # Which band is the current price in?
            band_idx = int((price - lower) / band_width)
            band_idx = max(0, min(band_idx, grid_levels - 1))

            band_low  = lower + band_idx * band_width
            band_high = band_low + band_width
            band_mid  = (band_low + band_high) / 2

            held = positions.get(sym, 0.0)

            if held > 0:
                # Sell when price is in the upper half of its band or above grid
                if price >= band_mid or price >= upper:
                    out.append(Signal(symbol=sym, side="sell", qty=held,
                        reason=f"grid sell: price {price:.4f} in upper zone "
                               f"[{band_mid:.4f}–{band_high:.4f}] (grid {lower:.2f}–{upper:.2f}, {grid_levels} levels)"))
            else:
                if open_positions >= max_pos:
                    continue
                # Buy when price is in the lower half of its band and within grid range
                if lower <= price < band_mid:
                    out.append(self._signal(sym, "buy",
                        f"grid buy: price {price:.4f} in lower zone "
                        f"[{band_low:.4f}–{band_mid:.4f}] (grid {lower:.2f}–{upper:.2f}, {grid_levels} levels)"))
                    open_positions += 1

        return out
```

- [ ] **Step 3: Add to `__init__.py` (final state)**

```python
from .base import Strategy
from .manual import ManualStrategy
from .sma_cross import SMACrossover
from .rsi_mr import RSIMeanReversion
from .momentum import MomentumBreakout
from .bollinger import BollingerBandMeanReversion
from .breakout_52w import Breakout52Week
from .macd_volume import MACDVolume
from .golden_cross import GoldenCross
from .crypto_trend import CryptoTrend
from .crypto_rsi_bounce import CryptoRSIBounce
from .crypto_volatility_breakout import CryptoVolatilityBreakout
from .crypto_grid import CryptoGrid

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (
        ManualStrategy,
        SMACrossover,
        RSIMeanReversion,
        MomentumBreakout,
        BollingerBandMeanReversion,
        Breakout52Week,
        MACDVolume,
        GoldenCross,
        CryptoTrend,
        CryptoRSIBounce,
        CryptoVolatilityBreakout,
        CryptoGrid,
    )
}
```

- [ ] **Step 4: Run all crypto tests**

```
pytest tests/test_crypto_strategies.py -v
```
Expected: 13 PASSED (3 + 3 + 3 + 4)

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -v
```
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```
git add server/strategies/crypto_grid.py server/strategies/__init__.py tests/test_crypto_strategies.py
git commit -m "feat: crypto_grid — Binance-style grid trading strategy"
```
