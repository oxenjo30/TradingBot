import asyncio
import csv
import httpx
import io
import logging
import os
import threading

# Load .env before any module reads os.environ (e.g. DB_SECRET_KEY, TRADEBOT_LICENSE_PRIVATE_KEY)
from dotenv import load_dotenv as _load_dotenv
_load_dotenv()
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from . import ai_explainer, ai_tuner, alpaca_client, auth, backtest as bt_mod, crypto, db, engine, notifications, risk, scanner, sentiment, strategies, version
from .config import STATIC_DIR, BASE_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    crypto.init_crypto()  # must run before db.init_db() — migration calls crypto.encrypt()
    db.init_db()
    # Fail loudly (but don't abort startup) if DB_SECRET_KEY no longer decrypts the
    # stored broker credentials — otherwise a changed/lost key looks like an
    # "invalid API key" error. Startup must continue so the user can log in and
    # re-enter their keys in Settings → Broker Accounts.
    try:
        db.verify_secret_key_matches_credentials()
    except db.SecretKeyMismatchError as e:
        bar = "!" * 72
        log.error("\n%s\nDB_SECRET_KEY MISMATCH\n%s\n%s", bar, e, bar)
    existing = {s["name"] for s in db.get_strategies()}
    for cls in strategies.REGISTRY.values():
        if cls.name not in existing:
            db.upsert_strategy(cls.name, enabled=False, params=cls.default_params)
    engine.start(interval_seconds=60)
    ai_explainer.start()
    # Pre-load asset search cache in background so first search is instant
    import threading
    threading.Thread(target=alpaca_client._load_asset_cache, daemon=True).start()
    yield
    try:
        engine.shutdown()
    except Exception as e:
        log.warning("engine shutdown error (ignored): %s", e)


app = FastAPI(title="TradeBot", lifespan=lifespan)

# ── No-cache middleware for static assets ─────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheStaticMiddleware)

# ── Auth helpers ───────────────────────────────────────────────────────────────

def _get_token(request: Request) -> str | None:
    return request.cookies.get("tb_session")

def _require_license():
    """Raise 402 if the stored license key is missing or invalid."""
    from .license import check_stored_license
    result = check_stored_license()
    if not result.get("valid"):
        raise HTTPException(402, result.get("reason", "License required"))


def _require_auth(request: Request):
    # If setup is complete, always require a valid password + session —
    # a missing password_hash row means DB corruption, not a fresh install.
    if auth.setup_complete():
        if not auth.password_is_set() or not auth.validate_session(_get_token(request)):
            raise HTTPException(401, "Unauthorized")
        _require_license()
        return
    # Setup not done yet — only allow through if password is genuinely not set
    # (first-run wizard). Once setup is marked complete this branch is unreachable.
    if auth.password_is_set():
        raise HTTPException(401, "Unauthorized")


def owner_mode_enabled() -> bool:
    """True only on the seller's own instance (env TRADEBOT_OWNER_MODE set)."""
    return os.environ.get("TRADEBOT_OWNER_MODE", "").strip().lower() in ("1", "true", "yes")


def _require_owner(request: Request):
    """Require auth AND owner mode for seller-only endpoints.

    Unauthenticated callers get 401 (from _require_auth, which runs first so the
    endpoint's existence is never leaked); authenticated non-owners get 403.
    """
    _require_auth(request)
    if not owner_mode_enabled():
        raise HTTPException(403, "owner only")


def _read_env_key(name: str) -> str:
    try:
        for line in (BASE_DIR / ".env").read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return ""


def _safe_broker_error(e: Exception) -> str:
    """Return a user-safe broker error message — never expose internal crypto details."""
    msg = str(e)
    if "decrypt" in msg.lower() or "fernet" in msg.lower() or "invalidtoken" in msg.lower():
        return "Account credentials unavailable — please re-enter your API keys in Broker Accounts."
    if "unauthorized" in msg.lower() or "403" in msg or "401" in msg:
        return "Broker rejected the API key — check your credentials in Broker Accounts."
    # Truncate very long messages (stack traces etc.)
    return msg[:200] if len(msg) > 200 else msg


def _mask_account(row: dict) -> dict:
    row = dict(row)
    try:
        key_plain_last4 = crypto.decrypt(row["api_key"])[-4:]
        row["api_key"] = "****" + key_plain_last4
    except Exception:
        # RuntimeError (key missing) or InvalidToken (corruption / wrong key)
        row["api_key"] = "****[key unavailable]"
    row.pop("api_secret", None)  # api_secret is never returned
    return row


# ── Models ─────────────────────────────────────────────────────────────────────

class OrderIn(BaseModel):
    symbol: str = Field(min_length=1)
    qty: float | None = Field(default=None, gt=0)
    notional: float | None = Field(default=None, gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    side: Literal["buy", "sell"]
    account_id: int | None = None

class WebhookSignal(BaseModel):
    symbol:     str = Field(min_length=1, max_length=20)
    side:       Literal["buy", "sell"]
    qty:        float | None = Field(default=None, gt=0)
    notional:   float | None = Field(default=None, gt=0)
    strategy:   str = Field(default="webhook", max_length=64)
    account_id: int | None = None

_broker_client_cache: dict[int, object] = {}

def _get_broker_client(account_id: int | None):
    """Return a broker client for the given account_id.
    If account_id is None, uses the first available Alpaca account from DB."""
    if account_id is None:
        alpaca_accts = [a for a in db.get_broker_accounts() if (a.get("broker") or "alpaca") == "alpaca"]
        if alpaca_accts:
            account_id = alpaca_accts[0]["id"]
        else:
            return alpaca_client  # falls back to module-level (will raise if no .env creds)
    if account_id in _broker_client_cache:
        return _broker_client_cache[account_id]
    acct = db.get_broker_account_credentials(account_id)
    if not acct:
        raise HTTPException(404, f"Account {account_id} not found")
    from .broker_factory import get_account_client
    raw_secret = acct.get("api_secret") or ""
    client = get_account_client(
        broker=acct.get("broker", "alpaca"),
        api_key=crypto.decrypt(acct["api_key"]),
        api_secret=crypto.decrypt(raw_secret) if raw_secret else "",
        paper=(acct["account_type"] == "paper"),
        account_id=account_id,
    )
    # NOTE: do NOT set client._account_id here. The broker that needs the DB id
    # (Binance) already receives it via the account_id constructor arg above.
    # Tradier reuses _account_id for the *broker-side* account number (e.g.
    # "VA6629110"), fetched lazily from /user/profile; overwriting it with the
    # DB integer id produced URLs like /accounts/24/balances and a 401.
    _broker_client_cache[account_id] = client
    return client


class AlertCreate(BaseModel):
    symbol:       str
    direction:    Literal["above", "below"]
    target_price: float
    note:         str = ""

class StrategyUpdate(BaseModel):
    enabled: bool | None = None
    params: dict | None = None
    active_start: str | None = None  # "HH:MM" or "" to clear
    active_end:   str | None = None  # "HH:MM" or "" to clear

class RiskSettingUpdate(BaseModel):
    value: str

class LoginIn(BaseModel):
    password: str = Field(min_length=1)

class SetupCompleteIn(BaseModel):
    notional: float = 500
    max_daily_loss_pct: float = 2.0
    max_position_count: int = 5
    starter_strategy: str = "momentum"
    password: str = Field(min_length=8)

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
    slack_enabled: bool = False
    slack_webhook_url: str = ""
    discord_enabled: bool = False
    discord_webhook_url: str = ""
    notify_on_trade: bool = True
    notify_on_block: bool = False
    notify_daily_summary: bool = True

class BrokerAccountCreate(BaseModel):
    label: str
    api_key: str
    api_secret: str
    account_type: Literal["paper", "live"] = "paper"
    broker: str = "alpaca"

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
    active_start: str | None = None
    active_end:   str | None = None


class AiSettingsBody(BaseModel):
    ollama_url:           str | None = None
    ollama_model:         str | None = None
    explanations_enabled: bool | None = None
    tuner_enabled:        bool | None = None
    tuner_provider:       str | None = None  # "ollama" or "claude"
    claude_api_key:       str | None = None
    claude_model:         str | None = None
    target_win_rate:           float | None = None
    sentiment_enabled:         bool | None  = None
    sentiment_block_threshold: float | None = None
    sentiment_boost_threshold: float | None = None
    sentiment_boost_multiplier:float | None = None


# ── Setup & Auth routes ────────────────────────────────────────────────────────

@app.get("/setup")
def setup_page():
    return FileResponse(str(STATIC_DIR / "setup.html"))

@app.get("/login")
def login_page():
    return FileResponse(str(STATIC_DIR / "login.html"))

@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    allowed, secs = auth.check_login_allowed()
    if not allowed:
        raise HTTPException(429, f"Too many failed attempts. Try again in {secs}s.")
    if not auth.check_password(body.password):
        auth.record_login_failure()
        raise HTTPException(401, "incorrect password")
    auth.record_login_success()
    token = auth.create_session()
    # secure=True when served over HTTPS; omit for plain localhost HTTP
    is_secure = request.url.scheme == "https"
    response.set_cookie("tb_session", token, httponly=True, samesite="lax",
                        max_age=86400, secure=is_secure)
    return {"ok": True}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = _get_token(request)
    if token:
        auth.revoke_session(token)
    response.delete_cookie("tb_session")
    return {"ok": True}

@app.post("/api/setup/complete")
def setup_complete(body: SetupCompleteIn):
    if auth.setup_complete():
        raise HTTPException(409, "Setup already completed")
    # 1. Ensure DB_SECRET_KEY exists in .env.
    # CRITICAL: this key encrypts every stored broker credential. If it is ever
    # regenerated, all saved credentials become permanently undecryptable and read
    # as "invalid". So we ONLY ever generate-and-write a key when none exists yet,
    # and when one already exists we leave .env completely untouched — no rewrite,
    # no re-ordering — to eliminate any path that could clobber it.
    env_path = BASE_DIR / ".env"
    existing_secret = os.environ.get("DB_SECRET_KEY") or _read_env_key("DB_SECRET_KEY")
    if existing_secret:
        # Key already present — never touch .env. Just make sure it's loaded.
        os.environ["DB_SECRET_KEY"] = existing_secret
    else:
        # First run only: generate a key and append it, preserving every other line.
        db_secret = crypto.generate_key()
        try:
            lines = env_path.read_text().splitlines()
        except FileNotFoundError:
            lines = []
        lines.append(f"DB_SECRET_KEY={db_secret}")
        env_path.write_text("\n".join(lines) + "\n")
        os.environ["DB_SECRET_KEY"] = db_secret
    crypto.init_crypto()  # re-initialise with the (possibly new) key

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
    # Intentionally public — needed by setup wizard before auth exists
    return {
        "ok": True,
        "setup_complete": auth.setup_complete(),
        "has_password": auth.password_is_set(),
    }


@app.get("/api/app-info")
def app_info(request: Request):
    """Authenticated app metadata. Tells the UI whether to show owner-only tooling."""
    _require_auth(request)
    return {"owner_mode": owner_mode_enabled()}


# ── Update check ──────────────────────────────────────────────────────────────

_GITHUB_RELEASES_URL = "https://api.github.com/repos/oxenjo30/TradingBot/releases/latest"


@app.get("/api/update/check")
def check_for_update(request: Request):
    _require_auth(request)
    try:
        resp = httpx.get(
            _GITHUB_RELEASES_URL,
            headers={"User-Agent": "TradeBot-UpdateCheck/1.0"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Unable to reach GitHub")
        data = resp.json()
    except httpx.RequestError:
        raise HTTPException(502, "Unable to reach GitHub")
    installed = version.INSTALLED_VERSION
    latest = data.get("tag_name", installed)
    notes = (data.get("body") or "")[:1000]
    release_url = data.get("html_url", "")
    if not isinstance(release_url, str) or not release_url.startswith("https://github.com/"):
        release_url = _GITHUB_RELEASES_URL
    return {
        "installed": installed,
        "latest": latest,
        "up_to_date": installed == latest,
        "release_notes": notes,
        "release_url": release_url,
    }


# ── License ───────────────────────────────────────────────────────────────────

class LicenseActivate(BaseModel):
    key: str

@app.get("/api/license/status")
def license_status(request: Request):
    # Allow unauthenticated only during setup (before password exists)
    if auth.setup_complete():
        if not auth.password_is_set() or not auth.validate_session(_get_token(request)):
            raise HTTPException(401, "Unauthorized")
    from .license import check_stored_license
    result = check_stored_license()
    # Never expose machine_id to clients
    result.pop("machine_id", None)
    return result

@app.post("/api/license/activate")
def license_activate(body: LicenseActivate, request: Request):
    # Require auth if setup is done; allow unauthenticated only on fresh installs
    if auth.setup_complete():
        if not auth.password_is_set() or not auth.validate_session(_get_token(request)):
            raise HTTPException(401, "Unauthorized")
    from .license import activate_license, LicenseError
    try:
        # Verifies, stores the key, AND durably records it as accepted so the user
        # is never re-asked for it (survives restarts + transient verifier hiccups).
        result = activate_license(body.key)
    except LicenseError as e:
        raise HTTPException(422, str(e))
    result.pop("machine_id", None)
    return result

@app.delete("/api/license")
async def license_deactivate(request: Request):
    _require_auth(request)
    # Clearing the license locks the user out, so it must be an explicit, deliberate
    # action � never a stray/accidental DELETE. Require {"confirm": true} in the body.
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not (isinstance(body, dict) and body.get("confirm") is True):
        raise HTTPException(400, "Deactivation must be confirmed: send {\"confirm\": true}.")
    from .license import invalidate_cache
    from .db import set_license_key
    set_license_key("")
    invalidate_cache()
    db.log_audit("license", "license deactivated", "owner confirmed deactivation")
    return {"ok": True}


# ── Lemon Squeezy webhook + admin ─────────────────────────────────────────────

@app.post("/api/lemon/webhook")
async def lemon_webhook(request: Request):
    """Receive Lemon Squeezy payment webhook, issue license key, email buyer."""
    from .lemon import process_webhook, LemonWebhookError
    body = await request.body()
    signature = request.headers.get("X-Signature", "")
    try:
        result = process_webhook(body, signature)
        return result
    except LemonWebhookError as e:
        if "signature" in str(e):
            raise HTTPException(401, str(e))
        log.warning("lemon webhook skipped: %s", e)
        return {"skipped": True, "reason": str(e)}
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@app.get("/api/admin/licenses")
def admin_list_licenses(request: Request, page: int = 1,
                        per_page: int = 20, search: str = ""):
    _require_owner(request)
    licenses = db.list_issued_licenses(search=search, page=page, per_page=per_page)
    total = db.count_issued_licenses(search=search)
    return {"total": total, "page": page, "per_page": per_page, "licenses": licenses}


@app.post("/api/admin/licenses/{license_id}/revoke")
def admin_revoke_license(request: Request, license_id: int):
    _require_owner(request)
    row = db.get_issued_license(license_id)
    if not row:
        raise HTTPException(404, "License not found")
    db.revoke_issued_license(license_id)
    return {"ok": True}


@app.post("/api/admin/licenses/{license_id}/resend")
def admin_resend_license(request: Request, license_id: int):
    _require_owner(request)
    from .lemon import build_license_email_html
    from .notifications import send_email_direct
    row = db.get_issued_license(license_id)
    if not row:
        raise HTTPException(404, "License not found")
    download_url = os.environ.get("LICENSE_DOWNLOAD_URL", "")
    html = build_license_email_html(row["buyer_email"], row["license_key"], download_url)
    smtp_host = db.get_app_config("email_smtp", "")
    smtp_port = int(db.get_app_config("email_port", "587"))
    smtp_user = db.get_app_config("email_user", "")
    smtp_pass = db.get_app_config_secure("email_pass", "")
    if not smtp_host or not smtp_user or not smtp_pass:
        raise HTTPException(400, "SMTP not configured in Settings")
    send_email_direct(row["buyer_email"], smtp_host, smtp_port,
                      smtp_user, smtp_pass, "Your TradeBot License Key", html)
    db.update_resent_at(license_id)
    return {"ok": True}


@app.get("/api/admin/licenses/export")
def admin_export_licenses(request: Request):
    _require_owner(request)
    import csv
    import io
    rows = db.list_issued_licenses(per_page=100000)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["order_id", "buyer_email", "license_key", "issued_at", "revoked", "resent_at"])
    for r in rows:
        w.writerow([r["order_id"], r["buyer_email"], r["license_key"],
                    r["issued_at"], r["revoked"], r.get("resent_at", "")])
    from fastapi.responses import Response
    return Response(content=out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=licenses.csv"})


class LemonConfigBody(BaseModel):
    signing_secret: str = ""


@app.get("/api/admin/lemon-config")
def admin_get_lemon_config(request: Request):
    """Return whether the Lemon Squeezy signing secret is set, masked. Never returns the raw value."""
    _require_owner(request)
    raw = db.get_app_config_secure("lemon_signing_secret", "")
    masked = ("••••" + raw[-4:]) if len(raw) > 4 else ("•" * len(raw) if raw else "")
    return {"signing_secret_set": bool(raw), "signing_secret_masked": masked}


@app.patch("/api/admin/lemon-config")
def admin_patch_lemon_config(body: LemonConfigBody, request: Request):
    """Save the Lemon Squeezy signing secret (encrypted). Empty value preserves the existing secret."""
    _require_owner(request)
    if body.signing_secret is not None and body.signing_secret.strip():
        db.set_app_config_secure("lemon_signing_secret", body.signing_secret.strip())
        db.log_audit("license", "updated Lemon Squeezy signing secret", "")
    raw = db.get_app_config_secure("lemon_signing_secret", "")
    masked = ("••••" + raw[-4:]) if len(raw) > 4 else ("•" * len(raw) if raw else "")
    return {"signing_secret_set": bool(raw), "signing_secret_masked": masked}


# ── Account & market ───────────────────────────────────────────────────────────

@app.get("/api/account")
def account(request: Request, account_id: int | None = None):
    _require_auth(request)
    try:
        summary = _get_broker_client(account_id).get_account_summary()
    except Exception as e:
        log.warning("account %s fetch failed: %s", account_id, e)
        raise HTTPException(503, f"Broker connection failed: {_safe_broker_error(e)}")
    # For Binance accounts, attach signals-based P&L (more accurate than cost_basis table)
    if account_id is not None:
        acct_row = db.get_broker_account(account_id)
        if acct_row and (acct_row.get("broker") or "alpaca").lower() == "binance":
            pnl_data = db.crypto_pnl_from_signals(account_id)
            summary["realized_pnl"]  = pnl_data["realized_pnl"]
            summary["total_buy"]     = pnl_data["total_buy"]
            summary["total_sell"]    = pnl_data["total_sell"]
            summary["pnl_by_symbol"] = pnl_data["by_symbol"]
    return summary


@app.get("/api/crypto-pnl")
def crypto_pnl(request: Request, account_id: int):
    _require_auth(request)
    return db.crypto_pnl_from_signals(account_id)


@app.get("/api/clock")
def clock(request: Request):
    _require_auth(request)
    try:
        return alpaca_client.get_clock()
    except Exception:
        return {"is_open": False, "next_open": None, "next_close": None, "timestamp": None}

@app.get("/api/positions")
def positions(request: Request, account_id: int | None = None):
    _require_auth(request)
    try:
        return _get_broker_client(account_id).get_positions()
    except Exception as e:
        log.warning("positions %s fetch failed: %s", account_id, e)
        raise HTTPException(503, f"Broker connection failed: {_safe_broker_error(e)}")

@app.get("/api/orders")
def orders(request: Request, status: str = "all", limit: int = 50, account_id: int | None = None):
    _require_auth(request)
    try:
        return _get_broker_client(account_id).get_orders(limit=limit, status=status)
    except Exception as e:
        log.warning("orders %s fetch failed: %s", account_id, e)
        raise HTTPException(503, f"Broker connection failed: {_safe_broker_error(e)}")

@app.post("/api/orders")
def submit_order(o: OrderIn, request: Request):
    _require_auth(request)
    try:
        client = _get_broker_client(o.account_id)
        sym = o.symbol.upper()
        if o.limit_price and o.qty:
            result = client.submit_limit_order(sym, o.side, o.qty, o.limit_price)
            label = f"manual limit @${o.limit_price:.2f}"
        else:
            result = client.submit_market_order(sym, o.side, qty=o.qty, notional=o.notional)
            label = f"manual ${o.notional:.2f}" if o.notional else "manual order"
        display = o.notional if o.notional else o.qty
        db.log_signal("manual", sym, o.side, display, label, result.get("id", ""), result.get("status", ""),
                      account_id=o.account_id)
        if o.notional:
            notifications.notify_trade("manual", sym, o.side, None, o.notional, label, result.get("id", ""))
        return result
    except HTTPException:
        raise
    except BaseException as e:
        import logging, traceback
        logging.error("submit_order error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(400, str(e))

@app.get("/api/crypto-sell-perf")
def crypto_sell_perf(request: Request, account_id: int | None = None):
    _require_auth(request)
    if not account_id:
        return []
    return db.get_crypto_sell_perf(account_id)

@app.delete("/api/orders/{order_id}")
def cancel(order_id: str, request: Request, account_id: int | None = None):
    _require_auth(request)
    try:
        _get_broker_client(account_id).cancel_order(order_id)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/api/orders")
def cancel_all(request: Request, account_id: int | None = None):
    _require_auth(request)
    client = _get_broker_client(account_id)
    if hasattr(client, "cancel_all_orders"):
        client.cancel_all_orders()
    return {"ok": True}

@app.delete("/api/positions/{symbol}")
def close_pos(symbol: str, request: Request, account_id: int | None = None):
    _require_auth(request)
    try:
        _get_broker_client(account_id).close_position(symbol)
        db.log_audit("position", f"manually closed {symbol}", f"account_id={account_id}")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/api/positions")
def close_all(request: Request, account_id: int | None = None):
    _require_auth(request)
    client = _get_broker_client(account_id)
    if hasattr(client, "close_all_positions"):
        client.close_all_positions()
    db.log_audit("position", "manually closed ALL positions", f"account_id={account_id}")
    return {"ok": True}

@app.get("/api/quote/{symbol}")
def quote(symbol: str, request: Request, account_id: int | None = None):
    _require_auth(request)
    # If a specific account is requested, use that broker's quote
    if account_id is not None:
        try:
            client = _get_broker_client(account_id)
            return client.get_latest_quote(symbol)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, str(e))
    # Default: try first Alpaca DB account, fall back to Binance
    alpaca_accts = [a for a in db.get_broker_accounts() if (a.get("broker") or "alpaca") == "alpaca"]
    if alpaca_accts:
        try:
            return _get_broker_client(alpaca_accts[0]["id"]).get_latest_quote(symbol)
        except Exception:
            pass
    binance_accts = [a for a in db.get_broker_accounts() if a.get("broker") == "binance"]
    if binance_accts:
        try:
            bclient = _get_broker_client(binance_accts[0]["id"])
            return bclient.get_latest_quote(symbol)
        except Exception as e:
            raise HTTPException(400, str(e))
    raise HTTPException(400, f"No quote available for {symbol}")

@app.get("/api/quotes/snapshot")
def quotes_snapshot(symbols: str, request: Request):
    _require_auth(request)
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    try:
        results = alpaca_client.get_snapshots(syms)
    except Exception as e:
        raise HTTPException(400, str(e))

    # Fall back to Binance for any symbols that Alpaca couldn't price
    missing = [r["symbol"] for r in results if r.get("price") is None]
    if missing:
        binance_accts = [a for a in db.get_broker_accounts() if a.get("broker") == "binance"]
        if binance_accts:
            try:
                bclient = _get_broker_client(binance_accts[0]["id"])
                price_map = {r["symbol"]: r for r in results}
                for sym in missing:
                    try:
                        q = bclient.get_latest_quote(sym)
                        price_map[sym]["price"] = q.get("price")
                        price_map[sym]["bid"]   = q.get("bid")
                        price_map[sym]["ask"]   = q.get("ask")
                    except Exception:
                        pass
            except Exception:
                pass

    return results

@app.get("/api/assets/search")
def assets_search(q: str = "", request: Request = None):
    _require_auth(request)
    results = alpaca_client.search_assets(q, limit=8)
    if len(results) < 8 and q:
        # Supplement with Binance markets for crypto search
        binance_accts = [a for a in db.get_broker_accounts() if a.get("broker") == "binance"]
        if binance_accts:
            try:
                bclient = _get_broker_client(binance_accts[0]["id"])
                bclient._ensure_markets()
                q_up = q.upper()
                existing_syms = {r["symbol"] for r in results}
                for market in list(bclient._exchange.markets.values())[:2000]:
                    base = str(market.get("base", "")).upper()
                    if base.startswith(q_up) and base not in existing_syms:
                        results.append({"symbol": base, "name": f"{base} (Binance)", "tradable": True})
                        existing_syms.add(base)
                    if len(results) >= 8:
                        break
            except Exception:
                pass
    return results

@app.get("/api/portfolio_history")
def portfolio_history(request: Request, period: str = "1M", timeframe: str = "1D"):
    _require_auth(request)
    try:
        return alpaca_client.get_portfolio_history(period=period, timeframe=timeframe)
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Strategies ─────────────────────────────────────────────────────────────────

@app.get("/api/strategies")
def list_strategies(request: Request, response: Response):
    _require_auth(request)
    response.headers["Cache-Control"] = "no-store"
    saved = {s["name"]: s for s in db.get_strategies()}
    out = []
    for cls in strategies.REGISTRY.values():
        if cls.hidden:
            continue
        s = saved.get(cls.name)
        out.append({
            **cls.describe(),
            "enabled":      s["enabled"]      if s else False,
            "params":       s["params"]       if s else cls.default_params,
            "active_start": s["active_start"] if s else None,
            "active_end":   s["active_end"]   if s else None,
        })
    return out

@app.patch("/api/strategies/{name}")
def update_strategy(name: str, body: StrategyUpdate, request: Request):
    _require_auth(request)
    if name not in strategies.REGISTRY:
        raise HTTPException(404, "unknown strategy")
    current = db.get_strategy(name) or {
        "enabled": False, "params": strategies.REGISTRY[name].default_params,
        "active_start": None, "active_end": None,
    }
    enabled = body.enabled if body.enabled is not None else current["enabled"]

    # Build kwargs — only pass fields the caller actually sent so upsert_strategy
    # uses its _UNSET sentinel to leave untouched columns alone.
    kwargs: dict = {"enabled": enabled}
    if body.params is not None:
        kwargs["params"] = {**current["params"], **body.params}
    if body.active_start is not None:
        # "" means clear the schedule
        kwargs["active_start"] = None if body.active_start == "" else body.active_start
    if body.active_end is not None:
        kwargs["active_end"]   = None if body.active_end   == "" else body.active_end

    db.upsert_strategy(name, **kwargs)
    parts = []
    if body.enabled is not None:
        parts.append(f"enabled={body.enabled}")
    if body.params is not None:
        parts.append(f"params updated")
    if body.active_start is not None or body.active_end is not None:
        parts.append(f"window={kwargs.get('active_start','')}-{kwargs.get('active_end','')}")
    db.log_audit("strategy", f"updated {name}", ", ".join(parts) or "no changes")
    return db.get_strategy(name)


# ── Broker Accounts ────────────────────────────────────────────────────────────

@app.get("/api/broker-accounts")
def list_broker_accounts(request: Request):
    _require_auth(request)
    return [_mask_account(r) for r in db.get_broker_accounts()]


@app.get("/api/broker-accounts/{account_id}")
def get_broker_account(account_id: int, request: Request):
    _require_auth(request)
    row = db.get_broker_account(account_id)
    if not row:
        raise HTTPException(404, "account not found")
    return _mask_account(row)


class BrokerCredentialsTest(BaseModel):
    api_key: str
    api_secret: str
    account_type: Literal["paper", "live"] = "paper"
    broker: str = "alpaca"

@app.post("/api/setup/test-credentials")
def setup_test_credentials(body: BrokerCredentialsTest, request: Request):
    """Validate broker credentials during setup wizard (pre-auth only)."""
    if auth.setup_complete():
        # After setup, use the authenticated endpoint instead
        raise HTTPException(403, "Use /api/broker-accounts/test-credentials")
    try:
        from .broker_factory import get_account_client
        client = get_account_client(
            broker=body.broker,
            api_key=body.api_key,
            api_secret=body.api_secret,
            paper=(body.account_type == "paper"),
        )
        summary = client.get_account_summary()
        return {"ok": True, "status": summary.get("status", "active"),
                "equity": summary.get("equity", 0)}
    except Exception as e:
        raise HTTPException(400, _safe_broker_error(e))

@app.post("/api/broker-accounts/test-credentials")
def test_broker_credentials(body: BrokerCredentialsTest, request: Request):
    """Validate API credentials without saving them."""
    _require_auth(request)
    try:
        from .broker_factory import get_account_client
        client = get_account_client(
            broker=body.broker,
            api_key=body.api_key,
            api_secret=body.api_secret,
            paper=(body.account_type == "paper"),
        )
        summary = client.get_account_summary()
        return {"ok": True, "status": summary.get("status", "active"),
                "equity": summary.get("equity", 0)}
    except Exception as e:
        raise HTTPException(400, _safe_broker_error(e))

@app.post("/api/broker-accounts", status_code=201)
def create_broker_account(body: BrokerAccountCreate, request: Request):
    _require_auth(request)
    try:
        new_id = db.create_broker_account(
            body.label,
            crypto.encrypt(body.api_key),
            crypto.encrypt(body.api_secret),
            body.account_type,
            body.broker,
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    db.log_audit("account", f"created account '{body.label}'", f"type={body.account_type}, broker={body.broker}")
    return _mask_account(db.get_broker_account(new_id))


@app.patch("/api/broker-accounts/{account_id}")
def patch_broker_account(account_id: int, body: BrokerAccountPatch, request: Request):
    _require_auth(request)
    if not db.get_broker_account(account_id):
        raise HTTPException(404, "account not found")
    db.update_broker_account(account_id, label=body.label, account_type=body.account_type)
    db.log_audit("account", f"updated account #{account_id}", f"label={body.label}, type={body.account_type}")
    return _mask_account(db.get_broker_account(account_id))


@app.put("/api/broker-accounts/{account_id}/credentials")
def rotate_broker_credentials(account_id: int, body: BrokerCredentialsUpdate, request: Request):
    _require_auth(request)
    if not db.get_broker_account(account_id):
        raise HTTPException(404, "account not found")
    db.update_broker_credentials(
        account_id,
        crypto.encrypt(body.api_key),
        crypto.encrypt(body.api_secret),
    )
    _broker_client_cache.pop(account_id, None)  # force re-init with new creds
    db.log_audit("account", f"rotated credentials #{account_id}", "API key + secret replaced")
    return _mask_account(db.get_broker_account(account_id))


@app.get("/api/broker-accounts/{account_id}/status")
def broker_account_status(account_id: int, request: Request):
    _require_auth(request)
    row = db.get_broker_account(account_id)
    if not row:
        raise HTTPException(404, "account not found")
    try:
        from .broker_factory import get_account_client
        creds  = db.get_broker_account_credentials(account_id)
        _sec = creds.get("api_secret") or ""
        client = get_account_client(
            broker=row.get("broker", "alpaca"),
            api_key=crypto.decrypt(creds["api_key"]),
            api_secret=crypto.decrypt(_sec) if _sec else "",
            paper=(row["account_type"] == "paper"),
        )
        return client.get_account_summary()
    except Exception as e:
        log.warning("broker_account_status %d failed: %s", account_id, e)
        raise HTTPException(400, str(e))


@app.get("/api/broker-accounts/{account_id}/assignments")
def broker_account_assignments(account_id: int, request: Request):
    _require_auth(request)
    if not db.get_broker_account(account_id):
        raise HTTPException(404, "account not found")
    return {"strategies": db.get_broker_account_assignments(account_id)}


@app.get("/api/broker-accounts/{account_id}/strategies")
def broker_account_strategy_view(account_id: int, request: Request):
    """All strategies compatible with this account's broker, with assignment + enabled status."""
    _require_auth(request)
    acct = db.get_broker_account(account_id)
    if not acct:
        raise HTTPException(404, "account not found")
    broker = (acct.get("broker") or "alpaca").lower()
    assignments = db.get_account_strategy_assignments(account_id)
    global_strats = {s["name"]: s for s in db.get_strategies()}
    # Per-account windows: keyed by strategy name
    acct_windows = {
        row["strategy_name"]: {"active_start": row["active_start"], "active_end": row["active_end"]}
        for row in db.get_strategy_account_windows(account_id)
    }
    return [
        {
            "name": name,
            "label": cls.label,
            "description": cls.description,
            "assigned": name in assignments,
            "enabled": assignments.get(name, False),
            "active_start": acct_windows.get(name, {}).get("active_start"),
            "active_end":   acct_windows.get(name, {}).get("active_end"),
            "params": global_strats.get(name, {}).get("params") or cls.default_params,
            "params_schema": cls.params_schema,
        }
        for name, cls in strategies.REGISTRY.items()
        if not cls.hidden and _broker_matches(broker, cls.brokers)
    ]


def _broker_matches(broker: str, brokers: list[str]) -> bool:
    """Return True if `broker` is compatible with the strategy's broker list.
    Supports asset-class tokens: "stock" and "crypto".
    """
    from server.strategies.base import STOCK_BROKERS, CRYPTO_BROKERS
    for b in brokers:
        if b == "stock"  and broker in STOCK_BROKERS:  return True
        if b == "crypto" and broker in CRYPTO_BROKERS: return True
        if b == broker:                                 return True
    return False


@app.delete("/api/broker-accounts/{account_id}")
def delete_broker_account(account_id: int, request: Request):
    _require_auth(request)
    if not db.get_broker_account(account_id):
        raise HTTPException(404, "account not found")
    label = (db.get_broker_account(account_id) or {}).get("label", str(account_id))
    db.delete_broker_account(account_id)
    db.log_audit("account", f"deleted account '{label}'", f"id={account_id}")
    return {"ok": True}


@app.get("/api/broker-accounts/{account_id}/kill-switch")
def get_account_kill_switch_route(account_id: int, request: Request):
    _require_auth(request)
    if not db.get_broker_account(account_id):
        raise HTTPException(404, "account not found")
    return {"account_id": account_id, "kill_switch": db.get_account_kill_switch(account_id)}

@app.post("/api/broker-accounts/{account_id}/kill-switch")
def set_account_kill_switch_route(account_id: int, request: Request, on: bool = True):
    _require_auth(request)
    if not db.get_broker_account(account_id):
        raise HTTPException(404, "account not found")
    db.set_account_kill_switch(account_id, on)
    db.log_audit("kill_switch", f"account #{account_id} kill switch {'ON' if on else 'OFF'}", f"account_id={account_id}")
    return {"account_id": account_id, "kill_switch": on}


# ── Strategy Account Assignments ───────────────────────────────────────────────

@app.get("/api/strategies/{name}/accounts")
def list_strategy_accounts(name: str, request: Request):
    _require_auth(request)
    if name not in strategies.REGISTRY:
        raise HTTPException(404, "unknown strategy")
    return db.get_strategy_account_list(name)


@app.post("/api/strategies/{name}/accounts", status_code=201)
def assign_strategy_account(name: str, body: StrategyAccountAssign, request: Request):
    _require_auth(request)
    if name not in strategies.REGISTRY:
        raise HTTPException(404, "unknown strategy")
    if not db.get_broker_account(body.account_id):
        raise HTTPException(404, "broker account not found")
    inserted = db.assign_strategy_account(name, body.account_id, body.enabled)
    if not inserted:
        raise HTTPException(409, "account already assigned to this strategy")
    db.log_audit("strategy", f"assigned account #{body.account_id} to {name}", f"enabled={body.enabled}")
    return db.get_strategy_account_list(name)


@app.patch("/api/strategies/{name}/accounts/{account_id}")
def patch_strategy_account(name: str, account_id: int, body: StrategyAccountPatch, request: Request):
    _require_auth(request)
    if not db.update_strategy_account_enabled(name, account_id, body.enabled):
        raise HTTPException(status_code=404, detail="account not found")
    # Save per-account time window if provided
    if body.active_start is not None or body.active_end is not None:
        db.update_strategy_account_window(name, account_id, body.active_start, body.active_end)
    # Sync global enabled flag: on if any account has it enabled, off if none do
    account_list = db.get_strategy_account_list(name)
    globally_enabled = any(a["enabled"] for a in account_list)
    db.upsert_strategy(name, enabled=globally_enabled)
    db.log_audit("strategy", f"{name} account #{account_id} {'enabled' if body.enabled else 'disabled'}", "")
    return account_list


@app.delete("/api/strategies/{name}/accounts/{account_id}")
def unassign_strategy_account(name: str, account_id: int, request: Request):
    _require_auth(request)
    db.unassign_strategy_account(name, account_id)
    return {"ok": True}


# ── Performance analytics ──────────────────────────────────────────────────────

@app.get("/api/performance")
def performance_data(request: Request, account_id: int | None = None):
    _require_auth(request)
    strategy_stats = db.performance_by_strategy()
    top_syms       = db.top_symbols_overall(limit=10)
    daily          = db.daily_signal_counts(30)

    # Enrich with live unrealized P&L from open positions for the requested
    # account. When account_id is omitted, fall back to the first Alpaca account.
    try:
        if account_id is None:
            alpaca_accts = [a for a in db.get_broker_accounts() if (a.get("broker") or "alpaca") == "alpaca"]
            account_id = alpaca_accts[0]["id"] if alpaca_accts else None
        positions = _get_broker_client(account_id).get_positions() if account_id else []
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


@app.get("/api/performance/by-account")
def performance_by_account(request: Request):
    _require_auth(request)
    return db.performance_by_strategy_account()


@app.get("/api/performance/compare")
def performance_compare(request: Request):
    _require_auth(request)
    stats = db.compare_paper_vs_live()

    def _enrich(bucket: dict, account_type: str) -> dict:
        accts = [a for a in db.get_broker_accounts() if a["account_type"] == account_type]
        for acct in accts:
            try:
                creds = db.get_broker_account_credentials(acct["id"])
                from .broker_factory import get_account_client
                _sec2 = creds.get("api_secret") or ""
                client = get_account_client(
                    broker=acct.get("broker", "alpaca"),
                    api_key=crypto.decrypt(creds["api_key"]),
                    api_secret=crypto.decrypt(_sec2) if _sec2 else "",
                    paper=(account_type == "paper"),
                )
                summary = client.get_account_summary()
                bucket["equity"]       = summary.get("equity")
                bucket["day_pl_pct"]   = summary.get("day_pl_pct")
                bucket["buying_power"] = summary.get("buying_power")
                break
            except Exception:
                pass
        return bucket

    stats["paper"] = _enrich(stats.get("paper", {}), "paper")
    stats["live"]  = _enrich(stats.get("live",  {}), "live")
    return stats


# ── Signals & Engine ───────────────────────────────────────────────────────────

@app.get("/api/signals")
def signals(request: Request, limit: int = 100, since: str | None = None, until: str | None = None,
            account_id: int | None = None):
    _require_auth(request)
    return db.recent_signals(limit=min(limit, 10000), since=since, until=until, account_id=account_id)

@app.get("/api/engine")
def engine_status(request: Request):
    _require_auth(request)
    return engine.last_run()

@app.post("/api/engine/run_now")
def engine_run_now(request: Request):
    _require_auth(request)
    engine.run_tick()
    return engine.last_run()


@app.get("/api/signals/{signal_id}/explanation")
def signal_explanation(signal_id: int, request: Request):
    _require_auth(request)
    row = db.get_signal_explanation(signal_id)
    if row is None or row["explanation"] is None:
        sig = db.get_signal_by_id(signal_id)
        if sig:
            ai_explainer.enqueue(sig)
        return {"explanation": None, "ready": False, "ai_provider": None, "ai_model": None}
    return {
        "explanation": row["explanation"],
        "ready":       True,
        "ai_provider": row["ai_provider"],
        "ai_model":    row["ai_model"],
    }


@app.get("/api/ai/status")
def ai_status(request: Request):
    _require_auth(request)
    return ai_explainer.ollama_status()


@app.get("/api/ai/settings")
def ai_settings_get(request: Request):
    _require_auth(request)
    raw_key = db.get_app_config_secure("ai_claude_api_key", "")
    masked_key = ("sk-ant-..." + raw_key[-4:]) if len(raw_key) > 4 else ("*" * len(raw_key) if raw_key else "")
    return {
        "ollama_url":           db.get_app_config("ai_ollama_url", "http://localhost:11434"),
        "ollama_model":         db.get_app_config("ai_ollama_model", "llama3"),
        "explanations_enabled": db.get_app_config("ai_explanations_enabled", "true") == "true",
        "tuner_enabled":        db.get_app_config("ai_tuner_enabled", "true") == "true",
        "tuner_provider":       db.get_app_config("ai_tuner_provider", "ollama"),
        "claude_api_key_set":   bool(raw_key),
        "claude_api_key_masked": masked_key,
        "claude_model":         db.get_app_config("ai_claude_model", "claude-haiku-4-5-20251001"),
        "target_win_rate":           float(db.get_app_config("ai_target_win_rate", "51")),
        "sentiment_enabled":         db.get_app_config("sentiment_enabled", "false") == "true",
        "sentiment_block_threshold": float(db.get_app_config("sentiment_block_threshold", "-0.3")),
        "sentiment_boost_threshold": float(db.get_app_config("sentiment_boost_threshold", "0.3")),
        "sentiment_boost_multiplier":float(db.get_app_config("sentiment_boost_multiplier", "1.25")),
    }


@app.patch("/api/ai/settings")
def ai_settings_patch(body: AiSettingsBody, request: Request):
    _require_auth(request)
    if body.ollama_url is not None:
        db.set_app_config("ai_ollama_url", body.ollama_url.strip())
    if body.ollama_model is not None:
        db.set_app_config("ai_ollama_model", body.ollama_model.strip())
    if body.explanations_enabled is not None:
        db.set_app_config("ai_explanations_enabled", "true" if body.explanations_enabled else "false")
    if body.tuner_enabled is not None:
        db.set_app_config("ai_tuner_enabled", "true" if body.tuner_enabled else "false")
    if body.tuner_provider is not None and body.tuner_provider in ("ollama", "claude"):
        db.set_app_config("ai_tuner_provider", body.tuner_provider)
    if body.claude_api_key is not None and body.claude_api_key.strip():
        db.set_app_config_secure("ai_claude_api_key", body.claude_api_key.strip())
    if body.claude_model is not None and body.claude_model.strip():
        db.set_app_config("ai_claude_model", body.claude_model.strip())
    if body.target_win_rate is not None and 50 <= body.target_win_rate <= 90:
        db.set_app_config("ai_target_win_rate", str(body.target_win_rate))
    if body.sentiment_enabled is not None:
        db.set_app_config("sentiment_enabled", "true" if body.sentiment_enabled else "false")
    if body.sentiment_block_threshold is not None and -1.0 <= body.sentiment_block_threshold <= 0:
        db.set_app_config("sentiment_block_threshold", str(body.sentiment_block_threshold))
    if body.sentiment_boost_threshold is not None and 0 <= body.sentiment_boost_threshold <= 1.0:
        db.set_app_config("sentiment_boost_threshold", str(body.sentiment_boost_threshold))
    if body.sentiment_boost_multiplier is not None and 1.0 <= body.sentiment_boost_multiplier <= 2.0:
        db.set_app_config("sentiment_boost_multiplier", str(body.sentiment_boost_multiplier))
    return {"ok": True}


@app.get("/api/ai/tuning-log")
def ai_tuning_log_get(request: Request):
    _require_auth(request)
    return db.list_tuning_log()


@app.get("/api/sentiment")
def sentiment_get(request: Request):
    _require_auth(request)
    return sentiment.get_all_cached()


_tune_now_lock = threading.Lock()

@app.post("/api/ai/tune-now")
def ai_tune_now(request: Request):
    _require_auth(request)
    if not _tune_now_lock.acquire(blocking=False):
        return {"tuned": 0, "skipped": 0, "error": "already running"}
    result_holder: dict = {}
    def _run():
        try:
            result_holder["result"] = ai_tuner.run_tuning()
        finally:
            _tune_now_lock.release()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=120)
    if t.is_alive():
        return {"tuned": 0, "skipped": 0, "error": "timeout"}
    return result_holder.get("result", {"tuned": 0, "skipped": 0, "error": "no result"})


@app.post("/api/ai/tuning-log/{run_id}/revert")
def ai_tuning_revert(run_id: int, request: Request):
    _require_auth(request)
    ok = db.revert_tuning_run(run_id)
    if not ok:
        raise HTTPException(404, "Tuning run not found or strategy no longer exists")
    return {"ok": True}


# ── Export ─────────────────────────────────────────────────────────────────────

@app.get("/api/export/trades")
def export_trades(request: Request, limit: int = 5000):
    _require_auth(request)
    rows = db.recent_signals(limit=min(limit, 10000))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "timestamp", "strategy", "symbol", "side", "qty", "reason",
        "blocked", "account_id"
    ], extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "timestamp":  r.get("ts", ""),
            "strategy":   r.get("strategy", ""),
            "symbol":     r.get("symbol", ""),
            "side":       r.get("side", ""),
            "qty":        r.get("qty", ""),
            "reason":     r.get("reason", ""),
            "blocked":    r.get("blocked", ""),
            "account_id": r.get("account_id", ""),
        })
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tradebot_trades.csv"},
    )

@app.get("/api/export/positions")
def export_positions(request: Request, account_id: int | None = None):
    _require_auth(request)
    try:
        if account_id is not None:
            raw = _get_broker_client(account_id).get_positions()
        else:
            alpaca_accts = [a for a in db.get_broker_accounts() if (a.get("broker") or "alpaca") == "alpaca"]
            raw = _get_broker_client(alpaca_accts[0]["id"]).get_positions() if alpaca_accts else []
    except Exception as e:
        raise HTTPException(502, f"Broker error: {e}")
    output = io.StringIO()
    if raw:
        fields = ["symbol", "qty", "side", "avg_entry_price",
                  "current_price", "market_value", "unrealized_pl", "unrealized_plpc"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in raw:
            d = p if isinstance(p, dict) else vars(p)
            writer.writerow({f: d.get(f, getattr(p, f, "")) for f in fields})
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tradebot_positions.csv"},
    )


# ── Webhook ───────────────────────────────────────────────────────────────────

@app.get("/api/webhook/token")
def get_webhook_token_route(request: Request):
    _require_auth(request)
    token = db.get_webhook_token()
    host  = str(request.base_url)
    return {
        "token":       token if token else None,
        "configured":  bool(token),
        "webhook_url": f"{host}api/webhook/signal",
    }

@app.post("/api/webhook/token/rotate")
def rotate_webhook_token_route(request: Request):
    _require_auth(request)
    token = db.rotate_webhook_token()
    return {"token": token}

@app.post("/api/webhook/signal")
def webhook_signal(body: WebhookSignal, request: Request):
    """Accept external webhook signals. Auth via X-Webhook-Token header only."""
    import hmac as _hmac
    stored_token = db.get_webhook_token()
    if not stored_token:
        raise HTTPException(403, "Webhooks not configured. Generate a token in Settings first.")
    incoming = request.headers.get("X-Webhook-Token", "")
    if not _hmac.compare_digest(stored_token, incoming):
        raise HTTPException(401, "Invalid webhook token.")

    # Risk check + order submission
    try:
        acct_client = _get_broker_client(body.account_id)
        if acct_client:
            acct_summary = acct_client.get_account_summary()
        else:
            alpaca_accts = [a for a in db.get_broker_accounts() if (a.get("broker") or "alpaca") == "alpaca"]
            acct_summary = _get_broker_client(alpaca_accts[0]["id"]).get_account_summary() if alpaca_accts else {}
        risk.check_all(body.symbol, body.side, acct_summary, 0, account_id=body.account_id)
    except risk.RiskViolation as rv:
        db.log_signal(body.strategy, body.symbol, body.side, body.qty or 0,
                      f"webhook blocked: {rv}", blocked=True, account_id=body.account_id)
        return {"status": "blocked", "reason": str(rv)}
    except Exception as e:
        raise HTTPException(502, f"Broker error: {e}")

    try:
        if acct_client:
            result = acct_client.submit_market_order(body.symbol, body.side,
                                                     qty=body.qty, notional=body.notional)
        else:
            result = alpaca_client.submit_market_order(body.symbol, body.side,
                                                       qty=body.qty, notional=body.notional)
        db.log_signal(body.strategy, body.symbol, body.side, body.qty or 0,
                      "webhook signal executed", blocked=False, account_id=body.account_id)
        return {"status": "executed", "order_id": result.get("id")}
    except Exception as e:
        raise HTTPException(502, f"Order submission failed: {e}")


# ── Price Alerts ──────────────────────────────────────────────────────────────

@app.get("/api/alerts")
def list_alerts(request: Request, include_triggered: bool = False):
    _require_auth(request)
    return db.list_price_alerts(include_triggered=include_triggered)

@app.post("/api/alerts", status_code=201)
def create_alert(body: AlertCreate, request: Request):
    _require_auth(request)
    alert_id = db.create_price_alert(body.symbol, body.direction, body.target_price, body.note)
    return {"id": alert_id, "symbol": body.symbol.upper(),
            "direction": body.direction, "target_price": body.target_price,
            "note": body.note, "triggered": 0}

@app.delete("/api/alerts/{alert_id}", status_code=204)
def delete_alert(alert_id: int, request: Request):
    _require_auth(request)
    db.delete_price_alert(alert_id)


# ── Watchlists ─────────────────────────────────────────────────────────────────

class WatchlistCreate(BaseModel):
    name: str

class WatchlistSymbol(BaseModel):
    symbol: str

class WatchlistRename(BaseModel):
    name: str

@app.get("/api/watchlists")
def list_watchlists(request: Request):
    _require_auth(request)
    return db.get_watchlists()

@app.post("/api/watchlists", status_code=201)
def create_watchlist(body: WatchlistCreate, request: Request):
    _require_auth(request)
    try:
        return db.create_watchlist(body.name.strip())
    except Exception as e:
        raise HTTPException(400, str(e))

@app.delete("/api/watchlists/{wl_id}", status_code=204)
def delete_watchlist(wl_id: int, request: Request):
    _require_auth(request)
    db.delete_watchlist(wl_id)

@app.patch("/api/watchlists/{wl_id}")
def rename_watchlist(wl_id: int, body: WatchlistRename, request: Request):
    _require_auth(request)
    wl = db.rename_watchlist(wl_id, body.name.strip())
    if not wl:
        raise HTTPException(404, "watchlist not found")
    return wl

@app.post("/api/watchlists/{wl_id}/symbols", status_code=201)
def add_symbol(wl_id: int, body: WatchlistSymbol, request: Request):
    _require_auth(request)
    wl = db.add_watchlist_symbol(wl_id, body.symbol)
    if not wl:
        raise HTTPException(404, "watchlist not found")
    return wl

@app.delete("/api/watchlists/{wl_id}/symbols/{symbol}", status_code=204)
def remove_symbol(wl_id: int, symbol: str, request: Request):
    _require_auth(request)
    db.remove_watchlist_symbol(wl_id, symbol)


# ── Scanner ────────────────────────────────────────────────────────────────────

@app.get("/api/scanner")
def scanner_data(request: Request):
    _require_auth(request)
    return scanner.get_raw()

@app.get("/api/scanner/universe")
def scanner_universe(request: Request, min_price: float = 5.0, max_price: float = 1000.0,
                     top_actives: int = 20, top_gainers: int = 10):
    _require_auth(request)
    return scanner.get_scanner_universe(min_price, max_price, top_actives, top_gainers)


# ── Risk ───────────────────────────────────────────────────────────────────────

@app.get("/api/risk")
def risk_status(request: Request):
    _require_auth(request)
    try:
        acct = alpaca_client.get_account_summary()
    except Exception:
        acct = {}
    try:
        tc = alpaca_client.trading()
        a = tc.get_account()
        dtc = int(a.daytrade_count or 0)
    except Exception:
        dtc = 0
    return risk.status_summary(acct, dtc)

@app.get("/api/risk/stock-window")
def get_stock_window(request: Request):
    _require_auth(request)
    return {
        "stock_trading_start": db.get_app_config("stock_trading_start", ""),
        "stock_trading_end":   db.get_app_config("stock_trading_end",   ""),
    }

class StockWindowIn(BaseModel):
    stock_trading_start: str = ""
    stock_trading_end:   str = ""

class KillSwitchIn(BaseModel):
    on: bool

@app.post("/api/risk/stock-window")
def set_stock_window(body: StockWindowIn, request: Request):
    _require_auth(request)
    start = body.stock_trading_start.strip()
    end   = body.stock_trading_end.strip()
    db.set_app_config("stock_trading_start", start)
    db.set_app_config("stock_trading_end",   end)
    db.log_audit("risk", "set global stock trading window", f"{start or 'any'}–{end or 'any'}")
    return {"stock_trading_start": start, "stock_trading_end": end}

@app.post("/api/risk/kill_switch")
def set_kill(body: KillSwitchIn, request: Request):
    _require_auth(request)
    risk.set_kill_switch(body.on)
    db.log_audit("kill_switch", f"global kill switch {'ON' if body.on else 'OFF'}", "")
    return {"kill_switch": body.on}

@app.patch("/api/risk/{key}")
def update_risk_setting(key: str, body: RiskSettingUpdate, request: Request):
    _require_auth(request)
    try:
        db.set_risk_setting(key, body.value)
        db.log_audit("risk", f"set {key}", f"value={body.value}")
        return db.get_risk_settings()
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/risk/blacklist")
def get_blacklist(request: Request):
    _require_auth(request)
    return {"symbols": db.get_symbol_blacklist()}

@app.post("/api/risk/blacklist")
def add_to_blacklist(body: dict, request: Request):
    _require_auth(request)
    symbol = str(body.get("symbol", "")).strip().upper()
    if not symbol:
        raise HTTPException(400, "symbol required")
    db.add_symbol_to_blacklist(symbol)
    db.log_audit("risk", f"blacklisted {symbol}", "")
    return {"symbols": db.get_symbol_blacklist()}

@app.delete("/api/risk/blacklist/{symbol}")
def remove_from_blacklist(symbol: str, request: Request):
    _require_auth(request)
    db.remove_symbol_from_blacklist(symbol.upper())
    db.log_audit("risk", f"removed {symbol.upper()} from blacklist", "")
    return {"symbols": db.get_symbol_blacklist()}

@app.post("/api/risk/reset_losses")
def reset_losses(request: Request):
    _require_auth(request)
    db.reset_consecutive_losses()
    return {"consecutive_losses": 0}


@app.get("/api/audit")
def get_audit_log(request: Request, limit: int = 200, since: str | None = None, until: str | None = None):
    _require_auth(request)
    return db.list_audit(limit=min(limit, 500), since=since, until=until)


# ── Notifications ──────────────────────────────────────────────────────────────

@app.get("/api/notifications")
def get_notifications(request: Request):
    _require_auth(request)
    return db.get_notification_settings()

@app.post("/api/notifications")
def save_notifications(body: NotificationSettings, request: Request):
    _require_auth(request)
    for key, val in body.model_dump().items():
        plaintext = "true" if val is True else "false" if val is False else str(val)
        db.set_app_config_secure(key, plaintext)
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
    # If the landing page exists and the visitor is not authenticated,
    # show the public sales page instead of the login screen.
    landing = STATIC_DIR / "landing.html"
    if landing.exists():
        if not auth.setup_complete():
            return RedirectResponse("/setup")
        if auth.password_is_set() and not auth.validate_session(_get_token(request)):
            return FileResponse(str(landing))
    else:
        if not auth.setup_complete():
            return RedirectResponse("/setup")
        if auth.password_is_set() and not auth.validate_session(_get_token(request)):
            return RedirectResponse("/login")
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/landing")
def landing_page():
    """Public sales/landing page — always accessible."""
    landing = STATIC_DIR / "landing.html"
    if not landing.exists():
        raise HTTPException(404, "Landing page not found")
    return FileResponse(str(landing))


@app.get("/api/buy-url")
def buy_url():
    """Return the Lemon Squeezy buy URL for the landing page."""
    url = os.environ.get("LEMON_SQUEEZY_BUY_URL", "")
    return {"url": url}


# ── Backtesting ───────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    strategy:          str
    symbols:           list[str] = Field(..., min_length=1)
    start_date:        date
    end_date:          date
    initial_capital:   float = 10000.0
    position_size_pct: float = 2.0
    commission_pct:    float = 0.1
    slippage_pct:      float = 0.05
    strategy_params:   dict   = {}

    @field_validator("end_date", mode="after")
    @classmethod
    def end_after_start(cls, v, info):
        if info.data.get("start_date") and v <= info.data["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v


class BacktestRunPatch(BaseModel):
    name: str = Field(..., max_length=200)


@app.post("/api/backtest")
async def run_backtest(req: BacktestRequest, request: Request):
    _require_auth(request)
    engine_bt = bt_mod.BacktestEngine()
    try:
        result = await asyncio.to_thread(
            engine_bt.run,
            req.strategy,
            req.symbols,
            req.start_date,
            req.end_date,
            req.initial_capital,
            req.position_size_pct,
            req.commission_pct,
            req.slippage_pct,
            req.strategy_params,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@app.get("/api/backtest/runs")
async def list_backtest_runs(request: Request):
    _require_auth(request)
    return db.list_backtest_runs_with_benchmark()


@app.get("/api/backtest/runs/{run_id}")
async def get_backtest_run(run_id: int, request: Request):
    _require_auth(request)
    run = db.get_backtest_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return run


@app.patch("/api/backtest/runs/{run_id}")
async def patch_backtest_run(run_id: int, body: BacktestRunPatch, request: Request):
    _require_auth(request)
    if not db.rename_backtest_run(run_id, body.name):
        raise HTTPException(404, f"Run {run_id} not found")
    return {"status": "ok"}


@app.delete("/api/backtest/runs/{run_id}")
async def delete_backtest_run(run_id: int, request: Request):
    _require_auth(request)
    if not db.delete_backtest_run(run_id):
        raise HTTPException(404, f"Run {run_id} not found")
    return {"status": "ok"}


def _compute_drift_status(live_wr: float, live_ar: float,
                           bench_wr: float, bench_ar: float,
                           live_trades: int) -> str:
    if live_trades < 10:
        return "no_data"
    wr_div = abs(live_wr - bench_wr) / max(bench_wr, 0.001)
    ar_div = abs(live_ar - bench_ar) / max(abs(bench_ar), 0.001)
    worst = max(wr_div, ar_div)
    if worst <= 0.15:
        return "green"
    if worst <= 0.30:
        return "yellow"
    return "red"


@app.get("/api/strategy-health")
async def strategy_health(request: Request):
    _require_auth(request)
    from server.strategies import REGISTRY
    result = []
    for name in REGISTRY:
        live   = db.get_live_health_stats(name)
        bench  = db.get_benchmark(name)
        if bench is None:
            drift_status = "no_benchmark"
        else:
            drift_status = _compute_drift_status(
                live["live_win_rate"],
                live["live_avg_return_pct"],
                bench["win_rate_pct"],
                bench["avg_return_pct"],
                live["total_trades"],
            )
        result.append({
            "strategy":              name,
            "live_trades":           live["total_trades"],
            "live_win_rate":         live["live_win_rate"],
            "live_avg_return_pct":   live["live_avg_return_pct"],
            "last_trade_at":         live["last_trade_at"],
            "benchmark_run_id":      bench["id"]            if bench else None,
            "benchmark_run_name":    bench["name"]          if bench else None,
            "benchmark_start_date":  bench["start_date"]    if bench else None,
            "benchmark_end_date":    bench["end_date"]      if bench else None,
            "benchmark_total_trades":bench["total_trades"]  if bench else None,
            "benchmark_win_rate":    bench["win_rate_pct"]  if bench else None,
            "benchmark_avg_return_pct": bench["avg_return_pct"] if bench else None,
            "drift_status":          drift_status,
        })
    return result


@app.post("/api/backtest/runs/{run_id}/set-benchmark")
async def set_benchmark(run_id: int, request: Request):
    _require_auth(request)
    if not db.set_benchmark(run_id):
        raise HTTPException(404, f"Run {run_id} not found")
    return {"ok": True}
