# Multi-Broker Account Support — Design Spec

**Date:** 2026-05-10
**Status:** Approved (post-review revision)

---

## Goal

Add support for multiple broker accounts so that strategies can be independently assigned to and executed on one or more Alpaca accounts, with per-(strategy, account) enable/disable control.

---

## Architecture

A two-table broker account system is added to the existing SQLite database. `broker_accounts` stores encrypted credentials for each brokerage connection. `strategy_accounts` is a many-to-many junction table mapping strategies to accounts, with a per-pair `enabled` flag.

The existing `strategies.enabled` column remains the global master switch — if it is off, no accounts run that strategy regardless of junction table state.

On startup, if `ALPACA_API_KEY` and `ALPACA_API_SECRET` are both non-blank in `.env`, they are migrated into `broker_accounts` as the Default account (id=1) using `ON CONFLICT(id) DO NOTHING` — existing rows are never overwritten.

Encryption and decryption of credentials is handled exclusively by `server/crypto.py`. The DB layer stores and retrieves ciphertext only. The engine decrypts credentials at the moment a `TradingClient` is constructed — not in the DB layer.

The trading engine adds a per-account loop around the existing per-strategy loop. All existing logic (market clock check, kill switch, risk checks, position sizing, signal logging, notifications) is preserved verbatim; only the account iteration wrapper is new.

The API Keys page becomes a full CRUD interface for broker accounts. The Bots page strategy rows expand to show per-account sub-rows with individual toggles and an account assignment picker.

---

## New File: `server/crypto.py`

Centralises all Fernet operations. Loaded once at startup. No other module imports `Fernet` directly.

```python
from cryptography.fernet import Fernet
import os, logging

log = logging.getLogger(__name__)
_fernet: Fernet | None = None

def init_crypto() -> None:
    global _fernet
    raw = os.environ.get("DB_SECRET_KEY", "")
    if not raw:
        raise RuntimeError(
            "DB_SECRET_KEY is missing. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        _fernet = Fernet(raw.encode())
    except Exception:
        raise RuntimeError(
            "DB_SECRET_KEY is not a valid Fernet key. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    log.info("DB_SECRET_KEY loaded and validated.")

def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()

def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
```

`init_crypto()` is called at the top of `main.py` before any route registration. The key value is never logged.

**Key rotation warning:** Changing `DB_SECRET_KEY` renders all existing encrypted credentials unreadable. A re-encryption migration must be performed manually before restarting with a new key. This is documented prominently in `.env.example` as a comment block.

---

## Database Schema

### Connection Helper

Rename the existing `conn()` context manager in `server/db.py` to `get_conn()` and add `PRAGMA foreign_keys = ON` immediately after `sqlite3.connect()`. Update all 11 existing call sites from `with conn()` to `with get_conn()`.

```python
@contextmanager
def get_conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()
```

### New Tables

```sql
CREATE TABLE IF NOT EXISTS broker_accounts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  label        TEXT NOT NULL,
  api_key      TEXT NOT NULL,    -- Fernet-encrypted at rest
  api_secret   TEXT NOT NULL,    -- Fernet-encrypted at rest
  account_type TEXT NOT NULL DEFAULT 'paper'
                   CHECK (account_type IN ('paper', 'live')),
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategy_accounts (
  strategy_name TEXT NOT NULL REFERENCES strategies(name) ON DELETE CASCADE,
  account_id    INTEGER NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  enabled       INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (strategy_name, account_id)
);
```

`updated_at` on `broker_accounts` is set by the application layer on every PATCH and PUT operation — not via a SQLite trigger.

### Startup .env Migration

Only runs if both `ALPACA_API_KEY` and `ALPACA_API_SECRET` are non-blank. `account_type` is read from `ALPACA_ACCOUNT_TYPE` env var (defaulting to `'paper'`). Both credentials are encrypted via `crypto.encrypt()` before insertion.

```sql
INSERT INTO broker_accounts (id, label, api_key, api_secret, account_type)
VALUES (1, 'Default', ?, ?, ?)
ON CONFLICT(id) DO NOTHING;
```

---

## Secret Encryption

**See `server/crypto.py` above.**

**Masking rule on API responses:** `api_key` is returned as `"****" + last4`. `api_secret` is never returned in any response — it is write-only. Decryption happens only in the engine loop at the moment a `TradingClient` is constructed.

---

## Setup Wizard

`POST /api/setup/complete` in `main.py` currently writes `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `ALPACA_ENDPOINT`, and `ALPACA_ACCOUNT_TYPE` to `.env`. It must be updated to also generate and write `DB_SECRET_KEY` if not already present:

```python
if not os.environ.get("DB_SECRET_KEY"):
    new_key = Fernet.generate_key().decode()
    # append DB_SECRET_KEY=<new_key> to .env
```

This ensures a fresh first-time setup results in a valid `.env` that passes startup validation.

---

## API Endpoints

### Broker Accounts CRUD

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/broker-accounts` | List all accounts (keys masked `****last4`) |
| GET | `/api/broker-accounts/{id}` | Single account (keys masked; used to pre-populate edit modal) |
| POST | `/api/broker-accounts` | Create account `{label, api_key, api_secret, account_type}` |
| PATCH | `/api/broker-accounts/{id}` | Update metadata only — body: `BrokerAccountPatch` |
| PUT | `/api/broker-accounts/{id}/credentials` | Replace api_key + api_secret (re-encrypts both) |
| DELETE | `/api/broker-accounts/{id}` | Delete account; cascades strategy_accounts |
| GET | `/api/broker-accounts/{id}/status` | Live connectivity test via per-account TradingClient |
| GET | `/api/broker-accounts/{id}/assignments` | List strategy names assigned to this account (used by delete confirmation modal) |

**Pydantic models:**

```python
class BrokerAccountCreate(BaseModel):
    label: str
    api_key: str
    api_secret: str
    account_type: Literal["paper", "live"] = "paper"

class BrokerAccountPatch(BaseModel):
    label: str | None = None
    account_type: Literal["paper", "live"] | None = None
    # returns 422 if both are None

class BrokerCredentialsUpdate(BaseModel):
    api_key: str
    api_secret: str
```

### Strategy Account Assignments

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/strategies/{name}/accounts` | List accounts assigned to strategy (with enabled flag) |
| POST | `/api/strategies/{name}/accounts` | Assign account `{account_id, enabled}` |
| PATCH | `/api/strategies/{name}/accounts/{id}` | Toggle enabled `{enabled: bool}` |
| DELETE | `/api/strategies/{name}/accounts/{id}` | Unassign account |

---

## `alpaca_client.py` — Per-Account Factory

Add a pure factory function. The existing global `_trading` / `_data` singletons are unchanged.

```python
def get_trading_client(api_key: str, api_secret: str, paper: bool) -> TradingClient:
    return TradingClient(api_key, api_secret, paper=paper)
```

The engine uses a thin wrapper to avoid duplicating SDK call logic:

```python
class AccountClient:
    def __init__(self, api_key: str, api_secret: str, paper: bool):
        self._client = TradingClient(api_key, api_secret, paper=paper)

    def get_account_summary(self) -> dict:
        a = self._client.get_account()
        return {"equity": float(a.equity), "cash": float(a.cash), ...}

    def submit_market_order(self, signal: dict) -> None:
        req = MarketOrderRequest(
            symbol=signal["symbol"],
            qty=signal["qty"],
            side=OrderSide.BUY if signal["side"] == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        self._client.submit_order(req)
```

`AccountClient` mirrors the existing module-level function signatures so the engine loop is a drop-in replacement.

---

## Engine Changes (`server/engine.py`)

The per-account loop wraps the existing per-strategy logic. **All existing behaviour (clock check, kill switch, risk checks, position sizing, `db.log_signal`, notifications) is preserved verbatim.** Only the account iteration wrapper is new.

Pseudocode showing the structural change only:

```python
async def run_tick():
    # --- existing: market clock check, kill switch check ---
    # (unchanged)

    strategies = db.get_strategies()

    for strat in strategies:
        if not strat["enabled"]:
            continue

        accounts = db.get_strategy_accounts(strat["name"])  # returns enabled pairs (ciphertext)
        if not accounts:
            continue

        # Per-account client cache — avoid re-instantiating for same account twice in one tick
        client_cache: dict[int, AccountClient] = {}

        for acct in accounts:
            acct_id = acct["id"]
            if acct_id not in client_cache:
                client_cache[acct_id] = AccountClient(
                    api_key=crypto.decrypt(acct["api_key"]),
                    api_secret=crypto.decrypt(acct["api_secret"]),
                    paper=(acct["account_type"] == "paper"),
                )
            client = client_cache[acct_id]

            try:
                summary = client.get_account_summary()
                # --- existing: risk checks, position sizing, signal generation ---
                # (unchanged, uses per-account summary)
                signal = run_strategy(strat, summary)
                if signal:
                    # --- existing: db.log_signal, notifications ---
                    client.submit_market_order(signal)
            except Exception as e:
                log.warning("tick error strat=%s acct=%d: %s", strat["name"], acct_id, e)
                continue
```

- `db.get_strategy_accounts()` returns rows with **ciphertext** `api_key` and `api_secret`
- `crypto.decrypt()` is called only here, only when constructing `AccountClient`
- `client_cache` prevents redundant `TradingClient` instantiations when multiple strategies share the same account within one tick
- The existing global `trading()` / `_data` clients remain for `GET /api/account` and the market chip until migrated in a future phase

---

## Frontend Changes

### API Keys page (`apikeys.html` + `initApiKeys()`)

Replaces the current single-account status card with:

- **Account cards grid** — one card per broker account: label, type badge, masked key (`****last4`), created date, "Test Connection" button (hits `GET /api/broker-accounts/{id}/status`)
- **Add Account modal** — Label, API Key, API Secret, Account Type (paper/live); submits POST, re-renders grid
- **Edit modal** — pre-populated via `GET /api/broker-accounts/{id}`; updates label and account type only via PATCH
- **Rotate Credentials modal** — separate modal for replacing api_key + api_secret; hits PUT `/credentials` endpoint
- **Delete button** — fetches `GET /api/broker-accounts/{id}/assignments` first; shows confirmation modal listing affected strategy names (informational only, not a block); then sends DELETE

### Bots page (`bots.html` + `initBots()`)

Strategy rows gain an expand toggle. Expanded sub-table:

```
▼ SMACrossover                    [global toggle]
   └ Default (Paper)   enabled    [per-account toggle]
   └ Live Account      disabled   [per-account toggle]
   └ [+ Assign Account]
```

- Global toggle controls `strategies.enabled` master switch — disabling greys out all sub-rows
- Per-account toggle hits `PATCH /api/strategies/{name}/accounts/{id}`
- "Assign Account" opens a picker modal listing unassigned broker accounts; submits POST with `enabled: true`
- Unassign via × button on each sub-row

### Unchanged pages

Dashboard, Performance, Positions, Balances, Logs, Risk, Settings, Backtesting — no changes.

---

## Files Modified

| File | Change |
|------|--------|
| `server/crypto.py` | **Create** — Fernet init, `encrypt()`, `decrypt()` |
| `server/db.py` | Rename `conn()` → `get_conn()` + FK pragma; add new tables + CRUD functions; startup migration |
| `server/alpaca_client.py` | Add `AccountClient` wrapper class |
| `server/engine.py` | Add per-account loop with `client_cache`; all existing logic preserved |
| `server/main.py` | Call `init_crypto()` on startup; add 11 new endpoints; update `setup_complete` to write `DB_SECRET_KEY` |
| `server/static/apikeys.html` | Full CRUD account management UI |
| `server/static/app.js` | Rewrite `initApiKeys()`; update `initBots()` for expandable rows |
| `requirements.txt` | Add `cryptography>=41.0` |
| `.env.example` | **Create** — all keys stubbed; `DB_SECRET_KEY` rotation warning as comment block |

---

## Out of Scope (Future Phase)

- Migration tooling for `DB_SECRET_KEY` rotation (re-encrypt all rows with new key)
- Multi-broker support for `/api/account` dashboard widget (still uses global client)
- Non-Alpaca brokers
