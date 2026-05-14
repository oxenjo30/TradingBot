# 4-EMA Confluence Strategy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `EMAConfluence` strategy to TradeBot that scores EMA 8/13/48/200 alignment to find high-conviction trend entries on both stocks (Alpaca/daily) and crypto (Binance/hourly), with optional confluence-scaled position sizing.

**Architecture:** Single new strategy file `server/strategies/ema_confluence.py` following the exact same pattern as `momentum.py` and `sma_cross.py`. One import line added to `server/strategies/__init__.py`. No engine, HTML, CSS, or JS changes.

**Tech Stack:** Python, existing `Strategy` base class, `_get_bars()` helper, `_signal()` helper.

---

## File Map

- **Create:** `server/strategies/ema_confluence.py` — full strategy implementation
- **Create:** `tests/test_ema_confluence.py` — unit tests
- **Modify:** `server/strategies/__init__.py` — import + register

---

### Task 1: Tests for `_ema()` helper and confluence scoring

**Files:**
- Create: `tests/test_ema_confluence.py`

- [ ] **Step 1: Write the tests**

```python
"""Tests for the 4-EMA Confluence strategy."""
import pytest
from unittest.mock import MagicMock


def _make_bars(closes):
    return [{"o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1000} for c in closes]


def _mock_client(closes):
    client = MagicMock()
    client.get_recent_bars.return_value = _make_bars(closes)
    return client


# ---------------------------------------------------------------------------
# _ema() helper
# ---------------------------------------------------------------------------

class TestEmaHelper:
    def test_returns_none_when_insufficient_data(self):
        from server.strategies.ema_confluence import _ema
        assert _ema([100.0, 101.0], 5) is None

    def test_returns_sma_for_exactly_period_length(self):
        from server.strategies.ema_confluence import _ema
        # 4 values all 100 — SMA seed = 100, no further iterations
        result = _ema([100.0, 100.0, 100.0, 100.0], 4)
        assert result == pytest.approx(100.0)

    def test_ema_rises_toward_rising_price(self):
        from server.strategies.ema_confluence import _ema
        # 8 flat bars then a big jump — EMA should be between old and new
        closes = [100.0] * 8 + [200.0]
        result = _ema(closes, 8)
        assert 100.0 < result < 200.0

    def test_ema_falls_toward_falling_price(self):
        from server.strategies.ema_confluence import _ema
        closes = [100.0] * 8 + [50.0]
        result = _ema(closes, 8)
        assert 50.0 < result < 100.0

    def test_returns_float(self):
        from server.strategies.ema_confluence import _ema
        result = _ema([100.0] * 10, 5)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# EMAConfluence — buy signals
# ---------------------------------------------------------------------------

class TestEMAConfluenceBuy:
    def _bull_closes(self, n=220):
        """n bars where price steadily climbs — all 4 EMAs will be below final price."""
        return [100.0 + i * 0.5 for i in range(n)]

    def test_buy_signal_full_bull_score(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert any(s.symbol == "AAPL" and s.side == "buy" for s in signals)

    def test_no_buy_when_min_confluence_not_met(self):
        from server.strategies.ema_confluence import EMAConfluence
        # Flat then one small rise — only short EMAs above price, long ones aren't
        closes = [100.0] * 210 + [101.0]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_buy_when_max_positions_reached(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL", "MSFT"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 1,
            "avoid_earnings": False,
        })
        # Already at max
        signals = strat.evaluate({"MSFT": 1.0}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_buy_notional_used(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 750,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        buys = [s for s in signals if s.side == "buy"]
        if buys:
            assert buys[0].notional == 750.0

    def test_scaled_sizing_score4_uses_full_notional(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": True,
            "notional": 1000,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        buys = [s for s in signals if s.side == "buy"]
        # Score 4 → 100% of notional
        if buys:
            assert buys[0].notional == pytest.approx(1000.0)

    def test_no_buy_when_mixed_signals(self):
        """bear_score > 0 means mixed — no buy even if bull_score >= min_confluence."""
        from server.strategies.ema_confluence import EMAConfluence
        # Flat price — all EMAs converge to same value; price == EMA is neither bull nor bear
        # Use descending to ensure some EMAs are above price
        closes = [200.0 - i * 0.3 for i in range(220)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 2,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "buy" for s in signals)

    def test_no_buy_when_already_holding(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = self._bull_closes(220)
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 4,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({"AAPL": 2.5}, client=client)
        assert not any(s.side == "buy" for s in signals)


# ---------------------------------------------------------------------------
# EMAConfluence — sell signals
# ---------------------------------------------------------------------------

class TestEMAConfluenceSell:
    def test_sell_on_bear_confluence(self):
        """Sustained decline triggers bear score >= min_confluence and sell."""
        from server.strategies.ema_confluence import EMAConfluence
        # Strong downtrend — price well below all EMAs
        closes = [200.0 - i * 0.5 for i in range(220)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({"AAPL": 10.0}, client=client)
        assert any(s.symbol == "AAPL" and s.side == "sell" for s in signals)

    def test_sell_qty_equals_held(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = [200.0 - i * 0.5 for i in range(220)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({"AAPL": 7.5}, client=client)
        sells = [s for s in signals if s.side == "sell"]
        if sells:
            assert sells[0].qty == pytest.approx(7.5)

    def test_no_sell_when_not_holding(self):
        from server.strategies.ema_confluence import EMAConfluence
        closes = [200.0 - i * 0.5 for i in range(220)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert not any(s.side == "sell" for s in signals)


# ---------------------------------------------------------------------------
# EMAConfluence — insufficient data
# ---------------------------------------------------------------------------

class TestEMAConfluenceEdgeCases:
    def test_skip_symbol_when_insufficient_bars(self):
        from server.strategies.ema_confluence import EMAConfluence
        # Only 50 bars — not enough for EMA 200
        closes = [100.0 + i for i in range(50)]
        client = _mock_client(closes)
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert signals == []

    def test_bar_fetch_exception_skips_symbol(self):
        from server.strategies.ema_confluence import EMAConfluence
        client = MagicMock()
        client.get_recent_bars.side_effect = Exception("network error")
        strat = EMAConfluence({
            "symbols": ["AAPL"],
            "use_scanner": False,
            "min_confluence": 3,
            "scaled_sizing": False,
            "notional": 500,
            "max_positions": 5,
            "avoid_earnings": False,
        })
        signals = strat.evaluate({}, client=client)
        assert signals == []


# ---------------------------------------------------------------------------
# EMAConfluence — metadata
# ---------------------------------------------------------------------------

class TestEMAConfluenceMetadata:
    def test_strategy_name(self):
        from server.strategies.ema_confluence import EMAConfluence
        assert EMAConfluence.name == "ema_confluence"

    def test_strategy_brokers(self):
        from server.strategies.ema_confluence import EMAConfluence
        assert "alpaca" in EMAConfluence.brokers
        assert "binance" in EMAConfluence.brokers

    def test_describe_has_required_keys(self):
        from server.strategies.ema_confluence import EMAConfluence
        d = EMAConfluence.describe()
        for key in ("name", "label", "description", "default_params", "params_schema", "brokers"):
            assert key in d

    def test_registered_in_registry(self):
        from server.strategies import REGISTRY
        assert "ema_confluence" in REGISTRY
```

- [ ] **Step 2: Run tests to verify they fail (strategy doesn't exist yet)**

```
cd c:\TradeBot
python -m pytest tests/test_ema_confluence.py -v 2>&1 | head -30
```

Expected: ImportError or ModuleNotFoundError for `ema_confluence`

- [ ] **Step 3: Commit the tests**

```bash
git add tests/test_ema_confluence.py
git commit -m "test: add failing tests for EMAConfluence strategy"
```

---

### Task 2: Implement `server/strategies/ema_confluence.py`

**Files:**
- Create: `server/strategies/ema_confluence.py`

- [ ] **Step 1: Write the full strategy file**

```python
from .base import Strategy, Signal


def _ema(closes: list, period: int):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    val = sum(closes[:period]) / period
    for price in closes[period:]:
        val = price * k + val * (1 - k)
    return val


_SCALE = {4: 1.0, 3: 0.70, 2: 0.40}


class EMAConfluence(Strategy):
    name = "ema_confluence"
    label = "4-EMA Confluence"
    description = (
        "Scores EMA 8/13/48/200 alignment to find high-conviction trend entries. "
        "Requires all scored EMAs to agree — no mixed signals. Position size scales "
        "with confluence score when enabled. Works on stocks (daily) and crypto (hourly)."
    )
    brokers = ["alpaca", "binance"]
    default_params = {
        "symbols": [],
        "use_scanner": True,
        "timeframe": "day",
        "min_confluence": 3,
        "scaled_sizing": True,
        "notional": 500,
        "avoid_earnings": False,
        "max_positions": 5,
    }
    params_schema = [
        {"key": "symbols", "label": "Symbols to Trade", "type": "symbols",
         "hint": "Comma-separated tickers to always include. Leave empty to rely on the scanner (stocks) or provide a list (crypto)."},
        {"key": "use_scanner", "label": "Auto-discover Stocks", "type": "bool",
         "hint": "When enabled, top active and gaining stocks are added automatically each tick. Ignored for Binance accounts."},
        {"key": "timeframe", "label": "Timeframe", "type": "select",
         "options": ["day", "hour"],
         "hint": "Use 'day' for stocks (Alpaca) and 'hour' for crypto (Binance)."},
        {"key": "min_confluence", "label": "Min Confluence Score", "type": "number", "min": 2, "max": 4,
         "hint": "How many of the 4 EMAs must agree for a signal. 4 = all four aligned (highest conviction), 2 = any two. Mixed signals always block a trade."},
        {"key": "scaled_sizing", "label": "Scale Size by Score", "type": "bool",
         "hint": "When on: score 4 uses 100% of the notional amount, score 3 uses 70%, score 2 uses 40%. When off, always trades the full amount."},
        {"key": "notional", "label": "Amount per Trade (USD)", "type": "number", "min": 10, "max": 100000,
         "hint": "Maximum USD to spend on a single buy. At confluence score 4 the full amount is used; lower scores use a fraction when scaled sizing is on."},
        {"key": "avoid_earnings", "label": "Skip Earnings Days", "type": "bool",
         "hint": "Skip symbols that have an earnings announcement within 2 days. Alpaca only — crypto is always exempt."},
        {"key": "max_positions", "label": "Max Open Positions", "type": "number", "min": 1, "max": 50,
         "hint": "Maximum number of symbols this strategy can hold at the same time."},
    ]

    def _get_symbols(self) -> list:
        fixed = [s.upper().strip() for s in (self.params.get("symbols") or []) if s]
        if self.params.get("use_scanner", True) and not fixed:
            try:
                from .. import scanner
                scanned = scanner.get_scanner_universe(
                    min_price=5.0, max_price=500.0, top_actives=25, top_gainers=15
                )
                return scanned
            except Exception:
                return fixed
        return fixed

    def _near_earnings(self, client, symbol: str) -> bool:
        try:
            return client.has_earnings_soon(symbol, days=2)
        except Exception:
            return False

    def evaluate(self, positions, client=None):
        out: list[Signal] = []
        min_conf  = int(self.params.get("min_confluence", 3))
        scaled    = bool(self.params.get("scaled_sizing", True))
        notional  = float(self.params.get("notional", 500))
        max_pos   = int(self.params.get("max_positions", 5))
        avoid_e   = bool(self.params.get("avoid_earnings", False))
        timeframe = self.params.get("timeframe", "day")

        is_crypto = client is not None and hasattr(client, "exchange") and "binance" in str(getattr(client, "exchange", "")).lower()

        open_positions = sum(1 for v in positions.values() if v > 0)
        days = 10 if timeframe == "hour" else 300

        for sym in self._get_symbols():
            try:
                bars = self._get_bars(client, sym, days=days)
            except Exception:
                continue

            closes = [b["c"] for b in bars]
            e8   = _ema(closes, 8)
            e13  = _ema(closes, 13)
            e48  = _ema(closes, 48)
            e200 = _ema(closes, 200)

            if any(v is None for v in (e8, e13, e48, e200)):
                continue

            price = closes[-1]
            bull_score = sum(1 for e in (e8, e13, e48, e200) if price > e)
            bear_score = sum(1 for e in (e8, e13, e48, e200) if price < e)

            held = positions.get(sym, 0.0)

            if held > 0:
                if bear_score >= min_conf or price < e48:
                    if bear_score >= min_conf:
                        reason = (
                            f"4-EMA bear score {bear_score}/4: price below "
                            + "/".join(
                                n for n, e in [("EMA8", e8), ("EMA13", e13), ("EMA48", e48), ("EMA200", e200)]
                                if price < e
                            )
                            + " | exit full position"
                        )
                    else:
                        reason = f"4-EMA exit: price {price:.2f} < EMA48 {e48:.2f} -- trend invalidated"
                    out.append(Signal(symbol=sym, side="sell", qty=held, reason=reason))
                continue

            if open_positions >= max_pos:
                continue

            if bull_score >= min_conf and bear_score == 0:
                if avoid_e and not is_crypto and client is not None:
                    if self._near_earnings(client, sym):
                        continue

                size = notional * _SCALE.get(bull_score, 1.0) if scaled else notional
                reason = (
                    f"4-EMA bull score {bull_score}/4: price {price:.2f} "
                    f"> EMA8 {e8:.2f} > EMA13 {e13:.2f} > EMA48 {e48:.2f} > EMA200 {e200:.2f} "
                    f"| notional ${size:.0f}"
                )
                out.append(Signal(symbol=sym, side="buy", notional=size, reason=reason))
                open_positions += 1

        return out
```

- [ ] **Step 2: Run tests to verify they pass**

```
cd c:\TradeBot
python -m pytest tests/test_ema_confluence.py -v
```

Expected: All tests PASS. The `test_registered_in_registry` test will still fail until Task 3.

- [ ] **Step 3: Commit**

```bash
git add server/strategies/ema_confluence.py
git commit -m "feat: implement EMAConfluence strategy (4-EMA 8/13/48/200)"
```

---

### Task 3: Register strategy in `__init__.py`

**Files:**
- Modify: `server/strategies/__init__.py`

- [ ] **Step 1: Add the import and register**

In `server/strategies/__init__.py`, add after the `from .crypto_grid import CryptoGrid` line:

```python
from .ema_confluence import EMAConfluence
```

And inside the `REGISTRY` tuple, add `EMAConfluence` after `CryptoGrid`:

```python
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
        EMAConfluence,
    )
}
```

- [ ] **Step 2: Run the full test suite**

```
cd c:\TradeBot
python -m pytest tests/test_ema_confluence.py -v
```

Expected: All tests PASS including `test_registered_in_registry`.

- [ ] **Step 3: Verify no existing tests broken**

```
cd c:\TradeBot
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All previously passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add server/strategies/__init__.py
git commit -m "feat: register EMAConfluence strategy in REGISTRY"
```

---

### Task 4: Manual verification in Bots UI

**Files:** None (read-only verification)

- [ ] **Step 1: Start the server**

```
cd c:\TradeBot
python -m uvicorn server.main:app --reload --port 8000
```

- [ ] **Step 2: Verify strategy appears in Bots UI**

Navigate to the Bots & Strategies page. Click "Add Bot" or "New Strategy". Confirm:
- "4-EMA Confluence" appears in the strategy dropdown
- All 8 params render with their labels and hints
- `min_confluence` shows as a number input with min=2 max=4
- `scaled_sizing` shows as a toggle
- `timeframe` shows as a select with `day` / `hour` options
- `symbols` shows as the symbol multi-input
- `avoid_earnings` shows as a toggle

- [ ] **Step 3: Create a test bot and verify it saves**

Create a bot with the strategy, set symbols to `AAPL`, notional to `500`. Save. Refresh page. Confirm the bot persists with correct params.

- [ ] **Step 4: Final commit if any adjustments needed**

If any UI param label/hint tweaks are needed, edit `params_schema` in `ema_confluence.py` and commit:

```bash
git add server/strategies/ema_confluence.py
git commit -m "fix: adjust EMAConfluence param labels for UI clarity"
```

---

## Self-Review

**Spec coverage:**
- ✅ EMA 8/13/48/200 implemented in `_ema()` — Task 2
- ✅ Bull/bear score logic — Task 2, covered by tests in Task 1
- ✅ Buy condition: `bull_score >= min_confluence AND bear_score == 0` — Task 2
- ✅ Sell: `bear_score >= min_confluence OR price < ema_48` — Task 2
- ✅ Scaled sizing: score→multiplier map `{4:1.0, 3:0.70, 2:0.40}` — Task 2
- ✅ Daily bars: `days=300`, hourly: `days=10` — Task 2
- ✅ `avoid_earnings` calls `client.has_earnings_soon()` with graceful fallback — Task 2
- ✅ `brokers = ["alpaca", "binance"]` — Task 2
- ✅ Registration in REGISTRY — Task 3
- ✅ UI verification — Task 4
- ✅ Reason strings: ASCII-safe, match spec format — Task 2
- ✅ No hardcoded hex colors in params_schema

**Placeholder scan:** No TBDs or incomplete sections.

**Type consistency:** `Signal(symbol, side, qty=held, reason=...)` for sells; `Signal(symbol, side, notional=size, reason=...)` for buys — matches `base.py` Signal dataclass throughout.
