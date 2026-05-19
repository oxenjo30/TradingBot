#!/usr/bin/env bash
# TradeBot — Ubuntu VPS deployment script
# Usage: bash deploy.sh
# Tested on Ubuntu 22.04 / 24.04 LTS

set -euo pipefail

APP_DIR="/opt/tradebot"
SERVICE_NAME="tradebot"
PYTHON_MIN="3.11"

# ── helpers ────────────────────────────────────────────────────────────────────
info()  { echo -e "\033[0;32m[OK]\033[0m  $*"; }
warn()  { echo -e "\033[0;33m[WARN]\033[0m $*"; }
error() { echo -e "\033[0;31m[ERR]\033[0m $*" >&2; exit 1; }
step()  { echo -e "\n\033[1;34m──► $*\033[0m"; }

require_root() {
    [[ $EUID -eq 0 ]] || error "Run as root: sudo bash deploy.sh"
}

# ── 1. Root check ──────────────────────────────────────────────────────────────
require_root

step "Checking system"
lsb_release -d 2>/dev/null || true

# ── 2. System packages ─────────────────────────────────────────────────────────
step "Installing system packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    git curl wget ufw \
    build-essential libssl-dev libffi-dev \
    > /dev/null
info "System packages ready"

# ── 3. Python version check ────────────────────────────────────────────────────
step "Checking Python version"
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3,11) else 0)")
[[ "$PY_OK" == "1" ]] || error "Python $PYTHON_MIN+ required, found $PY_VER. Install python3.11 or newer."
info "Python $PY_VER OK"

# ── 4. App directory ───────────────────────────────────────────────────────────
step "Setting up $APP_DIR"
if [[ -d "$APP_DIR/.git" ]]; then
    warn "$APP_DIR already exists — pulling latest code"
    git -C "$APP_DIR" pull
else
    # If running from the project directory, copy files; otherwise clone from GitHub
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "$SCRIPT_DIR/server/main.py" ]]; then
        info "Copying project files from $SCRIPT_DIR to $APP_DIR"
        mkdir -p "$APP_DIR"
        rsync -a --exclude='.venv' --exclude='__pycache__' \
              --exclude='*.pyc' --exclude='trading.db' \
              --exclude='.env' \
              "$SCRIPT_DIR/" "$APP_DIR/"
    else
        error "No project found at $SCRIPT_DIR. Copy your TradeBot files to $APP_DIR first, then re-run."
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
    warn ".env not found — creating template at $APP_DIR/.env"
    cat > "$APP_DIR/.env" <<'ENV'
# ── TradeBot Environment Configuration ───────────────────────────────────────
# Fill in every value marked <REQUIRED> before starting the bot.

# Encryption key for stored broker credentials (AES-256 Fernet).
# Generate once with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# BACK THIS UP — if lost, all saved broker API keys become unrecoverable.
DB_SECRET_KEY=<REQUIRED>

# License key issued at purchase (leave blank if not using license protection).
# TRADEBOT_LICENSE_SECRET=<your-license-secret>

# Optional: Slack / Discord / Telegram / Email alerts
# SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
# DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=you@gmail.com
# SMTP_PASS=your-app-password
# ALERT_FROM_EMAIL=you@gmail.com
# ALERT_TO_EMAIL=you@gmail.com

# Optional: Anthropic API key for AI trade explanations / tuner
# ANTHROPIC_API_KEY=sk-ant-...
ENV
    echo ""
    warn "ACTION REQUIRED: Edit $APP_DIR/.env and set DB_SECRET_KEY before starting the bot."
    warn "  nano $APP_DIR/.env"
else
    info ".env already exists — not overwritten"
    # Verify DB_SECRET_KEY is set
    if ! grep -q "^DB_SECRET_KEY=." "$APP_DIR/.env"; then
        warn "DB_SECRET_KEY appears empty in .env — the bot will fail to decrypt broker credentials."
    fi
fi

# ── 8. File permissions ────────────────────────────────────────────────────────
step "Setting file permissions"
chmod 600 "$APP_DIR/.env" 2>/dev/null || true
chmod 640 "$APP_DIR/trading.db" 2>/dev/null || true
chmod +x "$APP_DIR/deploy.sh" 2>/dev/null || true
info "Permissions set"

# ── 9. systemd service ─────────────────────────────────────────────────────────
step "Installing systemd service"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=TradeBot — Automated Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
StandardOutput=append:${APP_DIR}/server.log
StandardError=append:${APP_DIR}/server.err
# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
info "Service installed and enabled (starts on boot)"

# ── 10. Firewall ───────────────────────────────────────────────────────────────
step "Configuring firewall (ufw)"
ufw allow OpenSSH  > /dev/null 2>&1 || true
ufw allow 8000/tcp > /dev/null 2>&1 || true
ufw --force enable > /dev/null 2>&1 || true
info "Firewall: SSH and port 8000 open"

# ── 11. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║              TradeBot Deployment Complete                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

if grep -q "^DB_SECRET_KEY=<REQUIRED>" "$APP_DIR/.env" 2>/dev/null; then
    echo "  ⚠  NEXT STEP — configure your .env before starting:"
    echo "     nano $APP_DIR/.env"
    echo ""
    echo "  Then start the bot:"
    echo "     sudo systemctl start $SERVICE_NAME"
else
    echo "  Starting TradeBot..."
    systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        info "TradeBot is running"
    else
        warn "Service may have failed — check logs:"
        echo "     journalctl -u $SERVICE_NAME -n 50"
    fi
fi

echo ""
echo "  Dashboard:  http://$(hostname -I | awk '{print $1}'):8000"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl start   $SERVICE_NAME   # start"
echo "    sudo systemctl stop    $SERVICE_NAME   # stop"
echo "    sudo systemctl restart $SERVICE_NAME   # restart"
echo "    sudo systemctl status  $SERVICE_NAME   # status"
echo "    journalctl -u $SERVICE_NAME -f         # live logs"
echo "    tail -f $APP_DIR/server.log            # app logs"
echo ""
