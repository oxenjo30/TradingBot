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
"""

RISK_DEFAULTS = {
    "kill_switch":          "false",
    "max_daily_loss_pct":   "2.0",
    "max_day_trades":       "3",
    "position_size_mode":   "fixed",
    "position_size_pct":    "2.0",
    "max_position_pct":     "10.0",
}


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
    # seed risk defaults without overwriting existing values
    with conn() as c:
        for k, v in RISK_DEFAULTS.items():
            c.execute(
                "INSERT OR IGNORE INTO risk_settings(key, value) VALUES(?,?)", (k, v)
            )


def get_risk_settings() -> dict:
    with conn() as c:
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
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO risk_settings(key, value) VALUES(?,?)", (key, value)
        )


def get_app_config(key: str, default: str = "") -> str:
    with conn() as c:
        row = c.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_app_config(key: str, value: str):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO app_config(key, value) VALUES(?,?)", (key, value)
        )


def get_notification_settings() -> dict:
    keys = ["email_enabled", "email_to", "email_smtp", "email_port",
            "email_user", "email_pass", "telegram_enabled",
            "telegram_token", "telegram_chat_id", "notify_on_trade",
            "notify_on_block", "notify_daily_summary"]
    with conn() as c:
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
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_strategy(name: str, enabled: bool, params: dict):
    with conn() as c:
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
    with conn() as c:
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
    with conn() as c:
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
    with conn() as c:
        c.execute(
            """INSERT INTO signals(ts, strategy, symbol, side, qty, reason, order_id, status)
               VALUES(?,?,?,?,?,?,?,?)""",
            (now_iso(), strategy, symbol, side, qty, reason, order_id, status),
        )


def recent_signals(limit: int = 100) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Performance analytics ──────────────────────────────────────────────────────

def performance_by_strategy() -> list[dict]:
    """Aggregate signal counts per strategy."""
    with conn() as c:
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
    with conn() as c:
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
    with conn() as c:
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
