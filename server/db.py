import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    params_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    reason TEXT,
    order_id TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS risk_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_perf (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL,
    notional REAL,
    entry_price REAL,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts DESC);
CREATE INDEX IF NOT EXISTS idx_perf_strategy ON strategy_perf(strategy, date DESC);

-- Tracks open buy positions so sells can be matched back for P&L recording.
-- Rows are inserted on buy fill and deleted (FIFO) on matching sell fill.
CREATE TABLE IF NOT EXISTS open_trades (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at  TEXT NOT NULL,
    strategy   TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    account_id INTEGER,
    qty        REAL NOT NULL,
    fill_price REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_open_trades_lookup
    ON open_trades(strategy, symbol, account_id, opened_at ASC);

CREATE TABLE IF NOT EXISTS symbol_blacklist (
  symbol     TEXT PRIMARY KEY,
  added_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS broker_accounts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  label        TEXT NOT NULL UNIQUE,
  api_key      TEXT NOT NULL,
  api_secret   TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS backtest_runs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at        TEXT NOT NULL,
  name              TEXT,
  strategy          TEXT NOT NULL,
  symbols           TEXT NOT NULL,
  start_date        TEXT NOT NULL,
  end_date          TEXT NOT NULL,
  initial_capital   REAL NOT NULL,
  position_size_pct REAL NOT NULL,
  commission_pct    REAL NOT NULL,
  slippage_pct      REAL NOT NULL,
  total_return_pct  REAL,
  max_drawdown_pct  REAL,
  win_rate_pct      REAL,
  sharpe_ratio      REAL,
  total_trades      INTEGER,
  equity_curve      TEXT,
  trades            TEXT
);

CREATE TABLE IF NOT EXISTS account_settings (
  account_id  INTEGER PRIMARY KEY REFERENCES broker_accounts(id) ON DELETE CASCADE,
  kill_switch INTEGER NOT NULL DEFAULT 0,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watchlists (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  symbols    TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS price_alerts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol       TEXT NOT NULL,
  direction    TEXT NOT NULL CHECK(direction IN ('above', 'below')),
  target_price REAL NOT NULL,
  note         TEXT NOT NULL DEFAULT '',
  triggered    INTEGER NOT NULL DEFAULT 0,
  triggered_at TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL DEFAULT (datetime('now')),
  category   TEXT NOT NULL,
  action     TEXT NOT NULL,
  detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);

CREATE TABLE IF NOT EXISTS crypto_cost_basis (
  account_id  INTEGER NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  symbol      TEXT NOT NULL,
  qty         REAL NOT NULL DEFAULT 0,
  cost        REAL NOT NULL DEFAULT 0,
  realized_pnl REAL NOT NULL DEFAULT 0,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS issued_licenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT UNIQUE NOT NULL,
    buyer_email TEXT NOT NULL,
    license_key TEXT NOT NULL,
    issued_at   TEXT NOT NULL DEFAULT (datetime('now')),
    revoked     INTEGER NOT NULL DEFAULT 0,
    resent_at   TEXT
);

CREATE TABLE IF NOT EXISTS download_tokens (
    token           TEXT PRIMARY KEY,
    buyer_email     TEXT NOT NULL,
    license_key     TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at      TEXT NOT NULL,
    attempts_remaining INTEGER NOT NULL DEFAULT 3,
    exhausted       INTEGER NOT NULL DEFAULT 0
);

-- ── Execution ledger (strategy-rebuild spec §4.2, §19.5) ─────────────────────
-- Additive, decimal-safe order/fill accounting. Money and quantities are stored
-- as canonical decimal TEXT (never REAL). Acknowledgement is not a fill.

CREATE TABLE IF NOT EXISTS execution_orders (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id         INTEGER NOT NULL,
    strategy           TEXT NOT NULL,          -- owner/source (strategy, 'manual', 'webhook', 'take_profit', ...)
    client_order_id    TEXT NOT NULL,
    broker_order_id    TEXT,                   -- bound on acknowledgement
    symbol             TEXT NOT NULL,
    side               TEXT NOT NULL CHECK (side IN ('buy','sell')),
    order_type         TEXT NOT NULL,
    requested_qty      TEXT,                   -- decimal text, xor requested_notional
    requested_notional TEXT,
    state              TEXT NOT NULL DEFAULT 'INTENT_PERSISTED',
    last_error         TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    UNIQUE (account_id, client_order_id),
    CHECK (requested_qty IS NULL OR requested_qty NOT GLOB '*[eE]*'),
    CHECK (requested_notional IS NULL OR requested_notional NOT GLOB '*[eE]*')
);
CREATE INDEX IF NOT EXISTS idx_exec_orders_acct_state ON execution_orders(account_id, state);
CREATE INDEX IF NOT EXISTS idx_exec_orders_strat ON execution_orders(strategy, account_id, symbol);
CREATE UNIQUE INDEX IF NOT EXISTS uq_exec_orders_broker
    ON execution_orders(account_id, broker_order_id)
    WHERE broker_order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS execution_fills (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_order_id INTEGER NOT NULL REFERENCES execution_orders(id),
    account_id         INTEGER NOT NULL,
    broker_fill_id     TEXT NOT NULL,          -- stable broker trade id (idempotency key)
    qty                TEXT NOT NULL,          -- decimal text
    price              TEXT NOT NULL,          -- decimal text
    fee                TEXT NOT NULL DEFAULT '0',
    fee_currency       TEXT NOT NULL DEFAULT 'USD',
    filled_at          TEXT NOT NULL,          -- UTC ISO-8601 with microseconds
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    UNIQUE (account_id, broker_fill_id),
    CHECK (qty NOT GLOB '*[eE]*' AND price NOT GLOB '*[eE]*' AND fee NOT GLOB '*[eE]*')
);
CREATE INDEX IF NOT EXISTS idx_exec_fills_order ON execution_fills(execution_order_id);

CREATE TABLE IF NOT EXISTS fee_adjustments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_fill_id  INTEGER NOT NULL REFERENCES execution_fills(id),
    fee                TEXT NOT NULL,          -- signed decimal text (append-only; fills are immutable)
    fee_currency       TEXT NOT NULL DEFAULT 'USD',
    reason             TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    CHECK (fee NOT GLOB '*[eE]*')
);

CREATE TABLE IF NOT EXISTS position_lots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id         INTEGER NOT NULL,
    strategy           TEXT NOT NULL,
    symbol             TEXT NOT NULL,
    opening_fill_id    INTEGER REFERENCES execution_fills(id),
    original_qty       TEXT NOT NULL,          -- decimal text
    remaining_qty      TEXT NOT NULL,          -- decimal text
    unit_cost          TEXT NOT NULL,          -- decimal text, includes allocated entry fees
    opened_at          TEXT NOT NULL,
    closed_at          TEXT,
    provenance         TEXT NOT NULL DEFAULT 'verified',  -- verified | legacy_verified | legacy_unverified | external
    CHECK (original_qty NOT GLOB '*[eE]*' AND remaining_qty NOT GLOB '*[eE]*' AND unit_cost NOT GLOB '*[eE]*')
);
CREATE INDEX IF NOT EXISTS idx_lots_owner ON position_lots(strategy, account_id, symbol);

CREATE TABLE IF NOT EXISTS lot_matches (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    closing_fill_id    INTEGER NOT NULL REFERENCES execution_fills(id),
    opening_lot_id     INTEGER NOT NULL REFERENCES position_lots(id),
    matched_qty        TEXT NOT NULL,
    entry_price        TEXT NOT NULL,
    exit_price         TEXT NOT NULL,
    entry_cost         TEXT NOT NULL DEFAULT '0',
    exit_cost          TEXT NOT NULL DEFAULT '0',
    net_pnl            TEXT NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    UNIQUE (closing_fill_id, opening_lot_id),
    CHECK (matched_qty NOT GLOB '*[eE]*' AND net_pnl NOT GLOB '*[eE]*')
);

CREATE TABLE IF NOT EXISTS reconciliation_snapshots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id         INTEGER NOT NULL,
    symbol             TEXT NOT NULL,
    broker_qty         TEXT NOT NULL,
    internal_qty       TEXT NOT NULL,
    delta              TEXT NOT NULL,
    status             TEXT NOT NULL,          -- VERIFIED | DUST | FROZEN
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);
CREATE INDEX IF NOT EXISTS idx_recon_acct ON reconciliation_snapshots(account_id, symbol);

CREATE TABLE IF NOT EXISTS portfolio_risk_state (
    key                TEXT PRIMARY KEY,       -- high_water_mark, daily_baseline, weekly_baseline, hard_stop_triggered, ...
    value              TEXT NOT NULL,
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

-- Per-account fill-ingestion watermark + overlap cursor (spec §19.13). The poller
-- refetches a 24h overlap on every cycle; the watermark is the latest ingested
-- fill time so downtime beyond retention can be detected and frozen.
CREATE TABLE IF NOT EXISTS fill_watermarks (
    account_id         INTEGER PRIMARY KEY,
    watermark          TEXT NOT NULL,          -- latest ingested fill time (UTC ISO-8601)
    overlap_cursor     TEXT,                   -- start of the last overlap window
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now'))
);

-- Task 9: reproducible walk-forward research runs (spec §11, §12, §19.10). This is
-- research/reporting infrastructure ONLY — it never enables a strategy and never
-- touches live automation. `research_runs` holds one row per validation cycle
-- (frozen params, OOS/holdout summaries, the 12-criteria verdict, data fingerprint,
-- code revision); `research_attempts` records EVERY attempted configuration so the
-- §12.12 "every attempt visible" criterion is durably satisfied.
CREATE TABLE IF NOT EXISTS research_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    asset_class        TEXT NOT NULL,          -- 'stock' | 'crypto'
    label              TEXT,
    frozen_params      TEXT,                   -- JSON of the frozen parameter set
    oos_return         TEXT,                   -- canonical decimal text
    holdout_summary    TEXT,                   -- JSON
    criteria           TEXT,                   -- JSON of the 12-criteria verdict
    overall_pass       INTEGER NOT NULL DEFAULT 0,
    data_fingerprint   TEXT,
    code_revision      TEXT,
    geometry           TEXT                    -- JSON of the fold geometry used
);

CREATE TABLE IF NOT EXISTS research_attempts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             INTEGER,                -- nullable: streamed attempts may precede the run row
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f000Z','now')),
    role               TEXT NOT NULL,          -- 'training' | 'validation' | 'holdout'
    params             TEXT NOT NULL,          -- JSON
    window_start       TEXT,
    window_end         TEXT,
    from_cash          INTEGER NOT NULL DEFAULT 1,
    net_return         TEXT,
    calmar             TEXT,
    max_drawdown       TEXT,
    turnover           TEXT
);
CREATE INDEX IF NOT EXISTS idx_research_attempts_run ON research_attempts(run_id, role);
"""

RISK_DEFAULTS = {
    "kill_switch":             "false",
    "max_daily_loss_pct":      "2.0",
    "max_day_trades":          "3",
    "position_size_mode":      "fixed",
    "position_size_pct":       "2.0",
    "max_position_pct":        "10.0",
    "trading_mode":            "paper",
    # Extended guards
    "consecutive_loss_limit":  "0",     # 0 = disabled
    "weekly_loss_limit_pct":   "0",     # 0 = disabled
    "max_orders_per_day":      "0",     # 0 = disabled
    "max_open_positions":      "10",    # 0 = disabled
    "max_symbol_exposure_pct": "0",     # 0 = disabled
    "trading_hours_start":     "",      # "" = disabled (HH:MM ET)
    "trading_hours_end":       "",      # "" = disabled (HH:MM ET)
    "take_profit_pct":         "0",     # 0 = disabled
    # Crypto-specific settings (Binance / 24-7 brokers) — fully independent of stock settings
    "max_daily_loss_pct_crypto":      "5.0",
    "max_position_pct_crypto":        "20.0",
    "take_profit_pct_crypto":         "0",    # 0 = disabled
    "max_open_positions_crypto":      "10",   # 0 = disabled
    "max_symbol_exposure_pct_crypto": "0",    # 0 = disabled
    "consecutive_loss_limit_crypto":  "0",    # 0 = disabled
    "weekly_loss_limit_pct_crypto":   "0",    # 0 = disabled
    "max_orders_per_day_crypto":      "0",    # 0 = disabled
    "position_size_mode_crypto":      "fixed",
    "position_size_pct_crypto":       "5.0",
}


def _migrate_env_account() -> None:
    """Insert Default broker account from .env on first run. Idempotent."""
    import os
    from . import crypto
    api_key = os.environ.get("ALPACA_API_KEY", "").strip()
    api_secret = os.environ.get("ALPACA_API_SECRET", "").strip()
    if not api_key or not api_secret:
        return
    account_type = os.environ.get("ALPACA_ACCOUNT_TYPE", "paper").strip()
    if account_type not in ("paper", "live"):
        account_type = "paper"
    try:
        key_enc = crypto.encrypt(api_key)
        secret_enc = crypto.encrypt(api_secret)
    except RuntimeError:
        return  # crypto not initialised — skip migration silently
    label = "Alpaca Paper" if account_type == "paper" else "Alpaca Live"
    with get_conn() as c:
        c.execute(
            """INSERT INTO broker_accounts (id, label, api_key, api_secret, account_type)
               VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(id) DO NOTHING""",
            (label, key_enc, secret_enc, account_type)
        )
        # rename legacy 'Default' label for existing installs
        c.execute(
            "UPDATE broker_accounts SET label=? WHERE id=1 AND label='Default'",
            (label,)
        )


def _migrate_broker_column() -> None:
    """Add broker column to broker_accounts if it doesn't exist (one-time)."""
    with get_conn() as c:
        cols = [row[1] for row in c.execute("PRAGMA table_info(broker_accounts)")]
        if "broker" not in cols:
            c.execute("ALTER TABLE broker_accounts ADD COLUMN broker TEXT NOT NULL DEFAULT 'alpaca'")


def init_db():
    with get_conn() as c:
        c.executescript(SCHEMA)
    # seed risk defaults without overwriting existing values
    with get_conn() as c:
        for k, v in RISK_DEFAULTS.items():
            c.execute(
                "INSERT OR IGNORE INTO risk_settings(key, value) VALUES(?,?)", (k, v)
            )
    _migrate_broker_column()
    _migrate_env_account()
    # Migration: add account_id to signals if missing
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(signals)")]
        if "account_id" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN account_id INTEGER DEFAULT NULL")
        if "blocked" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
    # Migration: add account_id to strategy_perf if missing
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(strategy_perf)")]
        if "account_id" not in cols:
            c.execute("ALTER TABLE strategy_perf ADD COLUMN account_id INTEGER DEFAULT NULL")
    # Migration: add active_start / active_end to strategies if missing
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(strategies)")]
        if "active_start" not in cols:
            c.execute("ALTER TABLE strategies ADD COLUMN active_start TEXT DEFAULT NULL")
        if "active_end" not in cols:
            c.execute("ALTER TABLE strategies ADD COLUMN active_end TEXT DEFAULT NULL")
    # Migration: add per-account active_start / active_end to strategy_accounts if missing
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(strategy_accounts)")]
        if "active_start" not in cols:
            c.execute("ALTER TABLE strategy_accounts ADD COLUMN active_start TEXT DEFAULT NULL")
        if "active_end" not in cols:
            c.execute("ALTER TABLE strategy_accounts ADD COLUMN active_end TEXT DEFAULT NULL")
    # Migration: create watchlists table if missing (added after initial schema)
    with get_conn() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "watchlists" not in tables:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS watchlists (
                  id         INTEGER PRIMARY KEY AUTOINCREMENT,
                  name       TEXT NOT NULL UNIQUE,
                  symbols    TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL DEFAULT (datetime('now')),
                  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)
    # Migration: create price_alerts table if missing
    with get_conn() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "price_alerts" not in tables:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS price_alerts (
                  id         INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol     TEXT NOT NULL,
                  condition  TEXT NOT NULL,
                  price      REAL NOT NULL,
                  note       TEXT,
                  triggered  INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)
    # Migration: add symbol_breakdown column to backtest_runs if missing
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(backtest_runs)")]
        if "symbol_breakdown" not in cols:
            c.execute("ALTER TABLE backtest_runs ADD COLUMN symbol_breakdown TEXT DEFAULT NULL")

    # Migration: add is_benchmark column to backtest_runs if missing
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(backtest_runs)")]
        if "is_benchmark" not in cols:
            c.execute(
                "ALTER TABLE backtest_runs ADD COLUMN is_benchmark INTEGER NOT NULL DEFAULT 0"
            )

    # Migration (Task 7): add reproducibility metadata column to backtest_runs.
    # Stores provider, timeframe, adjustment/event policy, data fingerprint(s),
    # cost model, code revision, execution model, and end convention as JSON so a
    # run can be reproduced (spec §9/§10). Additive + nullable; older rows are NULL.
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(backtest_runs)")]
        if "reproducibility" not in cols:
            c.execute("ALTER TABLE backtest_runs ADD COLUMN reproducibility TEXT DEFAULT NULL")

    # Migration: add ai_explanation / filled_qty / sentiment_score to signals if missing
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(signals)")]
        if "ai_explanation" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN ai_explanation TEXT DEFAULT NULL")
        if "ai_provider" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN ai_provider TEXT DEFAULT NULL")
        if "ai_model" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN ai_model TEXT DEFAULT NULL")
        if "filled_qty" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN filled_qty REAL DEFAULT NULL")
        if "filled_price" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN filled_price REAL DEFAULT NULL")
        if "sentiment_score" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN sentiment_score REAL DEFAULT NULL")
    # Migration: create ai_tuning_log table if missing
    with get_conn() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "ai_tuning_log" not in tables:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS ai_tuning_log (
                  id               INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at       TEXT NOT NULL,
                  strategy         TEXT NOT NULL,
                  old_params       TEXT NOT NULL,
                  new_params       TEXT NOT NULL,
                  rationale        TEXT NOT NULL,
                  win_rate_before  REAL,
                  win_rate_after   REAL DEFAULT NULL,
                  ai_provider      TEXT DEFAULT NULL,
                  ai_model         TEXT DEFAULT NULL
                );
            """)
    # Migration: add ai_provider / ai_model columns to existing ai_tuning_log
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(ai_tuning_log)")]
        if "ai_provider" not in cols:
            c.execute("ALTER TABLE ai_tuning_log ADD COLUMN ai_provider TEXT DEFAULT NULL")
        if "ai_model" not in cols:
            c.execute("ALTER TABLE ai_tuning_log ADD COLUMN ai_model TEXT DEFAULT NULL")
    # Migration: create open_trades table if missing
    with get_conn() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "open_trades" not in tables:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS open_trades (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    opened_at  TEXT NOT NULL,
                    strategy   TEXT NOT NULL,
                    symbol     TEXT NOT NULL,
                    account_id INTEGER,
                    qty        REAL NOT NULL,
                    fill_price REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_open_trades_lookup
                    ON open_trades(strategy, symbol, account_id, opened_at ASC);
            """)
    # Migration: create sessions table for persistent login sessions
    with get_conn() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "sessions" not in tables:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token      TEXT PRIMARY KEY,
                    expires_at REAL NOT NULL
                );
            """)

    # Ledger schema versioning (Task 10, spec §19.8). The execution-ledger tables are
    # part of SCHEMA above (always created), so a freshly initialized DB is at the
    # current ledger schema version. Stamp it monotonically — never downgrade.
    _stamp_ledger_schema_version()


# Bump ONLY when a new ADDITIVE ledger migration step is added (kept in sync with
# server.migration.LEDGER_SCHEMA_VERSION).
LEDGER_SCHEMA_VERSION = 1
_LEDGER_SCHEMA_VERSION_KEY = "ledger_schema_version"


def get_ledger_schema_version() -> int:
    """Return the recorded ledger schema version (0 if never stamped)."""
    try:
        return int(get_app_config(_LEDGER_SCHEMA_VERSION_KEY, "0") or "0")
    except (TypeError, ValueError):
        return 0


def _stamp_ledger_schema_version() -> None:
    """Stamp the ledger schema version, monotonically (never downgrade)."""
    if get_ledger_schema_version() < LEDGER_SCHEMA_VERSION:
        set_app_config(_LEDGER_SCHEMA_VERSION_KEY, str(LEDGER_SCHEMA_VERSION))


def get_risk_settings() -> dict:
    with get_conn() as c:
        rows = c.execute("SELECT key, value FROM risk_settings").fetchall()
    base = dict(RISK_DEFAULTS)
    base.update({r["key"]: r["value"] for r in rows})
    return {
        "kill_switch":             base["kill_switch"] == "true",
        "max_daily_loss_pct":      float(base["max_daily_loss_pct"]),
        "max_day_trades":          int(base["max_day_trades"]),
        "position_size_mode":      base["position_size_mode"],
        "position_size_pct":       float(base["position_size_pct"]),
        "max_position_pct":        float(base["max_position_pct"]),
        "trading_mode":            base["trading_mode"],
        "consecutive_loss_limit":  int(base["consecutive_loss_limit"]),
        "weekly_loss_limit_pct":   float(base["weekly_loss_limit_pct"]),
        "max_orders_per_day":      int(base["max_orders_per_day"]),
        "max_open_positions":      int(base["max_open_positions"]),
        "max_symbol_exposure_pct": float(base["max_symbol_exposure_pct"]),
        "trading_hours_start":     base["trading_hours_start"],
        "trading_hours_end":       base["trading_hours_end"],
        "take_profit_pct":         float(base["take_profit_pct"]),
        # Crypto-specific settings (fully independent of stock)
        "max_daily_loss_pct_crypto":      float(base["max_daily_loss_pct_crypto"]),
        "max_position_pct_crypto":        float(base["max_position_pct_crypto"]),
        "take_profit_pct_crypto":         float(base["take_profit_pct_crypto"]),
        "max_open_positions_crypto":      int(base["max_open_positions_crypto"]),
        "max_symbol_exposure_pct_crypto": float(base["max_symbol_exposure_pct_crypto"]),
        "consecutive_loss_limit_crypto":  int(base["consecutive_loss_limit_crypto"]),
        "weekly_loss_limit_pct_crypto":   float(base["weekly_loss_limit_pct_crypto"]),
        "max_orders_per_day_crypto":      int(base["max_orders_per_day_crypto"]),
        "position_size_mode_crypto":      base["position_size_mode_crypto"],
        "position_size_pct_crypto":       float(base["position_size_pct_crypto"]),
    }


def set_risk_setting(key: str, value: str):
    if key not in RISK_DEFAULTS:
        raise ValueError(f"unknown risk key: {key}")
    with get_conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO risk_settings(key, value) VALUES(?,?)", (key, value)
        )


def get_app_config(key: str, default: str = "") -> str:
    with get_conn() as c:
        row = c.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_app_config(key: str, value: str):
    with get_conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO app_config(key, value) VALUES(?,?)", (key, value)
        )


def get_license_key() -> str:
    return get_app_config("license_key", "")


def set_license_key(key: str) -> None:
    # Instrumentation: the stored license_key has been mysteriously emptied more
    # than once, forcing the user to re-enter it. Clearing it is rare and always
    # significant, so when it happens we capture WHO did it (full stack trace) and
    # leave a durable audit row. This turns an invisible clobber into evidence.
    if not key or not key.strip():
        import logging, traceback
        stack = "".join(traceback.format_stack()[:-1])  # exclude this frame
        logging.getLogger("license").warning(
            "license_key cleared (set to empty). Caller stack:\n%s", stack,
        )
        try:
            # Record the FULL stack into the audit detail so the caller is captured
            # in the DB regardless of where process stdout/stderr goes.
            log_audit("license", "license key cleared", stack[-1500:])
        except Exception:
            pass
    set_app_config("license_key", key)


# ── Issued licenses (Lemon Squeezy automation) ────────────────────────────────

def add_issued_license(order_id: str, buyer_email: str, license_key: str) -> None:
    """Insert a new issued license. Silently ignores duplicate order_id."""
    with get_conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO issued_licenses (order_id, buyer_email, license_key) "
            "VALUES (?, ?, ?)",
            (order_id, buyer_email, license_key),
        )


def list_issued_licenses(search: str = "", page: int = 1,
                         per_page: int = 20) -> list[dict]:
    page = max(1, page)
    offset = (page - 1) * per_page
    with get_conn() as c:
        if search:
            rows = c.execute(
                "SELECT * FROM issued_licenses WHERE buyer_email LIKE ? "
                "ORDER BY issued_at DESC LIMIT ? OFFSET ?",
                (f"%{search}%", per_page, offset),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM issued_licenses ORDER BY issued_at DESC "
                "LIMIT ? OFFSET ?",
                (per_page, offset),
            ).fetchall()
    return [dict(r) for r in rows]


def count_issued_licenses(search: str = "") -> int:
    with get_conn() as c:
        if search:
            row = c.execute(
                "SELECT COUNT(*) FROM issued_licenses WHERE buyer_email LIKE ?",
                (f"%{search}%",),
            ).fetchone()
        else:
            row = c.execute("SELECT COUNT(*) FROM issued_licenses").fetchone()
    return row[0]


def get_issued_license(license_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM issued_licenses WHERE id=?", (license_id,)
        ).fetchone()
    return dict(row) if row else None


def revoke_issued_license(license_id: int) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE issued_licenses SET revoked=1 WHERE id=?", (license_id,)
        )


def update_resent_at(license_id: int) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE issued_licenses SET resent_at=datetime('now') WHERE id=?",
            (license_id,),
        )


# ── Download tokens ────────────────────────────────────────────────────────────

def create_download_token(token: str, buyer_email: str, license_key: str,
                           expires_hours: int = 72, max_attempts: int = 3) -> None:
    with get_conn() as c:
        c.execute(
            "INSERT INTO download_tokens (token, buyer_email, license_key, expires_at, attempts_remaining) "
            "VALUES (?, ?, ?, datetime('now', ? || ' hours'), ?)",
            (token, buyer_email, license_key, str(expires_hours), max_attempts),
        )


def consume_download_token(token: str) -> dict | None:
    """Validate token, decrement attempts, return row if valid. Returns None if invalid/expired/exhausted."""
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM download_tokens WHERE token=?", (token,)
        ).fetchone()
        if not row:
            return None
        row = dict(row)
        if row["exhausted"]:
            return None
        if row["attempts_remaining"] <= 0:
            c.execute("UPDATE download_tokens SET exhausted=1 WHERE token=?", (token,))
            return None
        # Check expiry
        expired = c.execute(
            "SELECT 1 FROM download_tokens WHERE token=? AND expires_at < datetime('now')", (token,)
        ).fetchone()
        if expired:
            return None
        # Decrement
        new_attempts = row["attempts_remaining"] - 1
        exhausted = 1 if new_attempts <= 0 else 0
        c.execute(
            "UPDATE download_tokens SET attempts_remaining=?, exhausted=? WHERE token=?",
            (new_attempts, exhausted, token),
        )
        row["attempts_remaining"] = new_attempts
        return row


def get_webhook_token() -> str:
    return get_app_config("webhook_token", "")

def set_webhook_token(token: str) -> None:
    set_app_config("webhook_token", token)

def rotate_webhook_token() -> str:
    import secrets
    token = secrets.token_hex(32)
    set_webhook_token(token)
    return token


# Fields stored encrypted in app_config
_ENCRYPTED_CONFIG_KEYS = {
    "email_pass", "telegram_token", "slack_webhook_url",
    "discord_webhook_url", "ai_claude_api_key", "lemon_signing_secret",
}

# Sentinel returned to the browser in place of a stored secret. When the UI sends
# this value back unchanged on save, the server keeps the existing secret (does not
# re-encrypt). A real new secret never equals this string.
SECRET_PLACEHOLDER = "********"


def _encrypt_config(value: str) -> str:
    """Encrypt a sensitive config value. Falls back to plaintext if crypto not initialised."""
    if not value:
        return value
    try:
        from . import crypto
        return crypto.encrypt(value)
    except Exception:
        return value


def _decrypt_config(value: str) -> str:
    """Decrypt a sensitive config value. Returns empty string on failure."""
    if not value:
        return value
    try:
        from . import crypto
        return crypto.decrypt(value)
    except Exception:
        # Value may be legacy plaintext — return as-is so existing installs don't break
        return value


def set_app_config_secure(key: str, value: str) -> None:
    """Store a config value, encrypting it if it's a sensitive key."""
    stored = _encrypt_config(value) if key in _ENCRYPTED_CONFIG_KEYS else value
    set_app_config(key, stored)


def get_app_config_secure(key: str, default: str = "") -> str:
    """Read a config value, decrypting it if it's a sensitive key."""
    raw = get_app_config(key, default)
    return _decrypt_config(raw) if key in _ENCRYPTED_CONFIG_KEYS else raw


def get_notification_settings() -> dict:
    keys = [
        "email_enabled", "email_to", "email_smtp", "email_port",
        "email_user", "email_pass", "telegram_enabled",
        "telegram_token", "telegram_chat_id",
        "slack_enabled", "slack_webhook_url",
        "discord_enabled", "discord_webhook_url",
        "notify_on_trade", "notify_on_block", "notify_daily_summary",
    ]
    defaults = {
        "email_enabled": "false", "email_port": "587",
        "telegram_enabled": "false",
        "slack_enabled": "false", "slack_webhook_url": "",
        "discord_enabled": "false", "discord_webhook_url": "",
        "notify_on_trade": "true", "notify_on_block": "true", "notify_daily_summary": "false",
    }
    with get_conn() as c:
        rows = c.execute(
            "SELECT key, value FROM app_config WHERE key IN ({})".format(
                ",".join("?" * len(keys))
            ),
            keys,
        ).fetchall()
    result = dict(defaults)
    result.update({r["key"]: r["value"] for r in rows})
    # Secrets must NOT leave the server in plaintext. Replace each stored secret with
    # a masked sentinel: "" if unset, else SECRET_PLACEHOLDER. The real value is only
    # used server-side (send_email_direct etc. read it via get_app_config_secure).
    # This also kills the old decrypt→reload→re-encrypt round-trip that corrupted
    # the email password.
    for k in _ENCRYPTED_CONFIG_KEYS:
        if k in result:
            result[k] = SECRET_PLACEHOLDER if result[k] not in (None, "") else ""
    for bk in ["email_enabled", "telegram_enabled", "slack_enabled", "discord_enabled",
                "notify_on_trade", "notify_on_block", "notify_daily_summary"]:
        result[bk] = result.get(bk, "") == "true"
    return result


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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_UNSET = object()  # sentinel — caller didn't provide the argument

def upsert_strategy(name: str, enabled: bool, params: dict = _UNSET,
                    active_start: str | None = _UNSET, active_end: str | None = _UNSET):
    with get_conn() as c:
        existing = c.execute("SELECT * FROM strategies WHERE name=?", (name,)).fetchone()
        if existing is None:
            # First insert — use provided values or safe defaults
            c.execute(
                """INSERT INTO strategies(name, enabled, params_json, active_start, active_end, updated_at)
                   VALUES(?,?,?,?,?,?)""",
                (name, 1 if enabled else 0,
                 json.dumps({} if params is _UNSET else params),
                 None if active_start is _UNSET else (active_start or None),
                 None if active_end   is _UNSET else (active_end   or None),
                 now_iso()),
            )
        else:
            # Partial update — only touch columns that were explicitly passed
            sets, vals = ["enabled=?", "updated_at=?"], [1 if enabled else 0, now_iso()]
            if params is not _UNSET:
                sets.append("params_json=?"); vals.append(json.dumps(params))
            if active_start is not _UNSET:
                sets.append("active_start=?"); vals.append(active_start or None)
            if active_end is not _UNSET:
                sets.append("active_end=?");   vals.append(active_end   or None)
            vals.append(name)
            c.execute(f"UPDATE strategies SET {', '.join(sets)} WHERE name=?", vals)


def get_strategies() -> list[dict]:
    with get_conn() as c:
        rows = c.execute("SELECT * FROM strategies ORDER BY name").fetchall()
    return [
        {
            "name":         r["name"],
            "enabled":      bool(r["enabled"]),
            "params":       json.loads(r["params_json"]),
            "active_start": r["active_start"],
            "active_end":   r["active_end"],
            "updated_at":   r["updated_at"],
        }
        for r in rows
    ]


def get_strategy(name: str) -> dict | None:
    with get_conn() as c:
        r = c.execute("SELECT * FROM strategies WHERE name=?", (name,)).fetchone()
    if not r:
        return None
    return {
        "name":         r["name"],
        "enabled":      bool(r["enabled"]),
        "params":       json.loads(r["params_json"]),
        "active_start": r["active_start"],
        "active_end":   r["active_end"],
        "updated_at":   r["updated_at"],
    }


def log_signal(strategy: str, symbol: str, side: str, qty: float, reason: str,
               order_id: str | None = None, status: str = "ok",
               blocked: bool = False, account_id: int | None = None,
               filled_qty: float | None = None, filled_price: float | None = None,
               sentiment_score: float | None = None) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO signals(ts, strategy, symbol, side, qty, reason, order_id, status,
                                   blocked, account_id, filled_qty, filled_price, sentiment_score)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now_iso(), strategy, symbol, side, qty, reason, order_id, status,
             int(blocked), account_id, filled_qty, filled_price, sentiment_score),
        )
        return cur.lastrowid


def recent_signals(limit: int = 100, since: str | None = None, until: str | None = None,
                   account_id: int | None = None) -> list[dict]:
    where, args = [], []
    if since:
        where.append("ts >= ?"); args.append(since)
    if until:
        where.append("ts <= ?"); args.append(until + "T23:59:59")
    if account_id is not None:
        where.append("account_id = ?"); args.append(account_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with get_conn() as c:
        rows = c.execute(
            f"SELECT * FROM signals {clause} ORDER BY id DESC LIMIT ?", (*args, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Performance analytics ──────────────────────────────────────────────────────

def performance_by_strategy() -> list[dict]:
    """Aggregate signal counts per strategy, joined with live enabled status."""
    with get_conn() as c:
        rows = c.execute("""
            SELECT
                sig.strategy,
                COUNT(*)                                               AS total,
                SUM(CASE WHEN sig.side='buy'       THEN 1 ELSE 0 END) AS buys,
                SUM(CASE WHEN sig.side='sell'      THEN 1 ELSE 0 END) AS sells,
                SUM(CASE WHEN sig.status='blocked' THEN 1 ELSE 0 END) AS blocked,
                SUM(CASE WHEN sig.status='error'   THEN 1 ELSE 0 END) AS errors,
                COUNT(DISTINCT sig.symbol)                             AS unique_symbols,
                MIN(sig.ts)                                            AS first_signal,
                MAX(sig.ts)                                            AS last_signal,
                COALESCE(st.enabled, 0)                               AS enabled
            FROM signals sig
            LEFT JOIN strategies st ON st.name = sig.strategy
            WHERE sig.strategy != 'manual'
            GROUP BY sig.strategy
            ORDER BY total DESC
        """).fetchall()
    return [dict(r) for r in rows]


def performance_by_strategy_account() -> list[dict]:
    """P&L grouped by (strategy, account_id) for attribution table."""
    with get_conn() as c:
        rows = c.execute("""
            SELECT
                s.strategy,
                s.account_id,
                ba.label  AS account_label,
                COUNT(*)  AS total_signals,
                SUM(CASE WHEN s.blocked=0 THEN 1 ELSE 0 END) AS executed,
                SUM(CASE WHEN s.blocked=1 THEN 1 ELSE 0 END) AS blocked
            FROM signals s
            LEFT JOIN broker_accounts ba ON ba.id = s.account_id
            WHERE s.strategy != 'manual'
            GROUP BY s.strategy, s.account_id
            ORDER BY s.strategy, s.account_id
        """).fetchall()
    return [dict(r) for r in rows]


def compare_paper_vs_live() -> dict:
    """Signal stats split by account_type (paper vs live) for the comparison panel."""
    with get_conn() as c:
        rows = c.execute("""
            SELECT
                COALESCE(ba.account_type, 'paper') AS account_type,
                COUNT(*)                            AS total_signals,
                SUM(CASE WHEN s.blocked=0 AND s.status NOT IN ('blocked','error') THEN 1 ELSE 0 END) AS executed,
                SUM(CASE WHEN s.blocked=1 THEN 1 ELSE 0 END)  AS blocked,
                SUM(CASE WHEN s.side='buy'  THEN 1 ELSE 0 END) AS buys,
                SUM(CASE WHEN s.side='sell' THEN 1 ELSE 0 END) AS sells,
                COUNT(DISTINCT s.strategy)   AS strategies_active,
                COUNT(DISTINCT s.symbol)     AS unique_symbols,
                MIN(s.ts)                    AS first_signal,
                MAX(s.ts)                    AS last_signal
            FROM signals s
            LEFT JOIN broker_accounts ba ON ba.id = s.account_id
            WHERE s.strategy NOT IN ('manual')
            GROUP BY account_type
        """).fetchall()
    result = {"paper": {}, "live": {}}
    for r in rows:
        result[r["account_type"]] = dict(r)
    return result


def top_symbols_overall(limit: int = 10) -> list[dict]:
    """Most traded symbols across all strategies."""
    with get_conn() as c:
        rows = c.execute("""
            SELECT
                symbol,
                COUNT(*)                                          AS total,
                SUM(CASE WHEN side='buy'  THEN 1 ELSE 0 END)     AS buys,
                SUM(CASE WHEN side='sell' THEN 1 ELSE 0 END)     AS sells,
                COUNT(DISTINCT strategy)                          AS strategies
            FROM signals
            WHERE status NOT IN ('blocked', 'error') AND symbol NOT IN ('-', '')
            GROUP BY symbol
            ORDER BY total DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def daily_signal_counts(days: int = 30) -> list[dict]:
    """Signal counts per calendar day for the past N days."""
    with get_conn() as c:
        rows = c.execute("""
            SELECT
                DATE(ts)                                                                           AS date,
                COUNT(*)                                                                           AS total,
                SUM(CASE WHEN side='buy'  AND status NOT IN ('blocked','error') THEN 1 ELSE 0 END) AS buys,
                SUM(CASE WHEN side='sell' AND status NOT IN ('blocked','error') THEN 1 ELSE 0 END) AS sells,
                SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END)                                 AS blocked
            FROM signals
            WHERE ts >= DATE('now', '-' || ? || ' days')
              AND symbol NOT IN ('-', '')
            GROUP BY DATE(ts)
            ORDER BY date ASC
        """, (days,)).fetchall()
    return [dict(r) for r in rows]


# ── Broker Accounts ───────────────────────────────────────────────────────────

def create_broker_account(label: str, api_key_enc: str, api_secret_enc: str, account_type: str, broker: str = "alpaca") -> int:
    """Insert new account. Returns new row id. Raises IntegrityError if label not unique."""
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO broker_accounts (label, api_key, api_secret, account_type, broker) VALUES (?,?,?,?,?)",
            (label, api_key_enc, api_secret_enc, account_type, broker)
        )
        return cur.lastrowid


def get_broker_accounts() -> list[dict]:
    """Return all accounts. api_secret excluded; api_key returned as ciphertext for masking in main.py."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, label, api_key, account_type, broker, created_at, updated_at FROM broker_accounts ORDER BY id"
        )]


def get_broker_account(account_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute(
            "SELECT id, label, api_key, account_type, broker, created_at, updated_at FROM broker_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        return dict(r) if r else None


def get_broker_account_credentials(account_id: int) -> dict | None:
    """Return encrypted api_key + api_secret plus metadata for internal use. Never send to clients."""
    with get_conn() as c:
        r = c.execute(
            "SELECT api_key, api_secret, account_type, broker FROM broker_accounts WHERE id=?", (account_id,)
        ).fetchone()
        return dict(r) if r else None


class SecretKeyMismatchError(RuntimeError):
    """Raised when DB_SECRET_KEY cannot decrypt stored broker credentials."""


def verify_secret_key_matches_credentials() -> None:
    """Fail loudly at startup if DB_SECRET_KEY can no longer decrypt stored broker
    credentials.

    Without this check a changed/lost DB_SECRET_KEY surfaces only as "API key
    invalid" errors in the UI — making a key-mismatch look like a broker problem.
    We try to decrypt each account's api_key; if a non-empty ciphertext fails to
    decrypt, the key does not match what encrypted the data.

    No-op (returns) when:
      - crypto is not initialised (no DB_SECRET_KEY set — separate, handled case)
      - there are no broker accounts, or none have a stored api_key
      - a stored api_key is legacy plaintext (decrypt fails but value isn't Fernet
        ciphertext — we only flag values that look like Fernet tokens, "gAAAAA…")
    """
    from . import crypto
    if crypto._fernet is None:
        return  # no key configured; encrypt/decrypt already guard this elsewhere

    accounts = get_broker_accounts()
    checked = 0
    for a in accounts:
        ciphertext = a.get("api_key") or ""
        if not ciphertext:
            continue
        # Fernet tokens are urlsafe-base64 starting with "gAAAAA". Skip anything
        # that clearly isn't encrypted (legacy plaintext keys) so we don't false-alarm.
        if not ciphertext.startswith("gAAAAA"):
            continue
        checked += 1
        try:
            crypto.decrypt(ciphertext)
            return  # at least one credential decrypts → key matches, all good
        except Exception:
            continue  # try the next account before concluding

    if checked == 0:
        return  # nothing encrypted to verify against

    # Every encrypted credential failed to decrypt → the key does not match the data.
    raise SecretKeyMismatchError(
        "DB_SECRET_KEY does not match the encrypted broker credentials in the "
        "database. The key in your .env was likely changed or regenerated.\n"
        "  • Your stored credentials are intact but cannot be read with this key.\n"
        "  • If you have the ORIGINAL DB_SECRET_KEY, restore it to .env and restart.\n"
        "  • Otherwise, start the app, go to Settings → Broker Accounts, and "
        "re-enter your API keys (they will be re-encrypted with the current key).\n"
        "This guard exists so a key mismatch fails loudly instead of looking like "
        "an invalid-API-key error."
    )


def update_broker_account(account_id: int, *, label: str | None = None, account_type: str | None = None) -> None:
    """Update label and/or account_type. Sets updated_at."""
    fields, vals = [], []
    if label is not None:
        fields.append("label=?"); vals.append(label)
    if account_type is not None:
        fields.append("account_type=?"); vals.append(account_type)
    if not fields:
        raise ValueError("at least one of label or account_type required")
    fields.append("updated_at=?"); vals.append(now_iso())
    vals.append(account_id)
    with get_conn() as c:
        c.execute(f"UPDATE broker_accounts SET {', '.join(fields)} WHERE id=?", vals)


def update_broker_credentials(account_id: int, api_key_enc: str, api_secret_enc: str) -> None:
    """Replace encrypted credentials and set updated_at."""
    with get_conn() as c:
        c.execute(
            "UPDATE broker_accounts SET api_key=?, api_secret=?, updated_at=? WHERE id=?",
            (api_key_enc, api_secret_enc, now_iso(), account_id)
        )


def delete_broker_account(account_id: int) -> None:
    """Delete account. CASCADE removes strategy_accounts rows."""
    with get_conn() as c:
        c.execute("DELETE FROM broker_accounts WHERE id=?", (account_id,))


def get_broker_account_assignments(account_id: int) -> list[str]:
    """Return strategy names assigned to this account."""
    with get_conn() as c:
        rows = c.execute(
            "SELECT strategy_name FROM strategy_accounts WHERE account_id=? ORDER BY strategy_name", (account_id,)
        ).fetchall()
        return [r["strategy_name"] for r in rows]


# ── Strategy Accounts ─────────────────────────────────────────────────────────

def get_strategy_accounts(strategy_name: str) -> list[dict]:
    """Return enabled (strategy, account) pairs with ciphertext credentials. Used by engine."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT sa.account_id AS id, ba.label, ba.api_key, ba.api_secret,
                      ba.account_type, ba.broker, sa.active_start, sa.active_end
               FROM strategy_accounts sa
               JOIN broker_accounts ba ON ba.id = sa.account_id
               WHERE sa.strategy_name = ? AND sa.enabled = 1""",
            (strategy_name,)
        )]


def get_strategy_account_list(strategy_name: str) -> list[dict]:
    """Return all assigned accounts with enabled flag. Used by API endpoint."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT ba.id, ba.label, ba.account_type, sa.enabled, sa.created_at,
                      sa.active_start, sa.active_end
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
    """Upsert the enabled flag — creates the row if it doesn't exist yet. Returns False if account_id not found."""
    with get_conn() as c:
        exists = c.execute("SELECT 1 FROM broker_accounts WHERE id=?", (account_id,)).fetchone()
        if not exists:
            return False
        c.execute(
            "INSERT INTO strategy_accounts (strategy_name, account_id, enabled) VALUES (?,?,?) "
            "ON CONFLICT(strategy_name, account_id) DO UPDATE SET enabled=excluded.enabled",
            (strategy_name, account_id, int(enabled))
        )
        return True


def get_strategy_account_windows(account_id: int) -> list[dict]:
    """Return per-account active_start/active_end for all strategies assigned to this account."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT strategy_name, active_start, active_end FROM strategy_accounts WHERE account_id=?",
            (account_id,)
        )]


def update_strategy_account_window(strategy_name: str, account_id: int,
                                    active_start: str | None, active_end: str | None) -> bool:
    """Set per-account active time window. Returns False if the row doesn't exist."""
    with get_conn() as c:
        cur = c.execute(
            "UPDATE strategy_accounts SET active_start=?, active_end=? "
            "WHERE strategy_name=? AND account_id=?",
            (active_start or None, active_end or None, strategy_name, account_id)
        )
        return cur.rowcount > 0


def unassign_strategy_account(strategy_name: str, account_id: int) -> None:
    with get_conn() as c:
        c.execute(
            "DELETE FROM strategy_accounts WHERE strategy_name=? AND account_id=?",
            (strategy_name, account_id)
        )


def get_account_strategy_assignments(account_id: int) -> dict[str, bool]:
    """Return {strategy_name: enabled} for all strategies assigned to this account."""
    with get_conn() as c:
        rows = c.execute(
            "SELECT strategy_name, enabled FROM strategy_accounts WHERE account_id=?",
            (account_id,)
        ).fetchall()
        return {r["strategy_name"]: bool(r["enabled"]) for r in rows}


# ── Per-account kill switch ────────────────────────────────────────────────────

def get_account_kill_switch(account_id: int) -> bool:
    with get_conn() as c:
        row = c.execute(
            "SELECT kill_switch FROM account_settings WHERE account_id=?",
            (account_id,)
        ).fetchone()
    return bool(row["kill_switch"]) if row else False

def set_account_kill_switch(account_id: int, on: bool) -> None:
    with get_conn() as c:
        c.execute(
            """INSERT INTO account_settings(account_id, kill_switch, updated_at)
               VALUES(?, ?, datetime('now'))
               ON CONFLICT(account_id) DO UPDATE
               SET kill_switch=excluded.kill_switch, updated_at=excluded.updated_at""",
            (account_id, 1 if on else 0)
        )

def get_all_account_kill_switches() -> dict[int, bool]:
    with get_conn() as c:
        rows = c.execute("SELECT account_id, kill_switch FROM account_settings").fetchall()
    return {r["account_id"]: bool(r["kill_switch"]) for r in rows}


# ── Symbol Blacklist ───────────────────────────────────────────────────────────

def get_symbol_blacklist() -> list[str]:
    with get_conn() as c:
        rows = c.execute("SELECT symbol FROM symbol_blacklist ORDER BY symbol").fetchall()
    return [r["symbol"] for r in rows]


def add_symbol_to_blacklist(symbol: str) -> None:
    with get_conn() as c:
        c.execute("INSERT OR IGNORE INTO symbol_blacklist (symbol) VALUES (?)", (symbol.upper(),))


def remove_symbol_from_blacklist(symbol: str) -> None:
    with get_conn() as c:
        c.execute("DELETE FROM symbol_blacklist WHERE symbol=?", (symbol.upper(),))


# ── Price Alerts ───────────────────────────────────────────────────────────────

def create_price_alert(symbol: str, direction: str, target_price: float, note: str = "") -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO price_alerts(symbol, direction, target_price, note)
               VALUES(?, ?, ?, ?)""",
            (symbol.upper(), direction, target_price, note)
        )
    return cur.lastrowid

def list_price_alerts(include_triggered: bool = False) -> list[dict]:
    sql = "SELECT * FROM price_alerts"
    if not include_triggered:
        sql += " WHERE triggered = 0"
    sql += " ORDER BY created_at DESC"
    with get_conn() as c:
        rows = c.execute(sql).fetchall()
    return [dict(r) for r in rows]

def delete_price_alert(alert_id: int) -> None:
    with get_conn() as c:
        c.execute("DELETE FROM price_alerts WHERE id=?", (alert_id,))

def trigger_price_alert(alert_id: int) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE price_alerts SET triggered=1, triggered_at=datetime('now') WHERE id=?",
            (alert_id,)
        )


# ── Extended risk helpers ──────────────────────────────────────────────────────

def count_signals_today() -> int:
    """Count non-blocked, non-error signals placed today (UTC date)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM signals WHERE DATE(ts)=? AND status NOT IN ('blocked','error')",
            (today,)
        ).fetchone()
    return row[0]


def get_consecutive_losses() -> int:
    val = get_app_config("consecutive_losses", "0")
    try:
        return int(val)
    except ValueError:
        return 0


def increment_consecutive_losses() -> int:
    n = get_consecutive_losses() + 1
    set_app_config("consecutive_losses", str(n))
    return n


def reset_consecutive_losses() -> None:
    set_app_config("consecutive_losses", "0")


# ── Crypto Cost Basis ─────────────────────────────────────────────────────────

def crypto_record_buy(account_id: int, symbol: str, qty: float, cost: float) -> None:
    """Update avg cost basis when a buy fills. Uses running weighted average."""
    with get_conn() as c:
        c.execute(
            """INSERT INTO crypto_cost_basis (account_id, symbol, qty, cost, realized_pnl, updated_at)
               VALUES (?, ?, ?, ?, 0, ?)
               ON CONFLICT(account_id, symbol) DO UPDATE SET
                 cost       = (cost * qty + excluded.cost) / (qty + excluded.qty),
                 qty        = qty + excluded.qty,
                 updated_at = excluded.updated_at""",
            (account_id, symbol.upper(), qty, cost, now_iso()),
        )


def crypto_record_sell(account_id: int, symbol: str, qty: float, proceeds: float) -> float:
    """Record a sell, compute realized P&L, reduce qty. Returns realized P&L."""
    with get_conn() as c:
        row = c.execute(
            "SELECT qty, cost, realized_pnl FROM crypto_cost_basis WHERE account_id=? AND symbol=?",
            (account_id, symbol.upper()),
        ).fetchone()
        if not row or row["qty"] <= 0:
            return 0.0
        avg_cost   = float(row["cost"])
        held_qty   = float(row["qty"])
        sell_qty   = min(qty, held_qty)
        pnl        = (proceeds / sell_qty - avg_cost) * sell_qty if sell_qty > 0 else 0.0
        new_qty    = max(0.0, held_qty - sell_qty)
        new_rpnl   = float(row["realized_pnl"]) + pnl
        c.execute(
            """UPDATE crypto_cost_basis SET qty=?, realized_pnl=?, updated_at=?
               WHERE account_id=? AND symbol=?""",
            (new_qty, new_rpnl, now_iso(), account_id, symbol.upper()),
        )
        return pnl


def crypto_get_cost_basis(account_id: int) -> list[dict]:
    """Return all cost basis rows for a Binance account."""
    with get_conn() as c:
        rows = c.execute(
            "SELECT symbol, qty, cost, realized_pnl FROM crypto_cost_basis WHERE account_id=?",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def crypto_get_realized_pnl(account_id: int) -> float:
    """Total realized P&L across all symbols for a Binance account."""
    with get_conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM crypto_cost_basis WHERE account_id=?",
            (account_id,),
        ).fetchone()
        return float(row["total"]) if row else 0.0


def crypto_pnl_from_signals(account_id: int) -> dict:
    """
    Compute per-symbol realized P&L for a Binance account.

    Primary source: strategy_perf rows written by close_trade_and_record_perf()
    — these use FIFO matching so the number is accurate even when buys and sells
    are unequal in count.

    Falls back to a buy/sell notional diff from the signals table only when no
    strategy_perf rows exist yet (fresh account with no completed round-trips).

    Returns:
        {
          "total_buy":      float,
          "total_sell":     float,
          "realized_pnl":  float,
          "by_symbol": {
            "BTC/USDT": {"buy": x, "sell": y, "pnl": z, "trades": n}, ...
          }
        }
    """
    # ── Primary: read from FIFO-matched strategy_perf ─────────────────────────
    with get_conn() as c:
        perf_rows = c.execute(
            """SELECT symbol, SUM(notional) AS sell_notional,
                      SUM(pnl) AS pnl, COUNT(*) AS trades
               FROM strategy_perf
               WHERE account_id=? AND side='sell'
               GROUP BY symbol""",
            (account_id,),
        ).fetchall()

    if perf_rows:
        by_sym: dict = {}
        total_buy = total_sell = realized = 0.0
        for r in perf_rows:
            sym = r["symbol"].upper()
            pnl = float(r["pnl"] or 0)
            notional = float(r["sell_notional"] or 0)
            buy_notional = notional - pnl  # entry_price * qty = notional - profit
            by_sym[sym] = {
                "buy":    round(buy_notional, 4),
                "sell":   round(notional, 4),
                "pnl":    round(pnl, 4),
                "trades": int(r["trades"]),
            }
            total_buy  += buy_notional
            total_sell += notional
            realized   += pnl
        return {
            "total_buy":    total_buy,
            "total_sell":   total_sell,
            "realized_pnl": realized,
            "by_symbol":    by_sym,
        }

    # No completed round-trips yet — return zero rather than an unreliable estimate.
    # Buys in the signals table don't have filled_price (Binance demo doesn't return
    # filled_avg_price on buy orders), so any sell-minus-buy calculation produces
    # a phantom profit. strategy_perf will accumulate accurate data as trades complete.
    return {
        "total_buy":    0.0,
        "total_sell":   0.0,
        "realized_pnl": 0.0,
        "by_symbol":    {},
    }


# ── Backtest Runs ─────────────────────────────────────────────────────────────

def save_backtest_run(params: dict, results: dict) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO backtest_runs (
                created_at, name, strategy, symbols, start_date, end_date,
                initial_capital, position_size_pct, commission_pct, slippage_pct,
                total_return_pct, max_drawdown_pct, win_rate_pct, sharpe_ratio,
                total_trades, equity_curve, trades, symbol_breakdown, reproducibility
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now_iso(),
                None,
                params["strategy"],
                json.dumps(params["symbols"]),
                params["start_date"],
                params["end_date"],
                params["initial_capital"],
                params["position_size_pct"],
                params["commission_pct"],
                params["slippage_pct"],
                results.get("total_return_pct"),
                results.get("max_drawdown_pct"),
                results.get("win_rate_pct"),
                results.get("sharpe_ratio"),
                results.get("total_trades"),
                json.dumps(results.get("equity_curve", [])),
                json.dumps(results.get("trades", [])),
                json.dumps(results.get("symbol_breakdown", [])),
                json.dumps(results["reproducibility"]) if results.get("reproducibility") else None,
            ),
        )
        return cur.lastrowid


def list_backtest_runs() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            """SELECT id, created_at, name, strategy, symbols, start_date, end_date,
                      initial_capital, position_size_pct, commission_pct, slippage_pct,
                      total_return_pct, max_drawdown_pct, win_rate_pct, sharpe_ratio, total_trades
               FROM backtest_runs ORDER BY id DESC"""
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["symbols"] = json.loads(d["symbols"])
        result.append(d)
    return result


def get_backtest_run(run_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute(
            """SELECT id, created_at, name, strategy, symbols, start_date, end_date,
                      initial_capital, position_size_pct, commission_pct, slippage_pct,
                      total_return_pct, max_drawdown_pct, win_rate_pct, sharpe_ratio,
                      total_trades, equity_curve, trades, symbol_breakdown, reproducibility
               FROM backtest_runs WHERE id=?""",
            (run_id,)
        ).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["symbols"] = json.loads(d["symbols"])
    d["equity_curve"] = json.loads(d["equity_curve"]) if d["equity_curve"] else []
    d["trades"] = json.loads(d["trades"]) if d["trades"] else []
    d["symbol_breakdown"] = json.loads(d["symbol_breakdown"]) if d.get("symbol_breakdown") else []
    d["reproducibility"] = json.loads(d["reproducibility"]) if d.get("reproducibility") else None
    return d


def delete_backtest_run(run_id: int) -> bool:
    with get_conn() as c:
        cur = c.execute("DELETE FROM backtest_runs WHERE id=?", (run_id,))
        return cur.rowcount > 0


def rename_backtest_run(run_id: int, name: str) -> bool:
    with get_conn() as c:
        cur = c.execute(
            "UPDATE backtest_runs SET name=? WHERE id=?", (name, run_id)
        )
        return cur.rowcount > 0


# ── Task 9: walk-forward research persistence (research/reporting only) ──────────
#
# These functions persist the outputs of server/research.py. They NEVER enable a
# strategy, mutate live state, or touch automation — they are pure evidence storage
# so the §12.12 "every attempt visible" and reproducibility criteria are durable.

def _dec_text(v):
    """Canonical decimal text for a Decimal/number, or None. Reporting-only."""
    if v is None:
        return None
    from decimal import Decimal
    from .execution_models import decimal_text
    try:
        return decimal_text(v if isinstance(v, Decimal) else Decimal(str(v)))
    except Exception:
        return str(v)


def persist_research_attempt(attempt: dict, run_id: int | None = None) -> int:
    """Record ONE attempted configuration (training/validation/holdout) verbatim.

    Callable as the `persist` hook of research.run_walk_forward so every attempt is
    durably visible (spec §12.12). Returns the new row id."""
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO research_attempts (
                run_id, role, params, window_start, window_end, from_cash,
                net_return, calmar, max_drawdown, turnover
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                attempt["role"],
                json.dumps(attempt.get("params", {}), default=str, sort_keys=True),
                attempt.get("window_start"),
                attempt.get("window_end"),
                1 if attempt.get("from_cash", True) else 0,
                _dec_text(attempt.get("net_return")),
                _dec_text(attempt.get("calmar")),
                _dec_text(attempt.get("max_drawdown")),
                _dec_text(attempt.get("turnover")),
            ),
        )
        return cur.lastrowid


def save_research_run(*, asset_class: str, frozen_params: dict | None,
                      oos_return, holdout_summary: dict | None,
                      criteria: dict | None, overall_pass: bool,
                      data_fingerprint: str | None = None,
                      code_revision: str | None = None,
                      geometry: dict | None = None,
                      label: str | None = None) -> int:
    """Persist one research validation cycle's result (frozen params, OOS/holdout
    summaries, the 12-criteria verdict, provenance). Returns the new run id.

    Does NOT enable anything — deployment/enable is a separate, explicitly gated
    Task 12 step."""
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO research_runs (
                asset_class, label, frozen_params, oos_return, holdout_summary,
                criteria, overall_pass, data_fingerprint, code_revision, geometry
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                asset_class,
                label,
                json.dumps(frozen_params, default=str, sort_keys=True) if frozen_params is not None else None,
                _dec_text(oos_return),
                json.dumps(holdout_summary, default=str) if holdout_summary is not None else None,
                json.dumps(criteria, default=str) if criteria is not None else None,
                1 if overall_pass else 0,
                data_fingerprint,
                code_revision,
                json.dumps(geometry, default=str) if geometry is not None else None,
            ),
        )
        return cur.lastrowid


def list_research_runs() -> list[dict]:
    """List research runs (newest first), summary columns only."""
    with get_conn() as c:
        rows = c.execute(
            """SELECT id, created_at, asset_class, label, oos_return,
                      overall_pass, data_fingerprint, code_revision
               FROM research_runs ORDER BY id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_research_run(run_id: int) -> dict | None:
    """Full research run including frozen params, holdout, and the 12-criteria
    verdict, plus every persisted attempt for that run."""
    with get_conn() as c:
        r = c.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        for k in ("frozen_params", "holdout_summary", "criteria", "geometry"):
            d[k] = json.loads(d[k]) if d.get(k) else None
        attempts = c.execute(
            "SELECT id, role, params, window_start, window_end, from_cash, "
            "net_return, calmar, max_drawdown, turnover "
            "FROM research_attempts WHERE run_id=? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
    out_attempts = []
    for a in attempts:
        ad = dict(a)
        ad["params"] = json.loads(ad["params"]) if ad.get("params") else {}
        out_attempts.append(ad)
    d["attempts"] = out_attempts
    return d


# ── Watchlists ─────────────────────────────────────────────────────────────────

def _clean_wl_symbols(syms: list) -> list:
    seen, out = set(), []
    for s in syms:
        s = str(s).upper().strip().split("/")[0]
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out

def get_watchlists() -> list[dict]:
    with get_conn() as c:
        rows = c.execute("SELECT * FROM watchlists ORDER BY name").fetchall()
    return [{"id": r["id"], "name": r["name"],
             "symbols": _clean_wl_symbols(json.loads(r["symbols"])), "updated_at": r["updated_at"]} for r in rows]

def get_watchlist(wl_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute("SELECT * FROM watchlists WHERE id=?", (wl_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "name": r["name"],
            "symbols": _clean_wl_symbols(json.loads(r["symbols"])), "updated_at": r["updated_at"]}

def create_watchlist(name: str) -> dict:
    with get_conn() as c:
        c.execute("INSERT INTO watchlists(name, symbols, updated_at) VALUES(?,?,?)",
                  (name, "[]", now_iso()))
        wl_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return get_watchlist(wl_id)

def delete_watchlist(wl_id: int) -> bool:
    with get_conn() as c:
        cur = c.execute("DELETE FROM watchlists WHERE id=?", (wl_id,))
        return cur.rowcount > 0

def add_watchlist_symbol(wl_id: int, symbol: str) -> dict | None:
    wl = get_watchlist(wl_id)
    if not wl:
        return None
    syms = wl["symbols"]
    symbol = symbol.upper().strip().split("/")[0]
    if symbol not in syms:
        syms.append(symbol)
    with get_conn() as c:
        c.execute("UPDATE watchlists SET symbols=?, updated_at=? WHERE id=?",
                  (json.dumps(syms), now_iso(), wl_id))
    return get_watchlist(wl_id)

def remove_watchlist_symbol(wl_id: int, symbol: str) -> dict | None:
    wl = get_watchlist(wl_id)
    if not wl:
        return None
    syms = [s for s in wl["symbols"] if s != symbol.upper().strip().split("/")[0]]
    with get_conn() as c:
        c.execute("UPDATE watchlists SET symbols=?, updated_at=? WHERE id=?",
                  (json.dumps(syms), now_iso(), wl_id))
    return get_watchlist(wl_id)

def rename_watchlist(wl_id: int, name: str) -> dict | None:
    with get_conn() as c:
        c.execute("UPDATE watchlists SET name=?, updated_at=? WHERE id=?",
                  (name, now_iso(), wl_id))
    return get_watchlist(wl_id)


def set_benchmark(run_id: int) -> bool:
    with get_conn() as c:
        row = c.execute(
            "SELECT strategy FROM backtest_runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            return False
        strategy = row["strategy"]
        c.execute(
            "UPDATE backtest_runs SET is_benchmark=0 WHERE strategy=?", (strategy,)
        )
        c.execute(
            "UPDATE backtest_runs SET is_benchmark=1 WHERE id=?", (run_id,)
        )
    return True


def get_benchmark(strategy: str) -> dict | None:
    with get_conn() as c:
        row = c.execute(
            """SELECT id, name, win_rate_pct, total_return_pct, total_trades,
                      start_date, end_date
               FROM backtest_runs WHERE strategy=? AND is_benchmark=1""",
            (strategy,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    total_trades = d.get("total_trades") or 0
    total_return = d.pop("total_return_pct") or 0.0
    d["avg_return_pct"] = total_return / total_trades if total_trades else 0.0
    return d


def get_live_health_stats(strategy: str) -> dict:
    with get_conn() as c:
        row = c.execute(
            """SELECT
                COUNT(*)                          AS total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                COALESCE(AVG(pnl_pct), 0.0)       AS live_avg_return_pct,
                MAX(date)                          AS last_trade_at
               FROM strategy_perf WHERE strategy=?""",
            (strategy,)
        ).fetchone()
    total    = row["total_trades"] or 0
    winning  = row["winning_trades"] or 0
    return {
        "total_trades":        total,
        "live_win_rate":       winning / total if total else 0.0,
        "live_avg_return_pct": row["live_avg_return_pct"],
        "last_trade_at":       row["last_trade_at"],
    }


def list_backtest_runs_with_benchmark() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            """SELECT id, created_at, name, strategy, symbols, start_date, end_date,
                      initial_capital, position_size_pct, commission_pct, slippage_pct,
                      total_return_pct, max_drawdown_pct, win_rate_pct, sharpe_ratio,
                      total_trades, is_benchmark
               FROM backtest_runs ORDER BY id DESC"""
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["symbols"] = json.loads(d["symbols"])
        result.append(d)
    return result


# ── AI helpers ─────────────────────────────────────────────────────────────────

def set_signal_explanation(signal_id: int, text: str, ai_provider: str | None = None, ai_model: str | None = None) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE signals SET ai_explanation=?, ai_provider=?, ai_model=? WHERE id=?",
            (text, ai_provider, ai_model, signal_id),
        )


# ── Persistent sessions ────────────────────────────────────────────────────────

def save_session(token: str, expires_at: float) -> None:
    with get_conn() as c:
        c.execute("INSERT OR REPLACE INTO sessions(token, expires_at) VALUES(?,?)",
                  (token, expires_at))


def load_session(token: str) -> float | None:
    """Return expiry timestamp or None if not found."""
    with get_conn() as c:
        row = c.execute("SELECT expires_at FROM sessions WHERE token=?", (token,)).fetchone()
    return row["expires_at"] if row else None


def update_session_expiry(token: str, expires_at: float) -> None:
    with get_conn() as c:
        c.execute("UPDATE sessions SET expires_at=? WHERE token=?", (expires_at, token))


def delete_session(token: str) -> None:
    with get_conn() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


def purge_expired_sessions() -> None:
    import time
    with get_conn() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))


def get_unexplained_signals(limit: int = 50) -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            """SELECT id, ts, strategy, symbol, side, reason
               FROM signals
               WHERE ai_explanation IS NULL
                 AND status NOT IN ('blocked', 'error')
                 AND symbol NOT IN ('-', '')
               ORDER BY id ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_signal_explanation(signal_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute(
            "SELECT ai_explanation, ai_provider, ai_model FROM signals WHERE id=?", (signal_id,)
        ).fetchone()
    if not row:
        return None
    return {"explanation": row["ai_explanation"], "ai_provider": row["ai_provider"], "ai_model": row["ai_model"]}


def get_signal_by_id(signal_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
    return dict(row) if row else None


def log_tuning_run(
    strategy: str,
    old_params: dict,
    new_params: dict,
    rationale: str,
    win_rate_before: float | None,
    ai_provider: str | None = None,
    ai_model: str | None = None,
) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO ai_tuning_log
               (created_at, strategy, old_params, new_params, rationale, win_rate_before, ai_provider, ai_model)
               VALUES (?,?,?,?,?,?,?,?)""",
            (now_iso(), strategy, json.dumps(old_params), json.dumps(new_params),
             rationale, win_rate_before, ai_provider, ai_model),
        )
        return cur.lastrowid


def list_tuning_log() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM ai_tuning_log ORDER BY id DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["old_params"] = json.loads(d["old_params"])
        d["new_params"] = json.loads(d["new_params"])
        result.append(d)
    return result


def get_tuning_run(run_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM ai_tuning_log WHERE id=?", (run_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["old_params"] = json.loads(d["old_params"])
    d["new_params"] = json.loads(d["new_params"])
    return d


def revert_tuning_run(run_id: int) -> bool:
    run = get_tuning_run(run_id)
    if not run:
        return False
    strat = get_strategy(run["strategy"])
    if not strat:
        return False
    upsert_strategy(run["strategy"], enabled=strat["enabled"], params=run["old_params"])
    return True


def get_strategy_perf_90d(strategy: str) -> dict:
    """Win rate, avg P&L, and trade count for a strategy over the last 90 days."""
    with get_conn() as c:
        row = c.execute(
            """SELECT
                COUNT(*)                                      AS total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)    AS wins,
                COALESCE(AVG(pnl), 0.0)                      AS avg_pnl
               FROM strategy_perf
               WHERE strategy=?
                 AND date >= DATE('now', '-90 days')""",
            (strategy,),
        ).fetchone()
    total = row["total_trades"] or 0
    wins  = row["wins"] or 0
    return {
        "total_trades": total,
        "win_rate":     round(wins / total * 100, 1) if total else 0.0,
        "avg_pnl":      round(row["avg_pnl"], 2),
    }


def get_open_trade_strategy(symbol: str, account_id: int | None) -> str | None:
    """Return the strategy that opened the oldest buy for symbol+account."""
    with get_conn() as c:
        row = c.execute(
            """SELECT strategy FROM open_trades
               WHERE symbol=? AND (account_id=? OR (account_id IS NULL AND ? IS NULL))
               ORDER BY opened_at ASC LIMIT 1""",
            (symbol, account_id, account_id),
        ).fetchone()
    return row["strategy"] if row else None


def get_open_trade_entry_price(strategy: str, symbol: str) -> float | None:
    """Return the avg fill price across all open buys for this strategy+symbol."""
    with get_conn() as c:
        row = c.execute(
            """SELECT AVG(fill_price) as avg_price FROM open_trades
               WHERE strategy=? AND symbol=?""",
            (strategy, symbol),
        ).fetchone()
    val = row["avg_price"] if row else None
    return float(val) if val is not None else None


def record_open_trade(strategy: str, symbol: str, account_id: int | None,
                      qty: float, fill_price: float) -> None:
    """Record a filled buy so it can be matched against a future sell for P&L."""
    with get_conn() as c:
        c.execute(
            """INSERT INTO open_trades(opened_at, strategy, symbol, account_id, qty, fill_price)
               VALUES(datetime('now'), ?, ?, ?, ?, ?)""",
            (strategy, symbol, account_id, qty, fill_price),
        )


def close_trade_and_record_perf(strategy: str, symbol: str, account_id: int | None,
                                 sell_qty: float, sell_price: float) -> None:
    """
    FIFO-match a sell against THIS strategy's own open buy rows for symbol+account,
    write realized P&L rows into strategy_perf attributed to that strategy, and
    delete the consumed buy rows.

    Matching includes strategy + account + symbol (§4.3): a strategy can only close
    its OWN lots, never another strategy's. The caller passes the owning strategy —
    for take-profit that is the ORIGINAL opening strategy (resolved via
    get_open_trade_strategy), never a different strategy's inventory.
    """
    if sell_qty <= 0 or sell_price <= 0:
        return

    with get_conn() as c:
        # Fetch oldest open buys for THIS strategy on this symbol+account only.
        buys = c.execute(
            """SELECT id, strategy, qty, fill_price FROM open_trades
               WHERE strategy=? AND symbol=? AND (account_id=? OR (account_id IS NULL AND ? IS NULL))
               ORDER BY opened_at ASC""",
            (strategy, symbol, account_id, account_id),
        ).fetchall()

        remaining = sell_qty
        for buy in buys:
            if remaining <= 0:
                break
            buy_id       = buy["id"]
            buy_strategy = buy["strategy"]   # attribute P&L to whoever opened the position
            buy_qty      = buy["qty"]
            buy_price    = buy["fill_price"]

            matched = min(remaining, buy_qty)
            pnl     = (sell_price - buy_price) * matched
            pnl_pct = ((sell_price - buy_price) / buy_price * 100) if buy_price else 0.0

            c.execute(
                """INSERT INTO strategy_perf
                   (date, strategy, symbol, side, qty, notional, entry_price, exit_price, pnl, pnl_pct, account_id)
                   VALUES(DATE('now'), ?, ?, 'sell', ?, ?, ?, ?, ?, ?, ?)""",
                (buy_strategy, symbol, matched, matched * sell_price,
                 buy_price, sell_price, round(pnl, 6), round(pnl_pct, 4), account_id),
            )

            leftover = buy_qty - matched
            if leftover < 0.000001:
                c.execute("DELETE FROM open_trades WHERE id=?", (buy_id,))
            else:
                c.execute("UPDATE open_trades SET qty=? WHERE id=?", (leftover, buy_id))

            remaining -= matched


def count_open_trades_for_symbol(symbol: str) -> int:
    """Return the total number of open buy rows for a symbol across all strategies/accounts."""
    with get_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM open_trades WHERE symbol=?", (symbol,)
        ).fetchone()
    return row["n"] if row else 0


def get_crypto_sell_perf(account_id: int) -> list[dict]:
    """Return strategy_perf sell rows for a Binance account, newest first."""
    with get_conn() as c:
        rows = c.execute(
            """SELECT symbol, qty, entry_price, exit_price, pnl, pnl_pct, date
               FROM strategy_perf
               WHERE account_id=? AND side='sell'
               ORDER BY id DESC
               LIMIT 200""",
            (account_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_tuning_win_rate_after(run_id: int, win_rate: float) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE ai_tuning_log SET win_rate_after=? WHERE id=?",
            (win_rate, run_id),
        )


# ── Audit log ──────────────────────────────────────────────────────────────────

def log_audit(category: str, action: str, detail: str = "") -> None:
    """Append one immutable audit record. Fire-and-forget; never raises."""
    try:
        with get_conn() as c:
            c.execute(
                "INSERT INTO audit_log(category, action, detail) VALUES(?,?,?)",
                (category, action, detail),
            )
    except Exception:
        pass


def list_audit(limit: int = 200, since: str | None = None, until: str | None = None) -> list[dict]:
    where, args = [], []
    if since:
        where.append("ts >= ?"); args.append(since)
    if until:
        where.append("ts <= ?"); args.append(until + " 23:59:59")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with get_conn() as c:
        rows = c.execute(
            f"SELECT id, ts, category, action, detail FROM audit_log {clause} ORDER BY ts DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Execution ledger persistence (strategy-rebuild spec §4.1, §19.5) ────────────

def _utc_micro() -> str:
    """UTC ISO-8601 timestamp with microseconds (spec §19.5)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def canonical_symbol(symbol: str) -> str:
    """Canonical instrument id used for all ownership/reconciliation selection keys.

    Selection keys always include strategy + account + canonical symbol (§4.3, §19.6),
    so lookups must not be defeated by case or surrounding whitespace. Slash pairs
    (e.g. 'BTC/USDT') keep their shape; only case/whitespace are normalized."""
    return (symbol or "").strip().upper()


def create_order_intent(*, account_id: int, strategy: str, client_order_id: str,
                        symbol: str, side: str, order_type: str,
                        requested_qty: str | None = None,
                        requested_notional: str | None = None) -> int:
    """Persist an order intent BEFORE contacting the broker (§4.1 step 2).

    Exactly one of requested_qty / requested_notional must be given, as canonical
    decimal text. Duplicate (account_id, client_order_id) raises (idempotency)."""
    from .execution_models import decimal_text
    if (requested_qty is None) == (requested_notional is None):
        raise ValueError("exactly one of requested_qty / requested_notional required")
    q = decimal_text(requested_qty) if requested_qty is not None else None
    n = decimal_text(requested_notional) if requested_notional is not None else None
    now = _utc_micro()
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO execution_orders (account_id, strategy, client_order_id, symbol, "
            "side, order_type, requested_qty, requested_notional, state, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,'INTENT_PERSISTED',?,?)",
            (account_id, strategy, client_order_id, symbol, side, order_type, q, n, now, now),
        )
        return cur.lastrowid


def mark_order_submitting(order_id: int) -> None:
    """Persist SUBMITTING immediately before the network call (§19.3)."""
    with get_conn() as c:
        c.execute("UPDATE execution_orders SET state='SUBMITTING', updated_at=? WHERE id=?",
                  (_utc_micro(), order_id))


def bind_order_ack(order_id: int, *, broker_order_id: str | None,
                   state: str, last_error: str | None = None) -> None:
    """Record the broker acknowledgement (NOT a fill) and bind the broker id."""
    with get_conn() as c:
        c.execute(
            "UPDATE execution_orders SET broker_order_id=?, state=?, last_error=?, updated_at=? WHERE id=?",
            (broker_order_id, state, last_error, _utc_micro(), order_id),
        )


def get_execution_order(order_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute("SELECT * FROM execution_orders WHERE id=?", (order_id,)).fetchone()
    return dict(r) if r else None


def get_order_by_client_id(account_id: int, client_order_id: str) -> dict | None:
    """Authoritative recovery lookup after a timeout/crash (§19.3)."""
    with get_conn() as c:
        r = c.execute(
            "SELECT * FROM execution_orders WHERE account_id=? AND client_order_id=?",
            (account_id, client_order_id),
        ).fetchone()
    return dict(r) if r else None


def insert_fill_and_apply_fifo(order_id: int, *, broker_fill_id: str, qty: str,
                               price: str, fee: str = "0", fee_currency: str = "USD",
                               filled_at: str) -> int:
    """Idempotently ingest a confirmed fill in one BEGIN IMMEDIATE transaction (§19.5).

    - A duplicate fill with identical economic values returns the existing row id.
    - A duplicate broker_fill_id with DIFFERENT values raises LedgerConflict (the
      account should freeze rather than overwrite).

    Lot creation / FIFO matching (Task 2, §4.3, §19.5):
      - A BUY fill opens a strategy-owned lot for (account, strategy, symbol) with
        unit cost = price + allocated entry fee.
      - A SELL fill FIFO-matches against that owner's own lots ONLY (ordered by
        opening fill time then lot id) and reduces their remaining quantity. A
        strategy can never consume another strategy's lot.
    All of this happens inside the one BEGIN IMMEDIATE transaction (§19.5).
    """
    from decimal import Decimal
    from .execution_models import decimal_text, LedgerConflict
    q, p, f = decimal_text(qty), decimal_text(price), decimal_text(fee)

    order = get_execution_order(order_id)
    if order is None:
        raise ValueError(f"unknown execution_order {order_id}")
    account_id = order["account_id"]
    strategy = order["strategy"]
    side = order["side"]
    sym = canonical_symbol(order["symbol"])

    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute(
            "SELECT id, qty, price, fee, fee_currency FROM execution_fills "
            "WHERE account_id=? AND broker_fill_id=?",
            (account_id, broker_fill_id),
        ).fetchone()
        if existing is not None:
            same = (existing["qty"] == q and existing["price"] == p
                    and existing["fee"] == f and existing["fee_currency"] == fee_currency)
            c.execute("ROLLBACK")
            if same:
                return existing["id"]                    # idempotent no-op
            raise LedgerConflict(
                f"fill {broker_fill_id} on account {account_id} re-ingested with "
                f"different values (was qty={existing['qty']} price={existing['price']}, "
                f"now qty={q} price={p})"
            )
        cur = c.execute(
            "INSERT INTO execution_fills (execution_order_id, account_id, broker_fill_id, "
            "qty, price, fee, fee_currency, filled_at) VALUES (?,?,?,?,?,?,?,?)",
            (order_id, account_id, broker_fill_id, q, p, f, fee_currency, filled_at),
        )
        fill_id = cur.lastrowid

        # ── Lot creation / FIFO matching (§4.3, §19.5) ──────────────────────────
        qty_d = Decimal(q)
        if side == "buy":
            # Unit cost includes the entry fee allocated across the filled quantity,
            # applied once (§19.5). Fee currency other than USD is left in price only.
            unit_cost = Decimal(p)
            if fee_currency == "USD" and qty_d > 0:
                unit_cost = unit_cost + (Decimal(f) / qty_d)
            c.execute(
                "INSERT INTO position_lots (account_id, strategy, symbol, opening_fill_id, "
                "original_qty, remaining_qty, unit_cost, opened_at, provenance) "
                "VALUES (?,?,?,?,?,?,?,?, 'verified')",
                (account_id, strategy, sym, fill_id, q, q,
                 decimal_text(unit_cost), filled_at),
            )
        else:  # sell → reduce this owner's own lots, FIFO by opening fill time then lot id
            remaining = qty_d
            lots = c.execute(
                "SELECT pl.id AS id, pl.remaining_qty AS remaining_qty, pl.unit_cost AS unit_cost, "
                "pl.opened_at AS opened_at, ef.filled_at AS fill_time "
                "FROM position_lots pl "
                "LEFT JOIN execution_fills ef ON ef.id = pl.opening_fill_id "
                "WHERE pl.account_id=? AND pl.strategy=? AND pl.symbol=? "
                "AND CAST(pl.remaining_qty AS REAL) > 0 "
                "ORDER BY COALESCE(ef.filled_at, pl.opened_at) ASC, pl.id ASC",
                (account_id, strategy, sym),
            ).fetchall()
            for lot in lots:
                if remaining <= 0:
                    break
                lot_rem = Decimal(lot["remaining_qty"])
                matched = min(remaining, lot_rem)
                if matched <= 0:
                    continue
                new_rem = lot_rem - matched
                closed_at = filled_at if new_rem == 0 else None
                c.execute(
                    "UPDATE position_lots SET remaining_qty=?, closed_at=COALESCE(?, closed_at) "
                    "WHERE id=?",
                    (decimal_text(new_rem), closed_at, lot["id"]),
                )
                entry_price = decimal_text(lot["unit_cost"])
                net_pnl = decimal_text((Decimal(p) - Decimal(lot["unit_cost"])) * matched)
                c.execute(
                    "INSERT OR IGNORE INTO lot_matches (closing_fill_id, opening_lot_id, "
                    "matched_qty, entry_price, exit_price, net_pnl) VALUES (?,?,?,?,?,?)",
                    (fill_id, lot["id"], decimal_text(matched), entry_price, p, net_pnl),
                )
                remaining -= matched
            # Unmatched sell quantity is preserved implicitly: it is a sell fill with
            # no owned lots to attribute against (surfaced by reconciliation, §4.4).

        c.execute("COMMIT")
        return fill_id
    except LedgerConflict:
        raise
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()


# ── Fill-ingestion watermark + overlap cursor (Task 3, §19.13) ──────────────────

def get_fill_watermark(account_id: int) -> str | None:
    """Latest ingested fill time for an account, or None if never polled."""
    with get_conn() as c:
        r = c.execute("SELECT watermark FROM fill_watermarks WHERE account_id=?",
                      (account_id,)).fetchone()
    return r["watermark"] if r else None


def set_fill_watermark(account_id: int, watermark: str,
                       overlap_cursor: str | None = None) -> None:
    """Advance the account's fill-ingestion watermark. Monotonic: never moves
    backward, so a late fill inside the overlap window cannot rewind the cursor."""
    now = _utc_micro()
    with get_conn() as c:
        existing = c.execute("SELECT watermark FROM fill_watermarks WHERE account_id=?",
                             (account_id,)).fetchone()
        if existing is not None and existing["watermark"] >= watermark:
            # Keep the higher watermark; still refresh the overlap cursor/timestamp.
            c.execute(
                "UPDATE fill_watermarks SET overlap_cursor=?, updated_at=? WHERE account_id=?",
                (overlap_cursor, now, account_id))
            return
        c.execute(
            "INSERT INTO fill_watermarks(account_id, watermark, overlap_cursor, updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
            "watermark=excluded.watermark, overlap_cursor=excluded.overlap_cursor, "
            "updated_at=excluded.updated_at",
            (account_id, watermark, overlap_cursor, now))


# ── Portfolio risk state (Task 5, §19.1 — consolidated equity + hard stop) ──────
# Durable key/value store for the high-water mark, daily/weekly baselines, snapshot
# metadata, conversion rates, hard-stop step machine, and reset events. Values are
# canonical decimal TEXT or short status strings — never REAL.

def get_portfolio_risk(key: str, default: str = "") -> str:
    """Read one portfolio_risk_state value, or `default` if unset."""
    with get_conn() as c:
        r = c.execute("SELECT value FROM portfolio_risk_state WHERE key=?",
                      (key,)).fetchone()
    return r["value"] if r else default


def set_portfolio_risk(key: str, value: str) -> None:
    """Upsert one portfolio_risk_state value (updated_at refreshed)."""
    with get_conn() as c:
        c.execute(
            "INSERT INTO portfolio_risk_state(key, value, updated_at) "
            "VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%f000Z','now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, value))


def delete_portfolio_risk(key: str) -> None:
    """Remove one portfolio_risk_state key (used by owner clearance)."""
    with get_conn() as c:
        c.execute("DELETE FROM portfolio_risk_state WHERE key=?", (key,))


def get_all_portfolio_risk() -> dict[str, str]:
    """All portfolio_risk_state key/value pairs."""
    with get_conn() as c:
        rows = c.execute("SELECT key, value FROM portfolio_risk_state").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ── Late fee adjustments (Task 3, §19.5 — fills are immutable; fees append) ──────

def append_fee_adjustment(*, account_id: int, broker_fill_id: str, fee: str,
                          fee_currency: str = "USD", reason: str | None = None) -> int:
    """Append a fee correction to an existing fill (§19.5). Fills are immutable, so a
    late fee is a NEW fee_adjustments row, never an overwrite of the original fee."""
    from .execution_models import decimal_text
    with get_conn() as c:
        r = c.execute(
            "SELECT id FROM execution_fills WHERE account_id=? AND broker_fill_id=?",
            (account_id, broker_fill_id)).fetchone()
        if r is None:
            raise ValueError(f"no fill {broker_fill_id!r} on account {account_id}")
        cur = c.execute(
            "INSERT INTO fee_adjustments(execution_fill_id, fee, fee_currency, reason) "
            "VALUES(?,?,?,?)",
            (r["id"], decimal_text(fee), fee_currency, reason))
        return cur.lastrowid


def get_fill_total_fee(*, account_id: int, broker_fill_id: str):
    """Total fee for a fill: original fill fee + all appended adjustments (Decimal)."""
    from decimal import Decimal
    with get_conn() as c:
        r = c.execute(
            "SELECT id, fee FROM execution_fills WHERE account_id=? AND broker_fill_id=?",
            (account_id, broker_fill_id)).fetchone()
        if r is None:
            raise ValueError(f"no fill {broker_fill_id!r} on account {account_id}")
        total = Decimal(r["fee"])
        adj = c.execute("SELECT fee FROM fee_adjustments WHERE execution_fill_id=?",
                        (r["id"],)).fetchall()
    for a in adj:
        total += Decimal(a["fee"])
    return total


# ── Strategy-owned lots, reservations, and entry prices (Task 2, §4.3, §19.5) ────
# Selection keys ALWAYS include strategy + account + canonical symbol so a strategy
# can only ever see and sell its OWN lots on a specific account.

# Nonterminal states of a reservation/exit order still hold quantity (§19.5). A
# reservation is represented as a nonterminal SELL execution order whose owner is
# f"{strategy}::exit_reservation" so it never collides with a real submitted order.
_RESERVATION_SUFFIX = "::exit_reservation"
_NONTERMINAL_STATES = (
    "INTENT_PERSISTED", "SUBMITTING", "ACKNOWLEDGED",
    "PARTIALLY_FILLED", "CANCEL_PENDING", "UNKNOWN",
)


def get_strategy_positions(strategy: str, account_id: int) -> dict[str, str]:
    """Return {canonical_symbol: remaining_qty_text} for lots owned by this
    strategy on this account. Only owned, non-external, still-open lots (§4.3).

    Automated strategies receive only these positions for EXIT decisions; they can
    never see or sell another strategy's or account-level quantity."""
    with get_conn() as c:
        rows = c.execute(
            "SELECT symbol, SUM(CAST(remaining_qty AS REAL)) AS qty "
            "FROM position_lots "
            "WHERE strategy=? AND account_id=? AND provenance NOT IN ('external') "
            "GROUP BY symbol HAVING SUM(CAST(remaining_qty AS REAL)) > 0",
            (strategy, account_id),
        ).fetchall()
    out: dict[str, str] = {}
    for r in rows:
        # Recompute the exact remaining as canonical decimal text (avoid REAL drift).
        out[r["symbol"]] = _sum_remaining_lots(strategy, account_id, r["symbol"])
    return out


def _sum_remaining_lots(strategy: str, account_id: int, symbol: str):
    from decimal import Decimal
    sym = canonical_symbol(symbol)
    with get_conn() as c:
        rows = c.execute(
            "SELECT remaining_qty FROM position_lots "
            "WHERE strategy=? AND account_id=? AND symbol=? "
            "AND provenance NOT IN ('external')",
            (strategy, account_id, sym),
        ).fetchall()
    from .execution_models import decimal_text
    total = sum((Decimal(r["remaining_qty"]) for r in rows), Decimal("0"))
    return decimal_text(total)


def get_account_verified_qty(account_id: int) -> dict[str, str]:
    """Return {canonical_symbol: remaining_qty_text} of VERIFIED internal lots across
    ALL strategies for an account. Used by reconciliation to compare against settled
    broker holdings (§19.6). Excludes external/manual quarantined lots."""
    from decimal import Decimal
    from .execution_models import decimal_text
    with get_conn() as c:
        rows = c.execute(
            "SELECT symbol, remaining_qty FROM position_lots "
            "WHERE account_id=? AND provenance NOT IN ('external')",
            (account_id,),
        ).fetchall()
    totals: dict[str, Decimal] = {}
    for r in rows:
        sym = canonical_symbol(r["symbol"])
        totals[sym] = totals.get(sym, Decimal("0")) + Decimal(r["remaining_qty"])
    return {s: decimal_text(v) for s, v in totals.items()}


def insert_reconciliation_snapshot(account_id: int, symbol: str, broker_qty: str,
                                   internal_qty: str, delta: str, status: str) -> int:
    """Persist a reconciliation row with a stable snapshot id (§19.6)."""
    from .execution_models import decimal_text
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO reconciliation_snapshots (account_id, symbol, broker_qty, "
            "internal_qty, delta, status) VALUES (?,?,?,?,?,?)",
            (account_id, canonical_symbol(symbol), decimal_text(broker_qty),
             decimal_text(internal_qty), decimal_text(delta), status),
        )
        return cur.lastrowid


def get_strategy_entry_price(strategy: str, account_id: int, symbol: str):
    """Quantity-weighted average unit cost of this strategy's OPEN lots for the
    (strategy, account, canonical symbol) key. Returns Decimal or None (§4.3)."""
    from decimal import Decimal
    sym = canonical_symbol(symbol)
    with get_conn() as c:
        rows = c.execute(
            "SELECT remaining_qty, unit_cost FROM position_lots "
            "WHERE strategy=? AND account_id=? AND symbol=? "
            "AND provenance NOT IN ('external') AND CAST(remaining_qty AS REAL) > 0",
            (strategy, account_id, sym),
        ).fetchall()
    total_qty = Decimal("0")
    total_cost = Decimal("0")
    for r in rows:
        q = Decimal(r["remaining_qty"])
        total_qty += q
        total_cost += q * Decimal(r["unit_cost"])
    if total_qty <= 0:
        return None
    return total_cost / total_qty


def _reserved_exit_qty(c, strategy: str, account_id: int, symbol: str):
    """Sum of UNFILLED quantity held by this owner's nonterminal exits/reservations.

    Reservation held by an order == its requested_qty minus quantity already ingested
    as fills against it, so a sell that has partially/fully filled stops
    double-counting against the lots the fill already reduced (§19.5)."""
    from decimal import Decimal
    sym = canonical_symbol(symbol)
    placeholders = ",".join("?" for _ in _NONTERMINAL_STATES)
    rows = c.execute(
        f"SELECT eo.id AS id, eo.requested_qty AS requested_qty, "
        f"COALESCE((SELECT SUM(CAST(ef.qty AS REAL)) FROM execution_fills ef "
        f"          WHERE ef.execution_order_id = eo.id), 0) AS filled "
        f"FROM execution_orders eo "
        f"WHERE eo.account_id=? AND eo.symbol=? AND eo.side='sell' "
        f"AND eo.strategy IN (?, ?) AND eo.state IN ({placeholders}) "
        f"AND eo.requested_qty IS NOT NULL",
        (account_id, sym, strategy, strategy + _RESERVATION_SUFFIX, *_NONTERMINAL_STATES),
    ).fetchall()
    total = Decimal("0")
    for r in rows:
        # Per-order unfilled reservation, never negative.
        unfilled = Decimal(r["requested_qty"]) - Decimal(str(r["filled"]))
        if unfilled > 0:
            total += unfilled
    return total


def get_sellable_qty(strategy: str, account_id: int, symbol: str):
    """Remaining owned lots MINUS reserved nonterminal exits (§19.5).

    Returns a non-negative Decimal. Rounds toward zero if reservations somehow
    exceed owned quantity (never returns negative)."""
    from decimal import Decimal
    sym = canonical_symbol(symbol)
    owned = Decimal(_sum_remaining_lots(strategy, account_id, sym))
    with get_conn() as c:
        reserved = _reserved_exit_qty(c, strategy, account_id, sym)
    sellable = owned - reserved
    return sellable if sellable > 0 else Decimal("0")


def reserve_exit_qty(strategy: str, account_id: int, symbol: str, qty: str):
    """Reserve up to `qty` of this strategy's sellable quantity for an exit.

    Oversized requests round DOWN to the currently sellable amount (§19.5); a zero
    sellable reserves nothing. Returns the Decimal quantity actually reserved."""
    from decimal import Decimal
    from .execution_models import decimal_text
    sym = canonical_symbol(symbol)
    want = Decimal(decimal_text(qty))
    if want <= 0:
        return Decimal("0")
    # Atomically reserve against currently sellable quantity.
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        c.execute("BEGIN IMMEDIATE")
        owned = Decimal(_sum_remaining_lots(strategy, account_id, sym))
        reserved = _reserved_exit_qty(c, strategy, account_id, sym)
        available = owned - reserved
        if available <= 0:
            c.execute("ROLLBACK")
            return Decimal("0")
        grant = want if want <= available else available   # round down to available
        import uuid
        cid = f"{strategy}{_RESERVATION_SUFFIX}-{uuid.uuid4().hex[:12]}"
        now = _utc_micro()
        c.execute(
            "INSERT INTO execution_orders (account_id, strategy, client_order_id, symbol, "
            "side, order_type, requested_qty, state, created_at, updated_at) "
            "VALUES (?,?,?,?, 'sell', 'reservation', ?, 'INTENT_PERSISTED', ?, ?)",
            (account_id, strategy + _RESERVATION_SUFFIX, cid, sym,
             decimal_text(grant), now, now),
        )
        c.execute("COMMIT")
        return grant
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()


def release_exit_reservation(strategy: str, account_id: int, symbol: str,
                             qty: str | None = None) -> None:
    """Release this strategy's exit reservations for the (strategy, account, symbol)
    key. If `qty` is given, release approximately that much (oldest reservations
    first); otherwise release all reservations for the key."""
    from decimal import Decimal
    from .execution_models import decimal_text
    sym = canonical_symbol(symbol)
    placeholders = ",".join("?" for _ in _NONTERMINAL_STATES)
    with get_conn() as c:
        rows = c.execute(
            f"SELECT id, requested_qty FROM execution_orders "
            f"WHERE account_id=? AND symbol=? AND side='sell' AND strategy=? "
            f"AND state IN ({placeholders}) ORDER BY id ASC",
            (account_id, sym, strategy + _RESERVATION_SUFFIX, *_NONTERMINAL_STATES),
        ).fetchall()
        if qty is None:
            for r in rows:
                c.execute("UPDATE execution_orders SET state='CANCELED', updated_at=? WHERE id=?",
                          (_utc_micro(), r["id"]))
            return
        remaining = Decimal(decimal_text(qty))
        for r in rows:
            if remaining <= 0:
                break
            rq = Decimal(r["requested_qty"])
            if rq <= remaining:
                c.execute("UPDATE execution_orders SET state='CANCELED', updated_at=? WHERE id=?",
                          (_utc_micro(), r["id"]))
                remaining -= rq
            else:
                # Partial release: shrink this reservation by `remaining`.
                c.execute("UPDATE execution_orders SET requested_qty=?, updated_at=? WHERE id=?",
                          (decimal_text(rq - remaining), _utc_micro(), r["id"]))
                remaining = Decimal("0")
