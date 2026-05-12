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
    set_app_config("license_key", key)


def get_webhook_token() -> str:
    return get_app_config("webhook_token", "")

def set_webhook_token(token: str) -> None:
    set_app_config("webhook_token", token)

def rotate_webhook_token() -> str:
    import secrets
    token = secrets.token_hex(32)
    set_webhook_token(token)
    return token


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
               order_id: str | None = None, status: str = "ok",
               blocked: bool = False, account_id: int | None = None):
    with get_conn() as c:
        c.execute(
            """INSERT INTO signals(ts, strategy, symbol, side, qty, reason, order_id, status, blocked, account_id)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (now_iso(), strategy, symbol, side, qty, reason, order_id, status, int(blocked), account_id),
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
    """Return encrypted api_key + api_secret for internal use (status check, engine). Never send to clients."""
    with get_conn() as c:
        r = c.execute(
            "SELECT api_key, api_secret FROM broker_accounts WHERE id=?", (account_id,)
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
    """Upsert the enabled flag — creates the row if it doesn't exist yet."""
    with get_conn() as c:
        c.execute(
            "INSERT INTO strategy_accounts (strategy_name, account_id, enabled) VALUES (?,?,?) "
            "ON CONFLICT(strategy_name, account_id) DO UPDATE SET enabled=excluded.enabled",
            (strategy_name, account_id, int(enabled))
        )
        return True


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


# ── Backtest Runs ─────────────────────────────────────────────────────────────

def save_backtest_run(params: dict, results: dict) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO backtest_runs (
                created_at, name, strategy, symbols, start_date, end_date,
                initial_capital, position_size_pct, commission_pct, slippage_pct,
                total_return_pct, max_drawdown_pct, win_rate_pct, sharpe_ratio,
                total_trades, equity_curve, trades
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                      total_trades, equity_curve, trades
               FROM backtest_runs WHERE id=?""",
            (run_id,)
        ).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["symbols"] = json.loads(d["symbols"])
    d["equity_curve"] = json.loads(d["equity_curve"]) if d["equity_curve"] else []
    d["trades"] = json.loads(d["trades"]) if d["trades"] else []
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
