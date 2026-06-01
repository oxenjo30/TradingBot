#!/usr/bin/env bash
# TradeBot — Ubuntu VPS deployment script
# Usage:
#   sudo bash deploy.sh                          # IP-only (no domain)
#   sudo bash deploy.sh primustrader.com         # with domain + HTTPS
#   sudo bash deploy.sh primustrader.com --email you@gmail.com
#
# Tested on Ubuntu 22.04 / 24.04 LTS

set -euo pipefail

APP_DIR="/opt/tradebot"
SERVICE_NAME="tradebot"
DOMAIN="${1:-}"
SSL_EMAIL="${3:-}"   # --email <addr> is optional arg 3

# Strip --email flag if passed as arg 2
if [[ "${2:-}" == "--email" ]]; then
    SSL_EMAIL="${3:-}"
elif [[ "${2:-}" == --email=* ]]; then
    SSL_EMAIL="${2#--email=}"
fi

# ── helpers ────────────────────────────────────────────────────────────────────
info()  { echo -e "\033[0;32m[OK]\033[0m  $*"; }
warn()  { echo -e "\033[0;33m[WARN]\033[0m $*"; }
error() { echo -e "\033[0;31m[ERR]\033[0m $*" >&2; exit 1; }
step()  { echo -e "\n\033[1;34m──► $*\033[0m"; }

[[ $EUID -eq 0 ]] || error "Run as root: sudo bash deploy.sh"

# ── 1. System info ─────────────────────────────────────────────────────────────
step "Checking system"
lsb_release -d 2>/dev/null || true
VPS_IP=$(hostname -I | awk '{print $1}')
info "VPS IP: $VPS_IP"
[[ -n "$DOMAIN" ]] && info "Domain: $DOMAIN" || warn "No domain provided — HTTP only on port 8000"

# ── 2. System packages ─────────────────────────────────────────────────────────
step "Installing system packages"
apt-get update -qq
PACKAGES="python3 python3-pip python3-venv python3-dev git curl wget ufw build-essential libssl-dev libffi-dev"
[[ -n "$DOMAIN" ]] && PACKAGES="$PACKAGES nginx certbot python3-certbot-nginx"
apt-get install -y --no-install-recommends $PACKAGES > /dev/null
info "System packages ready"

# ── 3. Python version check ────────────────────────────────────────────────────
step "Checking Python version"
PY_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3,11) else 0)")
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
[[ "$PY_OK" == "1" ]] || error "Python 3.11+ required, found $PY_VER."
info "Python $PY_VER OK"

# ── 4. App directory ───────────────────────────────────────────────────────────
step "Setting up $APP_DIR"
if [[ -d "$APP_DIR/.git" ]]; then
    warn "$APP_DIR already exists — pulling latest code"
    git -C "$APP_DIR" pull
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "$SCRIPT_DIR/server/main.py" ]]; then
        info "Copying project files from $SCRIPT_DIR"
        mkdir -p "$APP_DIR"
        rsync -a --exclude='.venv' --exclude='__pycache__' \
              --exclude='*.pyc' --exclude='trading.db' --exclude='.env' \
              "$SCRIPT_DIR/" "$APP_DIR/"
    else
        error "No project found at $SCRIPT_DIR. Copy files to $APP_DIR first."
    fi
fi
info "App directory ready"

# ── 5. Virtual environment ─────────────────────────────────────────────────────
step "Creating Python virtual environment"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip --quiet
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
info "Dependencies installed"

# ── 6. Database init ───────────────────────────────────────────────────────────
step "Initialising database"
if [[ ! -f "$APP_DIR/trading.db" ]]; then
    cd "$APP_DIR"
    "$APP_DIR/.venv/bin/python" -c "from server.db import init_db; init_db()"
    info "Database created"
else
    info "Existing trading.db kept — not overwritten"
fi

# ── 7. .env file ───────────────────────────────────────────────────────────────
step "Checking .env configuration"
if [[ ! -f "$APP_DIR/.env" ]]; then
    warn "Creating .env template at $APP_DIR/.env"
    cat > "$APP_DIR/.env" <<ENV
# ── TradeBot Environment Configuration ───────────────────────────────────────
# Fill in every value marked <REQUIRED> before starting the bot.

# AES-256 encryption key for stored broker credentials.
# Generate: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# BACK THIS UP — if lost, all stored broker API keys become unrecoverable.
DB_SECRET_KEY=<REQUIRED>

# Your seller secret for generating/validating license keys.
# Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
TRADEBOT_LICENSE_SECRET=<REQUIRED>

# ── Lemon Squeezy License Automation ─────────────────────────────────────────
# Signing secret from LS Dashboard → Webhooks → Signing secret
LEMON_SQUEEZY_SIGNING_SECRET=

# License validity in days (36500 = ~100 years = lifetime)
LICENSE_DURATION_DAYS=36500

# Lemon Squeezy product download URL (shown in buyer email)
LICENSE_DOWNLOAD_URL=

# ── Notifications (optional) ──────────────────────────────────────────────────
# SLACK_WEBHOOK_URL=
# DISCORD_WEBHOOK_URL=
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=you@gmail.com
# SMTP_PASS=your-app-password

# ── AI Trade Explanations (optional) ─────────────────────────────────────────
# ANTHROPIC_API_KEY=sk-ant-...
ENV
    echo ""
    warn "ACTION REQUIRED: edit $APP_DIR/.env and fill in DB_SECRET_KEY and TRADEBOT_LICENSE_SECRET"
    warn "  nano $APP_DIR/.env"
else
    info ".env already exists — not overwritten"
    grep -q "^DB_SECRET_KEY=." "$APP_DIR/.env" || \
        warn "DB_SECRET_KEY is empty — bot will fail to decrypt broker credentials"
    grep -q "^TRADEBOT_LICENSE_SECRET=." "$APP_DIR/.env" || \
        warn "TRADEBOT_LICENSE_SECRET is empty — license validation will fail"
fi

# ── 8. File permissions ────────────────────────────────────────────────────────
step "Setting file permissions"
chmod 600 "$APP_DIR/.env"           2>/dev/null || true
chmod 640 "$APP_DIR/trading.db"     2>/dev/null || true
chmod +x  "$APP_DIR/deploy.sh"      2>/dev/null || true
info "Permissions set"

# ── 9. systemd service ─────────────────────────────────────────────────────────
step "Installing systemd service"

# With a domain, TradeBot binds only to localhost (nginx is the public face).
# Without a domain, it binds to 0.0.0.0:8000 directly.
if [[ -n "$DOMAIN" ]]; then
    BIND="127.0.0.1:8000"
else
    BIND="0.0.0.0:8000"
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=TradeBot — Automated Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn server.main:app --host ${BIND%:*} --port 8000
Restart=always
RestartSec=10
StandardOutput=append:${APP_DIR}/server.log
StandardError=append:${APP_DIR}/server.err
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
info "systemd service installed"

# ── 10. Firewall ───────────────────────────────────────────────────────────────
step "Configuring firewall (ufw)"
ufw allow OpenSSH   > /dev/null 2>&1 || true
if [[ -n "$DOMAIN" ]]; then
    ufw allow 'Nginx Full' > /dev/null 2>&1 || true   # ports 80 + 443
    ufw delete allow 8000/tcp > /dev/null 2>&1 || true # not needed — nginx proxies
    info "Firewall: SSH + Nginx Full (80/443)"
else
    ufw allow 8000/tcp > /dev/null 2>&1 || true
    info "Firewall: SSH + port 8000"
fi
ufw --force enable > /dev/null 2>&1 || true

# ── 11. nginx + SSL (only when domain provided) ────────────────────────────────
if [[ -n "$DOMAIN" ]]; then
    step "Configuring nginx for $DOMAIN"

    # Remove default site
    rm -f /etc/nginx/sites-enabled/default

    # HTTP config (certbot will upgrade to HTTPS automatically)
    cat > "/etc/nginx/sites-available/tradebot" <<NGINX
server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";
    add_header X-XSS-Protection "1; mode=block";

    # Max upload size (for future file features)
    client_max_body_size 10M;

    # Proxy everything to TradeBot
    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_set_header   Upgrade           \$http_upgrade;
        proxy_set_header   Connection        "upgrade";
        proxy_read_timeout 120s;
        proxy_buffering    off;
    }
}
NGINX

    ln -sf /etc/nginx/sites-available/tradebot /etc/nginx/sites-enabled/tradebot
    nginx -t && systemctl restart nginx
    info "nginx configured and running"

    # ── SSL via Let's Encrypt ──────────────────────────────────────────────────
    step "Obtaining SSL certificate for $DOMAIN"

    # Build certbot command
    CERTBOT_CMD="certbot --nginx -d ${DOMAIN} -d www.${DOMAIN} --non-interactive --agree-tos --redirect"
    if [[ -n "$SSL_EMAIL" ]]; then
        CERTBOT_CMD="$CERTBOT_CMD --email $SSL_EMAIL"
    else
        CERTBOT_CMD="$CERTBOT_CMD --register-unsafely-without-email"
    fi

    if $CERTBOT_CMD; then
        info "SSL certificate obtained — HTTPS enabled"

        # Auto-renewal cron (certbot installs its own timer, but add a fallback)
        if ! crontab -l 2>/dev/null | grep -q certbot; then
            (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && systemctl reload nginx") | crontab -
            info "SSL auto-renewal cron added"
        fi
    else
        warn "SSL certificate failed — check that DNS A record for $DOMAIN points to $VPS_IP"
        warn "Re-run after DNS propagates:  certbot --nginx -d $DOMAIN -d www.$DOMAIN"
    fi
fi

# ── 12. Start TradeBot ─────────────────────────────────────────────────────────
step "Starting TradeBot"

NEEDS_CONFIG=false
grep -q "^DB_SECRET_KEY=<REQUIRED>" "$APP_DIR/.env" 2>/dev/null && NEEDS_CONFIG=true
grep -q "^TRADEBOT_LICENSE_SECRET=<REQUIRED>" "$APP_DIR/.env" 2>/dev/null && NEEDS_CONFIG=true

if [[ "$NEEDS_CONFIG" == "true" ]]; then
    warn "Cannot start — .env still has placeholder values. Fill them in first:"
    echo "     nano $APP_DIR/.env"
    echo "     sudo systemctl start $SERVICE_NAME"
else
    systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        info "TradeBot is running"
    else
        warn "Service failed to start — check logs:"
        echo "     journalctl -u $SERVICE_NAME -n 50"
    fi
fi

# ── 13. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║             TradeBot Deployment Complete                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
if [[ -n "$DOMAIN" ]]; then
    echo "  Dashboard:    https://${DOMAIN}"
    echo "  Webhook URL:  https://${DOMAIN}/api/lemon/webhook"
    echo "  License:      https://${DOMAIN}/api/license/validate"
else
    echo "  Dashboard:    http://${VPS_IP}:8000"
    echo "  Webhook URL:  http://${VPS_IP}:8000/api/lemon/webhook"
fi
echo ""
echo "  .env location:  $APP_DIR/.env"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status  $SERVICE_NAME      # status"
echo "    sudo systemctl restart $SERVICE_NAME      # restart"
echo "    journalctl -u $SERVICE_NAME -f            # live logs"
echo "    tail -f $APP_DIR/server.log               # app logs"
if [[ -n "$DOMAIN" ]]; then
    echo "    certbot renew --dry-run                  # test SSL renewal"
    echo ""
    echo "  Lemon Squeezy webhook setup:"
    echo "    URL:    https://${DOMAIN}/api/lemon/webhook"
    echo "    Event:  order_created"
    echo "    Then:   add LEMON_SQUEEZY_SIGNING_SECRET to $APP_DIR/.env"
    echo "            sudo systemctl restart $SERVICE_NAME"
fi
echo ""
