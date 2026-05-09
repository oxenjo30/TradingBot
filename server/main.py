import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import alpaca_client, auth, db, engine, notifications, risk, scanner, strategies
from .config import STATIC_DIR, BASE_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    existing = {s["name"] for s in db.get_strategies()}
    for cls in strategies.REGISTRY.values():
        if cls.name not in existing:
            db.upsert_strategy(cls.name, enabled=False, params=cls.default_params)
    engine.start(interval_seconds=60)
    yield
    engine.shutdown()


app = FastAPI(title="TradeBot", lifespan=lifespan)

# ── Auth helpers ───────────────────────────────────────────────────────────────

def _get_token(request: Request) -> str | None:
    return request.cookies.get("tb_session")

def _require_auth(request: Request):
    if not auth.password_is_set():
        return  # no password set yet — allow (setup mode)
    if not auth.validate_session(_get_token(request)):
        raise HTTPException(401, "unauthorized")


# ── Models ─────────────────────────────────────────────────────────────────────

class OrderIn(BaseModel):
    symbol: str = Field(min_length=1)
    qty: float | None = Field(default=None, gt=0)
    notional: float | None = Field(default=None, gt=0)
    side: Literal["buy", "sell"]

class StrategyUpdate(BaseModel):
    enabled: bool | None = None
    params: dict | None = None

class RiskSettingUpdate(BaseModel):
    value: str

class LoginIn(BaseModel):
    password: str

class SetupTestIn(BaseModel):
    api_key: str
    api_secret: str
    account_type: str = "paper"

class SetupCompleteIn(BaseModel):
    api_key: str
    api_secret: str
    account_type: str = "paper"
    notional: float = 500
    max_daily_loss_pct: float = 2.0
    max_position_count: int = 5
    starter_strategy: str = "momentum"
    password: str

class NotificationSettings(BaseModel):
    email_enabled: bool = False
    email_to: str = ""
    email_smtp: str = "smtp.gmail.com"
    email_port: int = 587
    email_user: str = ""
    email_pass: str = ""
    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    notify_on_trade: bool = True
    notify_on_block: bool = False
    notify_daily_summary: bool = True


# ── Setup & Auth routes ────────────────────────────────────────────────────────

@app.get("/setup")
def setup_page():
    return FileResponse(str(STATIC_DIR / "setup.html"))

@app.get("/login")
def login_page():
    return FileResponse(str(STATIC_DIR / "login.html"))

@app.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    if not auth.check_password(body.password):
        raise HTTPException(401, "incorrect password")
    token = auth.create_session()
    response.set_cookie("tb_session", token, httponly=True, samesite="lax", max_age=86400)
    return {"ok": True}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = _get_token(request)
    if token:
        auth.revoke_session(token)
    response.delete_cookie("tb_session")
    return {"ok": True}

@app.post("/api/setup/test_connection")
def setup_test(body: SetupTestIn):
    try:
        endpoint = (
            "https://paper-api.alpaca.markets"
            if body.account_type == "paper"
            else "https://api.alpaca.markets"
        )
        from alpaca.trading.client import TradingClient
        tc = TradingClient(body.api_key, body.api_secret,
                           paper=(body.account_type == "paper"))
        acct = tc.get_account()
        return {
            "ok": True,
            "account_id": str(acct.id)[:8] + "...",
            "equity": float(acct.equity or 0),
        }
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/setup/complete")
def setup_complete(body: SetupCompleteIn):
    # 1. Write .env
    env_path = BASE_DIR / ".env"
    endpoint = ("https://paper-api.alpaca.markets" if body.account_type == "paper"
                else "https://api.alpaca.markets")
    env_content = (
        f"ALPACA_API_KEY={body.api_key}\n"
        f"ALPACA_API_SECRET={body.api_secret}\n"
        f"ALPACA_ENDPOINT={endpoint}/v2\n"
        f"ALPACA_ACCOUNT_TYPE={body.account_type}\n"
    )
    env_path.write_text(env_content)

    # 2. Risk settings
    db.set_risk_setting("max_daily_loss_pct", str(body.max_daily_loss_pct))

    # 3. Update all strategy notionals + max_positions
    for cls in strategies.REGISTRY.values():
        saved = db.get_strategy(cls.name)
        params = dict(cls.default_params)
        if saved:
            params.update(saved["params"])
        params["notional"] = body.notional
        if "max_positions" in params:
            params["max_positions"] = body.max_position_count
        enabled = (cls.name == body.starter_strategy and cls.auto_trade)
        db.upsert_strategy(cls.name, enabled=enabled, params=params)

    # 4. Password
    auth.set_password(body.password)
    auth.mark_setup_complete()

    return {"ok": True}


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "setup_complete": auth.setup_complete(),
        "has_password": auth.password_is_set(),
    }


# ── Account & market ───────────────────────────────────────────────────────────

@app.get("/api/account")
def account(request: Request):
    _require_auth(request)
    return alpaca_client.get_account_summary()

@app.get("/api/clock")
def clock():
    return alpaca_client.get_clock()

@app.get("/api/positions")
def positions(request: Request):
    _require_auth(request)
    return alpaca_client.get_positions()

@app.get("/api/orders")
def orders(request: Request, status: str = "all", limit: int = 50):
    _require_auth(request)
    return alpaca_client.get_orders(limit=limit, status=status)

@app.post("/api/orders")
def submit_order(o: OrderIn, request: Request):
    _require_auth(request)
    try:
        sym = o.symbol.upper()
        result = alpaca_client.submit_market_order(sym, o.side, qty=o.qty, notional=o.notional)
        label = f"manual ${o.notional:.2f}" if o.notional else "manual order"
        display = o.notional if o.notional else o.qty
        db.log_signal("manual", sym, o.side, display, label, result["id"], result["status"])
        if o.notional:
            notifications.notify_trade("manual", sym, o.side, None, o.notional, label, result["id"])
        return result
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/api/orders/{order_id}")
def cancel(order_id: str, request: Request):
    _require_auth(request)
    try:
        alpaca_client.cancel_order(order_id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/api/orders")
def cancel_all(request: Request):
    _require_auth(request)
    alpaca_client.cancel_all_orders()
    return {"ok": True}

@app.delete("/api/positions/{symbol}")
def close_pos(symbol: str, request: Request):
    _require_auth(request)
    try:
        alpaca_client.close_position(symbol)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/api/positions")
def close_all(request: Request):
    _require_auth(request)
    alpaca_client.close_all_positions()
    return {"ok": True}

@app.get("/api/quote/{symbol}")
def quote(symbol: str):
    try:
        return alpaca_client.get_latest_quote(symbol)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/api/portfolio_history")
def portfolio_history(request: Request, period: str = "1M", timeframe: str = "1D"):
    _require_auth(request)
    try:
        return alpaca_client.get_portfolio_history(period=period, timeframe=timeframe)
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Strategies ─────────────────────────────────────────────────────────────────

@app.get("/api/strategies")
def list_strategies():
    saved = {s["name"]: s for s in db.get_strategies()}
    out = []
    for cls in strategies.REGISTRY.values():
        s = saved.get(cls.name)
        out.append({
            **cls.describe(),
            "enabled": s["enabled"] if s else False,
            "params": s["params"] if s else cls.default_params,
        })
    return out

@app.patch("/api/strategies/{name}")
def update_strategy(name: str, body: StrategyUpdate, request: Request):
    _require_auth(request)
    if name not in strategies.REGISTRY:
        raise HTTPException(404, "unknown strategy")
    current = db.get_strategy(name) or {
        "enabled": False, "params": strategies.REGISTRY[name].default_params,
    }
    enabled = body.enabled if body.enabled is not None else current["enabled"]
    params = current["params"]
    if body.params is not None:
        params = {**params, **body.params}
    db.upsert_strategy(name, enabled=enabled, params=params)
    return db.get_strategy(name)


# ── Performance analytics ──────────────────────────────────────────────────────

@app.get("/api/performance")
def performance_data(request: Request):
    _require_auth(request)
    strategy_stats = db.performance_by_strategy()
    top_syms       = db.top_symbols_overall(limit=10)
    daily          = db.daily_signal_counts(30)

    # Enrich with live unrealized P&L from open positions
    try:
        positions = alpaca_client.get_positions()
        open_count = len(positions)
        total_upl  = sum(p["unrealized_pl"] for p in positions)
    except Exception:
        open_count, total_upl = 0, 0.0

    # Total unique symbols ever traded
    all_symbols = len({r["symbol"] for r in top_syms})

    return {
        "strategy_stats":     strategy_stats,
        "top_symbols":        top_syms,
        "daily_counts":       daily,
        "open_positions":     open_count,
        "total_unrealized_pl": total_upl,
        "unique_symbols":     all_symbols,
    }


# ── Signals & Engine ───────────────────────────────────────────────────────────

@app.get("/api/signals")
def signals(request: Request, limit: int = 100):
    _require_auth(request)
    return db.recent_signals(limit=limit)

@app.get("/api/engine")
def engine_status():
    return engine.last_run()

@app.post("/api/engine/run_now")
def engine_run_now(request: Request):
    _require_auth(request)
    engine.run_tick()
    return engine.last_run()


# ── Scanner ────────────────────────────────────────────────────────────────────

@app.get("/api/scanner")
def scanner_data():
    return scanner.get_raw()

@app.get("/api/scanner/universe")
def scanner_universe(min_price: float = 5.0, max_price: float = 1000.0,
                     top_actives: int = 20, top_gainers: int = 10):
    return scanner.get_scanner_universe(min_price, max_price, top_actives, top_gainers)


# ── Risk ───────────────────────────────────────────────────────────────────────

@app.get("/api/risk")
def risk_status(request: Request):
    _require_auth(request)
    acct = alpaca_client.get_account_summary()
    try:
        tc = alpaca_client.trading()
        a = tc.get_account()
        dtc = int(a.daytrade_count or 0)
    except Exception:
        dtc = 0
    return risk.status_summary(acct, dtc)

@app.post("/api/risk/kill_switch")
def set_kill(body: dict, request: Request):
    _require_auth(request)
    on = bool(body.get("on", True))
    risk.set_kill_switch(on)
    return {"kill_switch": on}

@app.patch("/api/risk/{key}")
def update_risk_setting(key: str, body: RiskSettingUpdate, request: Request):
    _require_auth(request)
    try:
        db.set_risk_setting(key, body.value)
        return db.get_risk_settings()
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Notifications ──────────────────────────────────────────────────────────────

@app.get("/api/notifications")
def get_notifications(request: Request):
    _require_auth(request)
    return db.get_notification_settings()

@app.post("/api/notifications")
def save_notifications(body: NotificationSettings, request: Request):
    _require_auth(request)
    for key, val in body.model_dump().items():
        db.set_app_config(key, "true" if val is True else "false" if val is False else str(val))
    return db.get_notification_settings()

@app.post("/api/notifications/test")
def test_notification(body: dict, request: Request):
    """Test with credentials passed directly from the form — no need to Save first."""
    _require_auth(request)
    channel = body.get("channel", "email")
    try:
        if channel == "telegram":
            token   = body.get("telegram_token", "").strip()
            chat_id = body.get("telegram_chat_id", "").strip()
            notifications.send_telegram_direct(
                token, chat_id,
                "✅ <b>TradeBot</b> — Telegram notifications are working!"
            )
        else:
            notifications.send_email_direct(
                to       = body.get("email_to", "").strip(),
                smtp     = body.get("email_smtp", "smtp.gmail.com").strip(),
                port     = int(body.get("email_port") or 587),
                user     = body.get("email_user", "").strip(),
                password = body.get("email_pass", "").strip(),
                subject  = "Test Notification",
                body     = "<p>Your TradeBot email notifications are working correctly!</p>"
            )
        return {"ok": True}
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Unexpected error: {e}")


# ── Static & Pages ─────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def index(request: Request):
    # redirect to setup if not configured
    if not auth.setup_complete():
        return RedirectResponse("/setup")
    # redirect to login if password set and not authenticated
    if auth.password_is_set() and not auth.validate_session(_get_token(request)):
        return RedirectResponse("/login")
    return FileResponse(str(STATIC_DIR / "index.html"))
