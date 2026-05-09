import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET", "")
ALPACA_ACCOUNT_TYPE = os.getenv("ALPACA_ACCOUNT_TYPE", "paper").lower()
PAPER = ALPACA_ACCOUNT_TYPE != "live"

DB_PATH    = BASE_DIR / "trading.db"
STATIC_DIR = BASE_DIR / "server" / "static"

# Don't raise at import time — setup wizard writes .env on first run
