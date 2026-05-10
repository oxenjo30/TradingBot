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
"""

RISK_DEFAULTS = {
    "kill_switch":          "false",
    "max_daily_loss_pct":   "2.0",
    "max_day_trades":       "3",
    "position_size_mode":   "fixed",
    "position_size_pct":    "2.0",
    "max_position_pct":     "10.0",
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
    with get_conn() as c:
        c.execute(
            """INSERT INTO broker_accounts (id, label, api_key, api_secret, account_type)
               VALUES (1, 'Default', ?, ?, ?)
               ON CONFLICT(id) DO NOTHING""",
            (key_enc, secret_enc, account_type)
        )


def init_db():
    with get_conn() as c:
        c.executescript(SCHEMA)
    # seed risk defaults without overwriting existing values
    with get_conn() as c:
        for k, v in RISK_DEFAULTS.items():
            c.execute(
                "INSERT OR IGNORE INTO risk_settings(key, value) VALUES(?,?)", (k, v)
            )
    _migrate_env_account()


def get_risk_settings() -> dict:
    with get_conn() as c:
        rows = c.execute("SELECT key, value FROM risk_settings").fetchall()
    base = dict(RISK_DEFAULTS)
    base.update({r["key"]: r["value"] for r in rows})
    return {
        "kill_switch":        base["kill_switch"] == "true",
        "max_daily_loss_pct": float(base["max_daily_loss_pct"]),
        "max_day_trades":     int(base["max_day_trades"]),
        "position_size_mode": base["position_size_mode"],
        "position_size_pct":  float(base["position_size_pct"]),
        "max_position_pct":   float(base["max_position_pct"]),
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


def get_notification_settings() -> dict:
    keys = ["email_enabled", "email_to", "email_smtp", "email_port",
            "email_user", "email_pass", "telegram_enabled",
            "telegram_token", "telegram_chat_id", "notify_on_trade",
            "notify_on_block", "notify_daily_summary"]
    with get_conn() as c:
        rows = c.execute("SELECT key, value FROM app_config WHERE key IN ({})".format(
            ",".join("?" * len(keys))), keys).fetchall()
    result = {k: "" for k in keys}
    result.update({r["key"]: r["value"] for r in rows})
    # booleans
    for bk in ["email_enabled", "telegram_enabled", "notify_on_trade",
                "notify_on_block", "notify_daily_summary"]:
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


def upsert_strategy(name: str, enabled: bool, params: dict):
    with get_conn() as c:
        c.execute(
            """INSERT INTO strategies(name, enabled, params_json, updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 enabled=excluded.enabled,
                 params_json=excluded.params_json,
                 updated_at=excluded.updated_at""",
            (name, 1 if enabled else 0, json.dumps(params), now_iso()),
        )


def get_strategies() -> list[dict]:
    with get_conn() as c:
        rows = c.execute("SELECT * FROM strategies ORDER BY name").fetchall()
    return [
        {
            "name": r["name"],
            "enabled": bool(r["enabled"]),
            "params": json.loads(r["params_json"]),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def get_strategy(name: str) -> dict | None:
    with get_conn() as c:
        r = c.execute("SELECT * FROM strategies WHERE name=?", (name,)).fetchone()
    if not r:
        return None
    return {
        "name": r["name"],
        "enabled": bool(r["enabled"]),
        "params": json.loads(r["params_json"]),
        "updated_at": r["updated_at"],
    }


def log_signal(strategy: str, symbol: str, side: str, qty: float, reason: str,
               order_id: str | None, status: str):
    with get_conn() as c:
        c.execute(
            """INSERT INTO signals(ts, strategy, symbol, side, qty, reason, order_id, status)
               VALUES(?,?,?,?,?,?,?,?)""",
            (now_iso(), strategy, symbol, side, qty, reason, order_id, status),
        )


def recent_signals(limit: int = 100) -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Performance analytics ──────────────────────────────────────────────────────

def performance_by_strategy() -> list[dict]:
    """Aggregate signal counts per strategy."""
    with get_conn() as c:
        rows = c.execute("""
            SELECT
                strategy,
                COUNT(*)                                          AS total,
                SUM(CASE WHEN side='buy'       THEN 1 ELSE 0 END) AS buys,
                SUM(CASE WHEN side='sell'      THEN 1 ELSE 0 END) AS sells,
                SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) AS blocked,
                SUM(CASE WHEN status='error'   THEN 1 ELSE 0 END) AS errors,
                COUNT(DISTINCT symbol)                             AS unique_symbols,
                MIN(ts)                                           AS first_signal,
                MAX(ts)                                           AS last_signal
            FROM signals
            WHERE strategy != 'manual'
            GROUP BY strategy
            ORDER BY total DESC
        """).fetchall()
    return [dict(r) for r in rows]


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
                DATE(ts)                                          AS date,
                COUNT(*)                                          AS total,
                SUM(CASE WHEN side='buy'  THEN 1 ELSE 0 END)     AS buys,
                SUM(CASE WHEN side='sell' THEN 1 ELSE 0 END)     AS sells
            FROM signals
            WHERE ts >= DATE('now', '-' || ? || ' days')
              AND status NOT IN ('blocked', 'error')
              AND symbol NOT IN ('-', '')
            GROUP BY DATE(ts)
            ORDER BY date ASC
        """, (days,)).fetchall()
    return [dict(r) for r in rows]


# ── Broker Accounts ───────────────────────────────────────────────────────────

def create_broker_account(label: str, api_key_enc: str, api_secret_enc: str, account_type: str) -> int:
    """Insert new account. Returns new row id. Raises IntegrityError if label not unique."""
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO broker_accounts (label, api_key, api_secret, account_type) VALUES (?,?,?,?)",
            (label, api_key_enc, api_secret_enc, account_type)
        )
        return cur.lastrowid


def get_broker_accounts() -> list[dict]:
    """Return all accounts. api_secret excluded; api_key returned as ciphertext for masking in main.py."""
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, label, api_key, account_type, created_at, updated_at FROM broker_accounts ORDER BY id"
        )]


def get_broker_account(account_id: int) -> dict | None:
    with get_conn() as c:
        r = c.execute(
            "SELECT id, label, api_key, account_type, created_at, updated_at FROM broker_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        return dict(r) if r else None


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
