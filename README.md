# TradeBot

A professional self-hosted algorithmic trading dashboard for stocks and crypto. Built for serious traders who want full control — runs on your own machine, no monthly SaaS fees, no data sharing.

> **Commercial Software** — License required. Purchase at [your-store-url].

---

## What You Get

TradeBot is a one-time purchase that gives you a fully automated trading system with a clean web dashboard. Connect your Alpaca (stocks) and Binance (crypto) accounts and let your strategies run 24/7.

---

## Features

### Trading Engine
- **Multi-broker support** — Alpaca (stocks) and Binance (crypto) in one dashboard
- **13 built-in strategies** — ready to run out of the box, fully configurable
- **Manual order entry** — place market/limit orders directly from the UI
- **Paper & live trading** — test safely before going live
- **Kill switch** — instantly halt all bot activity per account

### Dashboard Pages
| Page | Description |
|------|-------------|
| **Dashboard** | Live P&L, open positions, account balances |
| **Bots** | Enable/disable strategies, tune parameters |
| **Positions & Orders** | Open positions and full order history with P&L |
| **Performance** | Strategy-level win rate, realized gain/loss |
| **Logs & Signals** | Filterable signal feed and audit log with date range |
| **Risk Management** | Exposure limits, kill switch, drawdown controls |
| **AI Tuning** | Automated parameter optimization powered by Claude AI |
| **Backtesting** | Historical strategy testing with equity curve |
| **Balances** | Live account balances across all brokers |
| **API Keys** | Manage broker credentials (AES-256 encrypted at rest) |
| **Settings** | App configuration |

### AI Auto-Tuning
TradeBot can analyze its own performance and automatically suggest better strategy parameters using Claude AI. Review the rationale, accept or reject changes — you stay in control.

### Security
- Session-based authentication with bcrypt password hashing
- Broker API keys encrypted with AES-256 — never stored in plain text
- All data stays on your machine — nothing is sent to any external server except your broker APIs

---

## Strategies Included

### Stocks (via Alpaca)
| Strategy | Signal Logic |
|----------|-------------|
| SMA Cross | 20/50 SMA crossover |
| RSI Mean Reversion | Oversold/overbought RSI entries |
| MACD Volume | MACD signal with volume confirmation |
| Bollinger Bands | Band touch with RSI filter |
| Momentum | Price momentum with trend filter |
| Golden Cross | 50/200 SMA golden/death cross |
| EMA Confluence | Multi-EMA alignment |
| Breakout 52W | 52-week high/low breakouts |
| Classic Chart Patterns | Head & shoulders, double top/bottom, triangles |

### Crypto (via Binance)
| Strategy | Signal Logic |
|----------|-------------|
| Crypto Trend | EMA trend-following for BTC, ETH, SOL, and more |
| Crypto RSI Bounce | RSI oversold bounce entries |
| Crypto Volatility Breakout | Bollinger Band breakout with RSI confirmation |
| Crypto Grid | Automated grid trading between price levels |

---

## Requirements

- Windows 10/11, macOS, or Linux
- Python 3.13+
- Alpaca account (paper or live) — for stock trading
- Binance account (demo or live) — for crypto trading
- Anthropic API key — optional, required only for AI Tuning

---

## Installation

Full step-by-step instructions are included in the **Installation Guide PDF** provided with your purchase.

**Quick start:**

1. Extract the zip and open a terminal in the folder
2. Run `pip install -r requirements.txt`
3. Create a `.env` file with your secret key:
   ```
   DB_SECRET_KEY=your-random-secret-key
   ```
4. Run `start.bat` (Windows) or `python server/main.py`
5. Open `http://localhost:8000` and complete the setup wizard

---

## Support

- Email: your-support-email@domain.com
- Response time: within 48 hours on business days

---

## License

This software is sold under a **single-user commercial license**. You may install and run it on one machine. Redistribution, resale, or modification for redistribution is not permitted.

&copy; 2025 TradeBot. All rights reserved.
