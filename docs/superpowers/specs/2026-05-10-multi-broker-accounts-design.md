# Multi-Broker Account Support — Design Spec

**Date:** 2026-05-10
**Status:** Approved (post-review revision 4)

---

## Goal

Add support for multiple broker accounts so that strategies can be independently assigned to and executed on one or more Alpaca accounts, with per-(strategy, account) enable/disable control.

---

## Architecture

A two-table broker account system is added to the existing SQLite database. `broker_accounts` stores Fernet-encrypted credentials for each brokerage connection. `strategy_accounts` is a many-to-many junction table mapping strategies to accounts, with a per-pair `enabled` flag.

The existing `strategies.enabled` column remains the global master switch. A `crypto.py` module handles all encryption/decryption — the DB layer stores ciphertext only, decryption occurs in `engine.py` at the moment a per-account client is constructed.

On startup, if `ALPACA_API_KEY` and `ALPACA_API_SECRET` are both non-blank in `.env`, they are migrated into `broker_accounts` as the Default account (id=1). The trading engine gains a per-account inner loop around the existing per-strategy logic; all existing logic (clock check, kill switch, risk checks, position sizing, signal logging, notifications) is preserved verbatim.

---

## `server/crypto.py` (new file)

All Fernet operations live here. No other module imports `Fernet` directly.

```python
from cryptography.fernet import Fernet
import os, logging

log = logging.getLogger(__name__)
_fernet: Fernet | None = None

def init_crypto() -> None:
    """Load and validate DB_SECRET_KEY. No-op if key is absent — encrypt()/decrypt() will raise instead."""
    global _fernet
    raw = os.environ.get("DB_SECRET_KEY", "")
    if not raw:
        log.warning("DB_SECRET_KEY not set — broker credential encryption unavailable.")
        return
    try:
        _fernet = Fernet(raw.encode())
        log.info("DB_SECRET_KEY loaded and validated.")
    except Exception:
        raise RuntimeError(
            "DB_SECRET_KEY is not a valid Fernet key. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

def generate_key() -> str:
    """Generate a new Fernet key. Used by setup_complete() on first run."""
    return Fernet.generate_key().decode()

def encrypt(plaintext: str) -> str:
    if _fernet is None:
        raise RuntimeError("crypto not initialised — DB_SECRET_KEY missing or invalid")
    return _fernet.encrypt(plaintext.encode()).decode()

def decrypt(ciphertext: str) -> str:
    if _fernet is None:
        raise RuntimeError("crypto not initialised — DB_SECRET_KEY missing or invalid")
    return _fernet.decrypt(ciphertext.encode()).decode()
```

`init_crypto()` is called in `main.py`'s lifespan startup handler **before** `db.init_db()`. Order matters: `init_db()` runs the startup `.env` migration which calls `crypto.encrypt()` — if `init_crypto()` runs after, `_fernet` will be `None` and the migration crashes.

```python
async def lifespan(app: FastAPI):
    crypto.init_crypto()  # must be first
    db.init_db()
    ...
```

It is a no-op (warning only) when `DB_SECRET_KEY` is absent, allowing the setup wizard to start. `encrypt()` and `decrypt()` fail fast with a clear error if called before a key is set.

**Key rotation warning:** Changing `DB_SECRET_KEY` renders all existing encrypted credentials unreadable. A re-encryption migration must be performed manually before restarting with a new key. Documented in `.env.example` (see Files Modified).

---

## Database Schema

### Connection Helper

Rename the existing `conn()` context manager in `server/db.py` to `get_conn()` and execute `PRAGMA foreign_keys = ON` immediately after `sqlite3.connect()`. Update **all** existing call sites (`with conn()` → `with get_conn()`):

- 15 call sites in `server/db.py`
- 4 call sites in `server/auth.py` (line 6 imports `conn` directly: `from .db import conn, init_db` — change to `from .db import get_conn, init_db`; update lines 31, 39, 86, 94)

Total: 19 call sites across 2 files.

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

### New Tables (added to `init_db()`)

```sql
CREATE TABLE IF NOT EXISTS broker_accounts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  label        TEXT NOT NULL UNIQUE,
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

`updated_at` is set by the application layer on every PATCH and PUT — not via a SQLite trigger.

### Startup .env Migration (inside `init_db()`)

Only runs if both `ALPACA_API_KEY` and `ALPACA_API_SECRET` env vars are non-blank. `account_type` is read from `ALPACA_ACCOUNT_TYPE` env var (defaulting to `'paper'`). Both credentials are encrypted via `crypto.encrypt()` before insertion.

```sql
INSERT INTO broker_accounts (id, label, api_key, api_secret, account_type)
VALUES (1, 'Default', ?, ?, ?)
ON CONFLICT(id) DO NOTHING;
```

---

## DB Helper Functions (additions to `server/db.py`)

### Broker Accounts

```python
def create_broker_account(label: str, api_key_enc: str, api_secret_enc: str, account_type: str) -> int:
    """Insert new account. Returns new row id. Raises IntegrityError if label not unique."""
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO broker_accounts (label, api_key, api_secret, account_type) VALUES (?,?,?,?)",
            (label, api_key_enc, api_secret_enc, account_type)
        )
        return cur.lastrowid

def get_broker_accounts() -> list[dict]:
    """Return all accounts with ciphertext api_key (masking applied in main.py)."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, label, api_key, account_type, created_at, updated_at FROM broker_accounts ORDER BY id"
        )]

def get_broker_account(account_id: int) -> dict | None:
    """Return single account or None."""
    with get_conn() as c:
        r = c.execute(
            "SELECT id, label, api_key, account_type, created_at, updated_at FROM broker_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        return dict(r) if r else None

def update_broker_account(account_id: int, *, label: str | None = None, account_type: str | None = None) -> None:
    """Update label and/or account_type. Sets updated_at to UTC ISO string."""
    from datetime import datetime, timezone
    fields, vals = [], []
    if label is not None:
        fields.append("label=?"); vals.append(label)
    if account_type is not None:
        fields.append("account_type=?"); vals.append(account_type)
    if not fields:
        raise ValueError("at least one of label or account_type required")
    fields.append("updated_at=?"); vals.append(datetime.now(timezone.utc).isoformat())
    vals.append(account_id)
    with get_conn() as c:
        c.execute(f"UPDATE broker_accounts SET {', '.join(fields)} WHERE id=?", vals)

def update_broker_credentials(account_id: int, api_key_enc: str, api_secret_enc: str) -> None:
    """Replace encrypted credentials. Sets updated_at to UTC ISO string."""
    from datetime import datetime, timezone
    with get_conn() as c:
        c.execute(
            "UPDATE broker_accounts SET api_key=?, api_secret=?, updated_at=? WHERE id=?",
            (api_key_enc, api_secret_enc, datetime.now(timezone.utc).isoformat(), account_id)
        )

def delete_broker_account(account_id: int) -> None:
    """Delete account. CASCADE removes strategy_accounts rows."""
    with get_conn() as c:
        c.execute("DELETE FROM broker_accounts WHERE id=?", (account_id,))

def get_broker_account_assignments(account_id: int) -> list[str]:
    """Return strategy names assigned to this account (for delete-confirmation modal)."""
    with get_conn() as c:
        rows = c.execute(
            "SELECT strategy_name FROM strategy_accounts WHERE account_id=?", (account_id,)
        ).fetchall()
        return [r["strategy_name"] for r in rows]
```

### Strategy Accounts

```python
def get_strategy_accounts(strategy_name: str) -> list[dict]:
    """Return enabled (strategy, account) pairs with ciphertext credentials. Used by engine."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT sa.account_id AS id, ba.label, ba.api_key, ba.api_secret, ba.account_type
               FROM strategy_accounts sa
               JOIN broker_accounts ba ON ba.id = sa.account_id
               WHERE sa.strategy_name = ? AND sa.enabled = 1""",
            (strategy_name,)
        )]

def get_strategy_account_list(strategy_name: str) -> list[dict]:
    """Return all assigned accounts with enabled flag. Used by API endpoint."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT ba.id, ba.label, ba.account_type, sa.enabled, sa.created_at
               FROM strategy_accounts sa
               JOIN broker_accounts ba ON ba.id = sa.account_id
               WHERE sa.strategy_name = ?
               ORDER BY ba.id""",
            (strategy_name,)
        )]

def assign_strategy_account(strategy_name: str, account_id: int, enabled: bool) -> bool:
    """Assign account to strategy. Returns True if inserted, False if already assigned (no-op)."""
    with get_conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO strategy_accounts (strategy_name, account_id, enabled) VALUES (?,?,?)",
            (strategy_name, account_id, int(enabled))
        )
        return cur.rowcount > 0

def update_strategy_account_enabled(strategy_name: str, account_id: int, enabled: bool) -> bool:
    """Returns True if updated, False if (strategy_name, account_id) pair not found."""
    with get_conn() as c:
        cur = c.execute(
            "UPDATE strategy_accounts SET enabled=? WHERE strategy_name=? AND account_id=?",
            (int(enabled), strategy_name, account_id)
        )
        return cur.rowcount > 0

def unassign_strategy_account(strategy_name: str, account_id: int) -> None:
    with get_conn() as c:
        c.execute(
            "DELETE FROM strategy_accounts WHERE strategy_name=? AND account_id=?",
            (strategy_name, account_id)
        )
```

---

## `server/alpaca_client.py` — AccountClient

Add `AccountClient` class. Remove the proposed `get_trading_client()` factory — it is redundant given `AccountClient`.

```python
class AccountClient:
    """Per-account Alpaca client with the same interface as the module-level functions."""

    def __init__(self, api_key: str, api_secret: str, paper: bool):
        self._t = TradingClient(api_key, api_secret, paper=paper)
        self._d = StockHistoricalDataClient(api_key, api_secret)
        self._paper = paper

    def get_account_summary(self) -> dict:
        a = self._t.get_account()
        equity = float(a.equity)
        last_equity = float(a.last_equity)
        return {
            "status": str(a.status),
            "cash": float(a.cash),
            "equity": equity,
            "last_equity": last_equity,
            "buying_power": float(a.buying_power),
            "portfolio_value": float(a.portfolio_value),
            "day_pl": equity - last_equity,
            "day_pl_pct": ((equity - last_equity) / last_equity * 100) if last_equity else 0.0,
            "pattern_day_trader": bool(a.pattern_day_trader),
            "trading_blocked": bool(a.trading_blocked),
            "account_type": "paper" if self._paper else "live",
        }

    def get_day_trade_count(self) -> int:
        try:
            return int(self._t.get_account().daytrade_count or 0)
        except Exception:
            return 0

    def get_positions(self) -> list[dict]:
        out = []
        for p in self._t.get_all_positions():
            out.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": str(p.side).lower().replace("positionside.", ""),
            })
        return out

    def get_latest_quote(self, symbol: str) -> dict:
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol.upper())
        q = self._d.get_stock_latest_quote(req)[symbol.upper()]
        return {"bid": float(q.bid_price), "ask": float(q.ask_price)}

    def submit_market_order(self, symbol: str, side: str,
                            qty: float | None = None,
                            notional: float | None = None,
                            client_order_id: str | None = None) -> dict:
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty if not notional else None,
            notional=round(notional, 2) if notional else None,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        o = self._t.submit_order(req)
        return {
            "id": str(o.id),
            "symbol": o.symbol,
            "side": str(o.side).lower().replace("orderside.", ""),
            "qty": float(o.qty) if o.qty else None,
            "status": str(o.status).lower().replace("orderstatus.", ""),
        }
```

The return shape of `get_account_summary()` is identical to the existing module-level function (same 11 keys) so `risk.check_all()`, `risk.calc_qty()`, and `risk.status_summary()` work without modification.

`get_positions()` intentionally returns only 3 fields (`symbol`, `qty`, `side`) — enough for the engine's position-sizing dict. The full 9-field positions response for `/api/positions` continues to use the module-level `alpaca_client.get_positions()` and is not affected.

---

## API Endpoints

### Pydantic Models

```python
class BrokerAccountCreate(BaseModel):
    label: str
    api_key: str
    api_secret: str
    account_type: Literal["paper", "live"] = "paper"

class BrokerAccountPatch(BaseModel):
    label: str | None = None
    account_type: Literal["paper", "live"] | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> "BrokerAccountPatch":
        if self.label is None and self.account_type is None:
            raise ValueError("at least one of label or account_type must be provided")
        return self

class BrokerCredentialsUpdate(BaseModel):
    api_key: str
    api_secret: str

class StrategyAccountAssign(BaseModel):
    account_id: int
    enabled: bool = True

class StrategyAccountPatch(BaseModel):
    enabled: bool
```

### Broker Accounts CRUD

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/broker-accounts` | List all accounts; `api_key` masked as `"****" + last4`; `api_secret` omitted |
| GET | `/api/broker-accounts/{id}` | Single account (same masking); used to pre-populate edit modal |
| POST | `/api/broker-accounts` | Create account; encrypts both credentials before insert |
| PATCH | `/api/broker-accounts/{id}` | Update label / account_type; body: `BrokerAccountPatch` |
| PUT | `/api/broker-accounts/{id}/credentials` | Replace credentials; re-encrypts both; body: `BrokerCredentialsUpdate` |
| DELETE | `/api/broker-accounts/{id}` | Delete account + cascade |
| GET | `/api/broker-accounts/{id}/status` | Decrypt credentials, construct `AccountClient`, call `get_account_summary()`, return status |
| GET | `/api/broker-accounts/{id}/assignments` | Return list of strategy names; used by delete-confirmation modal |

**Masking helper** (in `main.py`):
```python
def _mask_account(row: dict) -> dict:
    row = dict(row)
    try:
        key_plain_last4 = crypto.decrypt(row["api_key"])[-4:]
        row["api_key"] = "****" + key_plain_last4
    except Exception:
        # Covers RuntimeError (crypto not initialised) and InvalidToken (wrong key / corruption)
        row["api_key"] = "****[key unavailable]"
    row.pop("api_secret", None)  # never returned
    return row
```

Note: `GET /api/broker-accounts/{id}/status` calls `crypto.decrypt()` in `main.py` directly — not via `db.py`. This is consistent with the crypto module contract (only `main.py` and `engine.py` call `crypto.decrypt()`).

`POST /api/strategies/{name}/accounts` calls `db.assign_strategy_account()` and returns HTTP 409 if it returns `False` (already assigned).

`PATCH /api/strategies/{name}/accounts/{id}` calls `db.update_strategy_account_enabled()` and returns HTTP 404 if it returns `False` (pair not found).

Deleting the Default account (id=1) is permitted — no guard is needed. CASCADE removes its strategy assignments; affected strategies will have no accounts and be skipped on the next tick until reassigned.

### Strategy Account Assignments

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/strategies/{name}/accounts` | List assigned accounts with `enabled` flag; body: via `db.get_strategy_account_list()` |
| POST | `/api/strategies/{name}/accounts` | Assign account; body: `StrategyAccountAssign` |
| PATCH | `/api/strategies/{name}/accounts/{id}` | Toggle `enabled`; body: `StrategyAccountPatch` |
| DELETE | `/api/strategies/{name}/accounts/{id}` | Unassign |

---

## Engine Changes (`server/engine.py`)

The per-account loop wraps the existing per-strategy logic. **All existing behaviour (clock check, kill switch, `risk.check_all`, `risk.calc_qty`, `db.log_signal`, `notifications`) is preserved verbatim.** Only the account iteration wrapper is new.

`client_cache` is declared **outside** the per-strategy loop so accounts shared by multiple strategies instantiate `AccountClient` only once per tick.

Structural pseudocode (existing unchanged sections omitted with comments):

```python
from . import crypto  # new import

def run_tick():
    global _last_run
    # ... existing: _last_run reset, clock fetch, market-open check ...

    # Kill switch check: reads from risk_settings DB table — no account fetch needed.
    # Replace the existing block:
    #   account = alpaca_client.get_account_summary()
    #   day_trade_count = _get_day_trade_count(account)
    #   risk_status = risk.status_summary(account, day_trade_count)
    #   _last_run["risk"] = risk_status
    #   if risk_status["kill_switch"]: return
    # With the simpler direct check:
    if risk.is_killed():
        _last_run["error"] = "kill switch active"
        log.warning("kill switch active; skipping tick")
        return
    # _last_run["risk"] is left None at tick start; it is not populated globally
    # since there is no single account anymore. The /api/risk endpoint is unchanged
    # (it continues to use the global alpaca_client for its own account fetch).

    # Per-account client cache — one AccountClient per account_id per tick
    client_cache: dict[int, tuple[AccountClient, dict, int, dict[str, float]]] = {}
    # value: (client, account_summary, day_trade_count, positions)

    for s in db.get_strategies():
        if not s["enabled"]:
            continue
        if s["name"] not in strategies.REGISTRY:
            continue
        cls = strategies.REGISTRY[s["name"]]
        if not cls.auto_trade:
            continue

        accounts = db.get_strategy_accounts(s["name"])  # enabled only, with ciphertext
        if not accounts:
            continue

        for acct in accounts:
            acct_id = acct["id"]

            # Build or reuse per-account client + data
            if acct_id not in client_cache:
                acct_client = AccountClient(
                    api_key=crypto.decrypt(acct["api_key"]),
                    api_secret=crypto.decrypt(acct["api_secret"]),
                    paper=(acct["account_type"] == "paper"),
                )
                try:
                    acct_summary = acct_client.get_account_summary()
                    acct_dtc = acct_client.get_day_trade_count()
                    acct_positions = {
                        p["symbol"]: (p["qty"] if p["side"] == "long" else -p["qty"])
                        for p in acct_client.get_positions()
                    }
                except Exception as e:
                    log.warning("acct %d init failed: %s", acct_id, e)
                    continue
                client_cache[acct_id] = (acct_client, acct_summary, acct_dtc, acct_positions)

            acct_client, account, day_trade_count, positions = client_cache[acct_id]

            try:
                strat = strategies.build(s["name"], s["params"])
                signals = strat.evaluate(positions)
            except Exception as e:
                log.exception("strategy %s acct %d failed", s["name"], acct_id)
                db.log_signal(s["name"], "-", "-", 0, f"error: {e}", None, "error")
                continue

            for sig in signals:
                # ... existing: risk.check_all(sig.symbol, sig.side, account, day_trade_count) ...
                # ... existing: get_latest_quote, risk.calc_qty ...
                # Submit via per-account client instead of module-level function
                order = acct_client.submit_market_order(
                    sig.symbol, sig.side,
                    qty=final_qty if not sig.notional else None,
                    notional=sig.notional,
                    client_order_id=client_oid,
                )
                # ... existing: db.log_signal, notifications.notify_trade ...
```

`get_latest_quote()` continues to use the global `alpaca_client.data()` client — market data is not account-specific. The module-level `get_latest_quote()` call in the existing engine is unchanged.

The global `alpaca_client.get_account_summary()` and `alpaca_client.get_positions()` calls at the top of the current `run_tick()` are removed. The kill switch check uses `risk.is_killed()` directly (DB read, no account needed). `_last_run["risk"]` is no longer populated at the top of the tick; the `GET /api/engine` response will have `"risk": null`. The `GET /api/risk` endpoint is unchanged and continues to use the global single-account client.

The error-path inside the per-strategy loop must still append to `_last_run["ran"]` — the existing behaviour (`_last_run["ran"].append({"strategy": s["name"], "error": str(e)})`) is preserved unchanged inside the `except` block. The pseudocode omits this line for brevity but it must not be removed.

---

## Setup Wizard Update (`server/main.py`)

`POST /api/setup/complete` currently writes `.env` via `env_path.write_text(env_content)`. It must:

1. Read the existing `.env` to preserve `DB_SECRET_KEY` if already present.
2. Generate a new key (via `crypto.generate_key()`) only if absent.
3. Include `DB_SECRET_KEY` in the written content.

```python
def _read_env_key(name: str) -> str:
    try:
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return ""

# Inside setup_complete():
existing_secret = os.environ.get("DB_SECRET_KEY") or _read_env_key("DB_SECRET_KEY")
db_secret = existing_secret or crypto.generate_key()

endpoint = ("https://paper-api.alpaca.markets" if body.account_type == "paper"
            else "https://api.alpaca.markets")

env_content = (
    f"ALPACA_API_KEY={body.api_key}\n"
    f"ALPACA_API_SECRET={body.api_secret}\n"
    f"ALPACA_ENDPOINT={endpoint}/v2\n"
    f"ALPACA_ACCOUNT_TYPE={body.account_type}\n"
    f"DB_SECRET_KEY={db_secret}\n"
)
env_path.write_text(env_content)
os.environ["DB_SECRET_KEY"] = db_secret
crypto.init_crypto()  # re-initialise with the (possibly new) key
```

`_read_env_key` reads the current `.env` file and returns the value for a given key, or `""` if the file is missing or the key is absent. This prevents overwriting an existing `DB_SECRET_KEY` on subsequent setup runs. The `endpoint` variable is computed from `body.account_type` (same as the existing `setup_complete` code) — `SetupCompleteIn` has no `endpoint` field and is not changed.

---

## Frontend Changes

### API Keys page (`apikeys.html` + `initApiKeys()`)

Replaces the current single-account status card with:

- **Account cards grid** — one card per broker account: label, type badge, masked key (`****last4`), created date, "Test Connection" button (hits `GET /api/broker-accounts/{id}/status`)
- **Add Account modal** — Label, API Key, API Secret, Account Type (paper/live); submits POST, re-renders grid
- **Edit modal** — pre-populated via `GET /api/broker-accounts/{id}`; updates label and account type only via PATCH
- **Rotate Credentials modal** — separate modal for replacing api_key + api_secret; hits PUT `/credentials` endpoint
- **Delete button** — fetches `GET /api/broker-accounts/{id}/assignments`; shows confirmation modal listing affected strategy names (informational, not a block); then sends DELETE; re-renders grid on success

### Bots page (`bots.html` + `initBots()`)

Strategy rows gain an expand toggle. Expanded sub-table:

```
▼ SMACrossover                    [global toggle]
   └ Default (Paper)   enabled    [per-account toggle]
   └ Live Account      disabled   [per-account toggle]
   └ [+ Assign Account]
```

- Global toggle controls `strategies.enabled` — disabling greys out all sub-rows
- Per-account toggle hits `PATCH /api/strategies/{name}/accounts/{id}`
- "Assign Account" opens a picker modal; lists broker accounts not yet assigned to this strategy; submits POST with `enabled: true`
- Unassign via × button on each sub-row hits DELETE

### Unchanged pages

Dashboard, Performance, Positions, Balances, Logs, Risk, Settings, Backtesting.

---

## Files Modified

| File | Change |
|------|--------|
| `server/crypto.py` | **Create** — `init_crypto()`, `generate_key()`, `encrypt()`, `decrypt()` |
| `server/auth.py` | Update `from .db import conn` → `get_conn`; rename 4 call sites |
| `server/db.py` | Rename `conn()` → `get_conn()` (15 call sites); add new tables + 12 CRUD functions; startup migration |
| `server/alpaca_client.py` | Add `AccountClient` class |
| `server/engine.py` | Add per-account loop with `client_cache`; preserve all existing logic |
| `server/main.py` | Call `init_crypto()` in lifespan; add 11 new endpoints + Pydantic models; update `setup_complete` |
| `server/static/apikeys.html` | Full CRUD account management UI |
| `server/static/app.js` | Rewrite `initApiKeys()`; update `initBots()` for expandable rows |
| `requirements.txt` | Add `cryptography>=41.0` |
| `.env.example` | **Create** — all keys stubbed; `DB_SECRET_KEY` rotation warning as comment block (see below) |

### `.env.example` key rotation comment block

```
# DB_SECRET_KEY — Fernet encryption key for broker credentials stored in the database.
# Generate once with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# WARNING: Changing this key makes all existing broker credentials in the database unreadable.
# If you must rotate the key, re-encrypt all stored credentials first (manual migration required).
DB_SECRET_KEY=
```

---

## Out of Scope (Future Phase)

- Migration tooling for `DB_SECRET_KEY` rotation (re-encrypt all rows with new key)
- Multi-broker support for `/api/account` dashboard widget (still uses global client)
- Non-Alpaca brokers
