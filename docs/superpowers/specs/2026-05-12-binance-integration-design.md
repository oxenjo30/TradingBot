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
| `server/db.py` | Verify no CHECK constraint blocks `"binance"` in `broker` column (no migration needed) |
| `server/static/apikeys.html` | Add Binance to broker dropdown + credential hint text |
| `requirements.txt` | Add `ccxt` |

Engine, risk manager, strategies, notifications — all untouched.

---

## `binance_client.py` — Public Interface

Class: `BinanceAccountClient`

Constructor: `BinanceAccountClient(api_key: str, api_secret: str, paper: bool)`
- `paper=True` → Binance Testnet (`testnet.binance.vision`) via `exchange.set_sandbox_mode(True)`
- `paper=False` → Binance Live (`api.binance.com`)

### Methods

| Method | Signature | Notes |
|---|---|---|
| `get_account` | `() -> dict` | Returns `equity`, `cash`, `buying_power` from USDT balance |
| `get_positions` | `() -> list[dict]` | Non-zero crypto balances as positions with USDT market value |
| `get_bars` | `(symbol: str, limit: int) -> list[dict]` | OHLCV candles for `{symbol}USDT` pair |
| `get_quote` | `(symbol: str) -> dict` | Bid/ask for `{symbol}USDT` |
| `submit_market_order` | `(symbol, side, qty=None, notional=None, client_order_id=None) -> dict` | Spot market order |
| `submit_limit_order` | `(symbol, side, qty, limit_price, client_order_id=None) -> dict` | Spot limit order |
| `get_orders` | `() -> list[dict]` | Open + recent filled orders |
| `cancel_order` | `(order_id: str) -> dict` | Cancel open order |

### Symbol Normalization

All methods accept and return bare tickers (`"BTC"`, `"ETH"`).
Internally: `symbol + "USDT"` before any ccxt call. Response symbols stripped back to bare ticker before returning.

Strategies emit `"BTC"` → client sends `"BTCUSDT"` to Binance → client returns `"BTC"` to engine. Everything upstream stays clean.

### Return Shape (matches existing brokers)

**`get_account()`**
```json
{"equity": 10000.0, "cash": 10000.0, "buying_power": 10000.0, "currency": "USDT"}
```

**`get_positions()`**
```json
[{"symbol": "BTC", "qty": 0.5, "market_value": 25000.0, "avg_entry_price": 48000.0, "unrealized_pl": 1000.0, "side": "long"}]
```

**`get_bars()`**
```json
[{"t": "2026-05-12T09:00:00Z", "o": 60000.0, "h": 61000.0, "l": 59500.0, "c": 60500.0, "v": 1234.5}]
```

**`get_quote()`**
```json
{"symbol": "BTC", "bid": 60490.0, "ask": 60510.0, "price": 60500.0}
```

**`submit_market_order()` / `submit_limit_order()`**
```json
{"id": "binance-order-id", "symbol": "BTC", "side": "buy", "qty": 0.01, "status": "filled"}
```

---

## Credentials

- `api_key` — Binance API Key (encrypted in DB, same as other brokers)
- `api_secret` — Binance Secret Key (encrypted in DB)
- Testnet keys generated at `testnet.binance.vision` (separate from live keys)
- Live keys generated at `binance.com` → API Management

No new DB columns needed. `broker = "binance"`, `account_type = "paper"` (Testnet) or `"live"`.

---

## UI Changes (`apikeys.html`)

1. Add `<option value="binance">Binance</option>` to broker selector dropdown
2. When Binance selected, show hint text:
   - *"For paper mode, use Testnet keys from testnet.binance.vision"*
   - *"Crypto is always traded against USDT (BTC → BTCUSDT)"*
3. Field labels remain `API Key` / `API Secret` — same as other brokers

---

## Out of Scope

- Binance Futures and Margin trading
- Websocket price streaming (polling only, consistent with other brokers)
- Crypto-specific strategies (existing strategies work with any symbol)
- Multi-pair quote currency (USDT only)
- Binance-specific risk rules

---

## Dependencies

- `ccxt>=4.0.0` — add to `requirements.txt`

---

## Testing

- Unit: `BinanceAccountClient` with mocked ccxt exchange
- Integration: Testnet account with real Testnet API keys
- Verify symbol normalization round-trips (`BTC` → `BTCUSDT` → `BTC`)
- Verify engine submits orders through Binance client without errors
