# Binance Integration Design

**Date:** 2026-05-12
**Approach:** Minimal shim (Approach A) — additive only, no existing files restructured

---

## Goal

Add Binance as a third supported broker for crypto spot trading (Testnet + Live), using `ccxt` as the connection library. Existing Alpaca and Tradier integrations are untouched.

---

## Architecture

Five touch points only:

| File | Change |
|---|---|
| `server/binance_client.py` | New file — implements same interface as `alpaca_client.AccountClient` and `tradier_client.TradierAccountClient` |
| `server/broker_factory.py` | Add `elif broker == "binance": return BinanceAccountClient(...)` |
| `server/db.py` | No migration needed — `broker` column has no CHECK constraint, `"binance"` inserts freely |
| `server/static/apikeys.html` | Add Binance to broker dropdown + credential hint text |
| `requirements.txt` | Add `ccxt>=4.4,<5` |

Engine, risk manager, strategies, notifications — all untouched.

---

## `binance_client.py` — Public Interface

Class: `BinanceAccountClient`

Constructor: `BinanceAccountClient(api_key: str, api_secret: str, paper: bool)`
- `paper=True` → Binance Testnet (`testnet.binance.vision`) via `exchange.set_sandbox_mode(True)`
- `paper=False` → Binance Live (`api.binance.com`)
- Constructor calls `exchange.load_markets()` on init so symbol resolution works immediately

### Methods

| Method | Signature | Notes |
|---|---|---|
| `get_account_summary` | `() -> dict` | Returns full account dict (see shape below) |
| `get_positions` | `() -> list[dict]` | Non-zero crypto balances as positions with USDT market value |
| `get_recent_bars` | `(symbol: str, days: int) -> list[dict]` | OHLCV candles for `{symbol}/USDT` pair — `days` converted to ccxt `limit` |
| `get_quote` | `(symbol: str) -> dict` | Bid/ask for `{symbol}/USDT` |
| `get_day_trade_count` | `() -> int` | Always returns `0` — PDT rules don't apply to crypto |
| `submit_market_order` | `(symbol, side, qty=None, notional=None, client_order_id=None) -> dict` | Spot market order |
| `submit_limit_order` | `(symbol, side, qty, limit_price, client_order_id=None) -> dict` | Spot limit order |
| `get_orders` | `() -> list[dict]` | Open + recent filled orders |
| `cancel_order` | `(order_id: str) -> dict` | Cancel open order |

### Symbol Normalization

All methods accept and return bare tickers (`"BTC"`, `"ETH"`).

**Incoming normalization** (before ccxt call):
```python
def _to_ccxt(symbol: str) -> str:
    s = symbol.upper()
    if "/" in s:
        return s  # already normalized
    if s.endswith("USDT"):
        return s[:-4] + "/USDT"  # BTCUSDT → BTC/USDT
    return s + "/USDT"  # BTC → BTC/USDT
```

**Outgoing stripping** (after ccxt response):
```python
def _from_ccxt(ccxt_symbol: str) -> str:
    return ccxt_symbol.split("/")[0]  # BTC/USDT → BTC
```

Strategies emit `"BTC"` → client sends `"BTC/USDT"` to ccxt → client returns `"BTC"` to engine. Everything upstream stays clean.

### Return Shapes

**`get_account_summary()`** — matches full contract expected by engine and risk manager:
```json
{
  "status": "active",
  "cash": 10000.0,
  "equity": 10000.0,
  "last_equity": 10000.0,
  "buying_power": 10000.0,
  "portfolio_value": 10000.0,
  "day_pl": 0.0,
  "day_pl_pct": 0.0,
  "pattern_day_trader": false,
  "trading_blocked": false,
  "account_type": "paper",
  "currency": "USDT"
}
```

Notes on Binance-specific derivation:
- `equity` / `portfolio_value` = USDT free + USDT locked + sum of (crypto qty × current price)
- `last_equity` = same as `equity` (Binance spot has no prior-day snapshot — day P&L tracking requires a stored session baseline)
- `day_pl` / `day_pl_pct` = `0.0` on first call; updated against a stored session-start baseline if available
- `pattern_day_trader` = always `False` (PDT is a US broker concept)
- `trading_blocked` = always `False` (Binance manages this separately via account status)

**`get_positions()`**
```json
[{
  "symbol": "BTC",
  "qty": 0.5,
  "market_value": 25000.0,
  "avg_entry_price": 0.0,
  "unrealized_pl": 0.0,
  "side": "long"
}]
```
Note: `avg_entry_price` and `unrealized_pl` return `0.0` — Binance spot balance API does not expose cost basis. UI will show blank P&L for Binance positions (acceptable).

**`get_recent_bars()`**
```json
[{"t": "2026-05-12T09:00:00Z", "o": 60000.0, "h": 61000.0, "l": 59500.0, "c": 60500.0, "v": 1234.5}]
```

**`get_quote()`**
```json
{"symbol": "BTC", "bid": 60490.0, "ask": 60510.0, "price": 60500.0}
```

**`get_orders()`**
```json
[{"id": "123456", "symbol": "BTC", "side": "buy", "qty": 0.01, "type": "market", "status": "filled", "submitted_at": "2026-05-12T09:00:00Z"}]
```

**`submit_market_order()` / `submit_limit_order()`**
```json
{"id": "binance-order-id", "symbol": "BTC", "side": "buy", "qty": 0.01, "status": "filled"}
```

---

## Known Limitations

**Automated trading is gated by the US market clock.** The engine checks `alpaca_client.get_clock()` before running strategies. When the US stock market is closed (weekends, after 4pm ET, holidays), the engine returns early and no strategies run — including those assigned to Binance accounts. Binance is a 24/7 exchange, but automated signals will only fire during US equity hours (9:30am–4pm ET, Mon–Fri). Manual orders via the positions page are unaffected.

**Manual order routing does not yet support Binance.** The `/api/orders POST` endpoint in `main.py` is hardcoded to `alpaca_client`. Placing a manual order from the UI while a Binance account is selected will route to Alpaca instead. This is a separate fix tracked for a future PR.

---

## Credentials

- `api_key` — Binance API Key (encrypted in DB, same as other brokers)
- `api_secret` — Binance Secret Key (encrypted in DB)
- Testnet keys generated at `testnet.binance.vision` — **separate keys from live, reset periodically**
- Live keys generated at `binance.com` → API Management

No new DB columns needed. `broker = "binance"`, `account_type = "paper"` (Testnet) or `"live"`.

---

## UI Changes (`apikeys.html`)

1. Add `<option value="binance">Binance</option>` to broker selector dropdown
2. When Binance selected, show hint text:
   - *"For paper mode, use Testnet keys from testnet.binance.vision — keys are separate from live and reset periodically"*
   - *"Crypto is always traded against USDT (e.g. BTC → BTC/USDT)"*
   - *"Automated strategies only run during US market hours (9:30am–4pm ET)"*
3. Field labels remain `API Key` / `API Secret` — same as other brokers

---

## Out of Scope

- Binance Futures and Margin trading
- Websocket price streaming (polling only, consistent with other brokers)
- Crypto-specific strategies (existing strategies work with any symbol)
- Multi-pair quote currency (USDT only)
- Binance-specific risk rules
- 24/7 engine clock (US market hours gate — separate future feature)
- Manual order routing to Binance (separate future fix)

---

## Dependencies

- `ccxt>=4.4,<5` — add to `requirements.txt`

---

## Testing

- Unit: `BinanceAccountClient` with mocked ccxt exchange
- Integration: Testnet account with real Testnet API keys
- Verify symbol normalization is idempotent: `BTC` → `BTC/USDT`, `BTCUSDT` → `BTC/USDT`, `BTC/USDT` → `BTC/USDT`
- Verify stripping: `BTC/USDT` → `BTC`
- Verify `get_account_summary()` returns all 12 keys
- Verify `get_day_trade_count()` returns `0`
- Verify engine submits orders through Binance client without errors
