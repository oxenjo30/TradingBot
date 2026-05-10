# Multi-Broker Account Support — Design Spec

**Date:** 2026-05-10
**Status:** Approved

---

## Goal

Add support for multiple broker accounts so that strategies can be independently assigned to and executed on one or more Alpaca accounts, with per-(strategy, account) enable/disable control.

---

## Architecture

A two-table broker account system is added to the existing SQLite database. `broker_accounts` stores credentials for each brokerage connection. `strategy_accounts` is a many-to-many junction table mapping strategies to accounts, with a per-pair `enabled` flag.

The existing `strategies.enabled` column remains the global master switch — if it is off, no accounts run that strategy regardless of junction table state.

On startup, if `ALPACA_API_KEY` and `ALPACA_API_SECRET` are both non-blank in `.env`, they are migrated into `broker_accounts` as the Default account (id=1) using `ON CONFLICT(id) DO NOTHING` — existing rows are never overwritten.

The trading engine changes from one global alpaca client to instantiating a per-account `TradingClient` on each tick. Each (strategy, account) pair runs independently. A per-pair exception is caught and logged without aborting other pairs.

The API Keys page becomes a full CRUD interface for broker accounts. The Bots page strategy rows expand to show per-account sub-rows with individual toggles and an account assignment picker.

---

## Database Schema

### Migration

Every `sqlite3.connect()` call executes `PRAGMA foreign_keys = ON` immediately via a `get_conn()` helper before any other statement.

```sql
PRAGMA foreign_keys = ON;

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
  strategy_name TEXT NOT NULL,
  account_id    INTEGER NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  enabled       INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  PRIMARY KEY (strategy_name, account_id)
);
```

### Startup .env Migration

Only runs if `ALPACA_API_KEY` and `ALPACA_API_SECRET` are both non-blank:

```sql
INSERT INTO broker_accounts (id, label, api_key, api_secret, account_type)
VALUES (1, 'Default', ?, ?, ?)
ON CONFLICT(id) DO NOTHING;
```

`api_key` and `api_secret` are Fernet-encrypted before insertion. `updated_at` is set by the application layer on every PATCH and PUT operation; it is not managed by a SQLite trigger.

---

## Secret Encryption

**Library:** `cryptography.fernet.Fernet`

**Key source:** `DB_SECRET_KEY` environment variable in `.env`.

**Startup validation:**

```python
key = os.environ["DB_SECRET_KEY"].encode()
try:
    Fernet(key)
except Exception:
    raise RuntimeError(
        "DB_SECRET_KEY is not a valid Fernet key. "
        "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )
log.info("DB_SECRET_KEY loaded and validated.")
```

The app refuses to start if `DB_SECRET_KEY` is absent or malformed. The log line confirms validation only — the key value is never logged.

**Key rotation warning:** Changing `DB_SECRET_KEY` renders all existing encrypted credentials in the database unreadable. A re-encryption migration must be performed manually before restarting with a new key. Document this prominently in `.env.example`.

**Masking rule on API responses:** `api_key` is returned as `"••••" + last4`. `api_secret` is never returned — it is write-only. Credentials are decrypted inside the server process only when constructing a `TradingClient`.

---

## API Endpoints

### Broker Accounts CRUD

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/broker-accounts` | List all accounts (keys masked) |
| POST | `/api/broker-accounts` | Create account `{label, api_key, api_secret, account_type}` |
| PATCH | `/api/broker-accounts/{id}` | Update label or account_type only |
| PUT | `/api/broker-accounts/{id}/credentials` | Replace api_key + api_secret (re-encrypts) |
| DELETE | `/api/broker-accounts/{id}` | Delete account; cascades strategy_accounts |
| GET | `/api/broker-accounts/{id}/status` | Live connectivity test via TradingClient |

### Strategy Account Assignments

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/strategies/{name}/accounts` | List accounts assigned to strategy |
| POST | `/api/strategies/{name}/accounts` | Assign account `{account_id, enabled}` |
| PATCH | `/api/strategies/{name}/accounts/{id}` | Toggle enabled `{enabled: bool}` |
| DELETE | `/api/strategies/{name}/accounts/{id}` | Unassign account |

---

## Engine Changes (`server/engine.py`)

```python
async def run_tick():
    strategies = db.get_strategies()  # returns all; engine checks enabled

    for strat in strategies:
        if not strat["enabled"]:
            continue

        accounts = db.get_strategy_accounts(strat["name"])  # returns enabled pairs only
        if not accounts:
            continue

        for acct in accounts:
            client = alpaca_client.get_trading_client(
                acct["api_key"],    # decrypted in db layer
                acct["api_secret"], # decrypted in db layer
                paper=(acct["account_type"] == "paper"),
            )
            try:
                summary = client.get_account_summary()
                signal = run_strategy(strat, summary)
                if signal:
                    client.submit_market_order(signal)
            except Exception as e:
                log.warning("tick error strat=%s acct=%d: %s", strat["name"], acct["id"], e)
                continue
```

- Decryption happens in `db.get_strategy_accounts()` — engine receives plaintext credentials
- `get_trading_client()` is a pure factory in `alpaca_client.py` — no global state mutation
- The existing global `trading()` / `_data` clients remain for single-account endpoints (`GET /api/account`, market chip) until migrated in a future phase

---

## Frontend Changes

### API Keys page (`apikeys.html` + `initApiKeys()`)

Replaces the current single-account status card with:

- **Account cards grid** — one card per broker account: label, type badge, masked key, created date, "Test Connection" button (hits `/api/broker-accounts/{id}/status`)
- **Add Account modal** — Label, API Key, API Secret, Account Type (paper/live); submits POST, re-renders grid
- **Edit modal** — label and account type only
- **Rotate Credentials modal** — separate modal for replacing api_key + api_secret; hits PUT endpoint
- **Delete button** — confirmation modal listing any strategy assignments that will be removed (via CASCADE); user must confirm before DELETE is sent. The delete is not blocked — CASCADE handles cleanup.

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
| `server/db.py` | Add `broker_accounts` + `strategy_accounts` tables, `get_conn()` helper with FK pragma, CRUD functions, startup migration |
| `server/alpaca_client.py` | Add `get_trading_client(api_key, api_secret, paper)` pure factory function |
| `server/engine.py` | Replace single-client loop with per-(strategy, account) loop |
| `server/main.py` | Add 10 new endpoints; `DB_SECRET_KEY` validation on startup |
| `server/static/apikeys.html` | Full CRUD account management UI |
| `server/static/app.js` | Rewrite `initApiKeys()`; update `initBots()` for expandable rows |
| `.env.example` | Document `DB_SECRET_KEY`, key rotation warning |

---

## Out of Scope (Future Phase)

- Migration tooling for `DB_SECRET_KEY` rotation
- Multi-broker support for `/api/account` dashboard widget (still uses global client)
- Non-Alpaca brokers
