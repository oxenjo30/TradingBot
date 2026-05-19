"""Generate TradeBot User Guide PDF — covers all 14 strategies and all current features."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle, HRFlowable, PageBreak,
                                 KeepTogether)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

OUT = "TradeBot_Installation_Guide.pdf"

ACCENT  = colors.HexColor("#3B82F6")
PURPLE  = colors.HexColor("#8B5CF6")
GREEN   = colors.HexColor("#10B981")
RED     = colors.HexColor("#EF4444")
YELLOW  = colors.HexColor("#F59E0B")
DARK    = colors.HexColor("#080D14")
PANEL   = colors.HexColor("#0F172A")
PANEL2  = colors.HexColor("#1E2D45")
MUTE    = colors.HexColor("#94A3B8")
WHITE   = colors.white
LIGHT   = colors.HexColor("#CBD5E1")

styles = getSampleStyleSheet()

def S(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], **kw)

Title    = S("Title",    fontSize=30, textColor=WHITE, spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica-Bold")
SubTitle = S("SubTitle", fontSize=12, textColor=MUTE,  spaceAfter=24, alignment=TA_CENTER)
ChapNum  = S("ChapNum",  fontSize=10, textColor=ACCENT, spaceAfter=4, fontName="Helvetica-Bold", spaceBefore=6)
H1       = S("H1",       fontSize=20, textColor=ACCENT, spaceBefore=20, spaceAfter=8,  fontName="Helvetica-Bold")
H2       = S("H2",       fontSize=13, textColor=WHITE,  spaceBefore=14, spaceAfter=6,  fontName="Helvetica-Bold")
H3       = S("H3",       fontSize=11, textColor=LIGHT,  spaceBefore=10, spaceAfter=4,  fontName="Helvetica-Bold")
Body     = S("Body",     fontSize=10, textColor=colors.HexColor("#C8D6E8"), spaceAfter=6,  leading=16)
Note     = S("Note",     fontSize=9,  textColor=YELLOW, spaceAfter=6,  leftIndent=12, leading=14)
Danger   = S("Danger",   fontSize=9,  textColor=RED,    spaceAfter=6,  leftIndent=12, leading=14)
Good     = S("Good",     fontSize=9,  textColor=GREEN,  spaceAfter=6,  leftIndent=12, leading=14)
Code     = S("Code",     fontSize=9,  fontName="Courier", textColor=GREEN, backColor=PANEL, spaceAfter=6, leftIndent=12, leading=14)
BulletSt = S("Bullet",  fontSize=10, textColor=colors.HexColor("#C8D6E8"), spaceAfter=4, leftIndent=16, leading=15, bulletIndent=6)
Toc      = S("Toc",      fontSize=10, textColor=MUTE,   spaceAfter=3,  leftIndent=8, leading=14)

def doc():
    d = SimpleDocTemplate(OUT, pagesize=letter,
                          leftMargin=0.85*inch, rightMargin=0.85*inch,
                          topMargin=0.85*inch, bottomMargin=0.9*inch)
    d.build(story(), onFirstPage=bg_page, onLaterPages=bg_page)
    print(f"[OK] Generated: {OUT}")

def bg_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
    # accent stripe at top
    canvas.setFillColor(ACCENT)
    canvas.rect(0, letter[1] - 3, letter[0], 3, fill=1, stroke=0)
    # footer
    canvas.setFillColor(PANEL2)
    canvas.rect(0, 0, letter[0], 0.35*inch, fill=1, stroke=0)
    canvas.setFillColor(MUTE)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(0.85*inch, 0.12*inch, "TradeBot — Complete User Guide")
    canvas.drawRightString(letter[0] - 0.85*inch, 0.12*inch, f"Page {doc.page}")
    canvas.restoreState()

def HR():
    return HRFlowable(width="100%", thickness=1, color=PANEL2, spaceAfter=10, spaceBefore=4)

def bullet(text):
    return Paragraph(f"<bullet>•</bullet> {text}", BulletSt)

def step_row(num, title, desc):
    return [Paragraph(f"<b>{num}</b>", S("sn", fontSize=11, textColor=ACCENT, fontName="Helvetica-Bold", alignment=TA_CENTER)),
            Paragraph(f"<b>{title}</b><br/><font size='9' color='#94A3B8'>{desc}</font>",
                      S("sb", fontSize=10, textColor=WHITE, leading=15))]

def steps_table(rows):
    data = [step_row(i+1, t, d) for i, (t, d) in enumerate(rows)]
    t = Table(data, colWidths=[0.38*inch, 5.5*inch])
    t.setStyle(TableStyle([
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",  (0,0), (-1,-1), 7),
        ("BOTTOMPADDING",(0,0),(-1,-1), 7),
        ("LEFTPADDING", (0,0), (0,-1), 0),
        ("LINEBELOW",   (0,0), (-1,-2), 0.5, PANEL2),
    ]))
    return t

def callout(text, kind="note"):
    colour = {"note": YELLOW, "danger": RED, "good": GREEN, "tip": ACCENT}.get(kind, YELLOW)
    prefix = {"note": "NOTE", "danger": "WARNING", "good": "TIP", "tip": "INFO"}.get(kind, "NOTE")
    data = [[Paragraph(f"<b>{prefix}</b>",
                       S("cp", fontSize=8, textColor=colour, fontName="Helvetica-Bold")),
             Paragraph(text, S("cb", fontSize=9, textColor=colour, leading=14))]]
    t = Table(data, colWidths=[0.55*inch, 5.33*inch])
    bg = colors.HexColor({
        "note": "#1C1400", "danger": "#1C0000", "good": "#001C0E", "tip": "#00101C"
    }.get(kind, "#1C1400"))
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), bg),
        ("ROUNDEDCORNERS", [6]),
        ("TOPPADDING",   (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0), (-1,-1), 8),
        ("LEFTPADDING",  (0,0), (-1,-1), 10),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]))
    return KeepTogether([Spacer(1, 4), t, Spacer(1, 8)])

def th_table(headers, rows, col_widths):
    data = [headers] + rows
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  ACCENT),
        ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 9),
        ("BACKGROUND",    (0,1), (-1,-1), PANEL),
        ("TEXTCOLOR",     (0,1), (-1,-1), colors.HexColor("#C8D6E8")),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [PANEL, colors.HexColor("#162030")]),
        ("ALIGN",         (0,0), (-1,-1), "LEFT"),
        ("PADDING",       (0,0), (-1,-1), 7),
        ("GRID",          (0,0), (-1,-1), 0.5, PANEL2),
        ("FONTNAME",      (0,1), (0,-1),  "Helvetica-Bold"),
    ]))
    return t

# ── story ─────────────────────────────────────────────────────────────────────
def story():
    e = []

    # ── Cover ──────────────────────────────────────────────────────────────────
    e += [Spacer(1, 1.0*inch),
          Paragraph("TradeBot", Title),
          Paragraph("Complete User Guide", SubTitle),
          Spacer(1, 0.2*inch),
          HR()]

    cover = Table([[
        Paragraph("Automated Algorithmic Trading Platform", S("ct", fontSize=13, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_CENTER)),
    ],[
        Paragraph("14 Built-in Strategies  •  10-Layer Risk Engine  •  Crypto &amp; Stocks  •  AI-Powered", S("cs", fontSize=10, textColor=MUTE, alignment=TA_CENTER)),
    ]], colWidths=["100%"])
    cover.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), PANEL),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("ROUNDEDCORNERS",[10]),
    ]))
    e += [cover, Spacer(1, 0.3*inch), HR()]

    feature_data = [
        ["14 Built-in Strategies", "7 stock + 4 crypto + EMA Confluence + Chart Patterns + Manual"],
        ["10-Layer Risk Engine",   "Kill switch, loss limits, PDT, max positions, symbol exposure"],
        ["Stocks & Crypto",        "Alpaca & Tradier for equities; Binance for 24/7 crypto spot"],
        ["AI Trade Explanations",  "Every trade explained in plain English via Claude or Ollama"],
        ["Weekly Auto-Tuner",      "AI optimises strategy parameters every Sunday 11 PM ET"],
        ["Backtesting Studio",     "Historical simulation with slippage, commission & drift monitor"],
        ["Webhook Signals",        "Receive buy/sell signals from TradingView or any HTTP source"],
        ["Price Alerts",           "Notify via Slack, Discord, Telegram, or email when price hits target"],
    ]
    ft = Table(feature_data, colWidths=[2.2*inch, 3.7*inch])
    ft.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), PANEL),
        ("TEXTCOLOR",    (0,0), (0,-1),  ACCENT),
        ("FONTNAME",     (0,0), (0,-1),  "Helvetica-Bold"),
        ("TEXTCOLOR",    (1,0), (1,-1),  colors.HexColor("#C8D6E8")),
        ("FONTSIZE",     (0,0), (-1,-1), 9),
        ("PADDING",      (0,0), (-1,-1), 6),
        ("GRID",         (0,0), (-1,-1), 0.5, PANEL2),
        ("ROWBACKGROUNDS",(0,0),(-1,-1), [PANEL, colors.HexColor("#162030")]),
    ]))
    e += [ft, PageBreak()]

    # ── Table of Contents ──────────────────────────────────────────────────────
    e += [Paragraph("Table of Contents", H1), HR()]
    toc = [
        ("1", "What is TradeBot?"),
        ("2", "Installation & First-time Setup"),
        ("3", "Broker Accounts"),
        ("4", "Strategies & Bots"),
        ("    4.1", "Stock Strategies (9 total)"),
        ("    4.2", "Crypto Strategies (4 total)"),
        ("5", "Crypto Trading with Binance"),
        ("6", "Manual Orders"),
        ("7", "Risk Controls"),
        ("8", "Kill Switch"),
        ("9", "Take-Profit"),
        ("10", "Price Alerts"),
        ("11", "Performance Analytics"),
        ("12", "Strategy Health & Drift Monitor"),
        ("13", "Backtesting Studio"),
        ("14", "AI Tuning & Trade Explanations"),
        ("15", "Webhook Signals"),
        ("16", "Notifications (Email, Telegram, Slack, Discord)"),
        ("17", "Going Live with Real Money"),
        ("18", "VPS Deployment"),
        ("19", "Troubleshooting & FAQ"),
    ]
    for num, title in toc:
        e.append(Paragraph(f"<b>{num}</b>    {title}", Toc))
    e.append(PageBreak())

    # ── Ch 1 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 1", ChapNum),
          Paragraph("What is TradeBot?", H1), HR(),
          Paragraph("TradeBot is an automated algorithmic trading platform that connects to your broker accounts, runs 14 built-in strategies on a 60-second engine tick, enforces multi-layer risk controls, explains every trade with AI, and supports both stocks and crypto — all from one web dashboard.", Body),
          Paragraph("It runs continuously on your PC or a VPS and monitors the market every minute. You control everything from a browser — no coding required.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Key principles:", H2),
          bullet("<b>Paper-first</b> — defaults to paper trading. No real money at risk until you explicitly add a live account."),
          bullet("<b>Transparent</b> — every signal, block, and order is logged with a full reason."),
          bullet("<b>Risk-first</b> — 10 configurable guards run before every order, from strategies and webhooks alike."),
          bullet("<b>AI-assisted</b> — every trade gets a plain-English explanation and weekly parameter tuning."),
          Spacer(1, 0.1*inch),
          callout("TradeBot is a tool, not financial advice. Past strategy performance does not guarantee future results. Always run paper trading first.", "danger"),
          PageBreak()]

    # ── Ch 2 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 2", ChapNum),
          Paragraph("Installation & First-time Setup", H1), HR(),
          Paragraph("System Requirements", H2),
          bullet("Windows 10/11 64-bit <b>or</b> Ubuntu 22.04/24.04 LTS (for VPS)"),
          bullet("Python 3.11 or newer"),
          bullet("Internet connection"),
          bullet("500 MB free disk space"),
          Spacer(1, 0.15*inch),
          Paragraph("Windows — Quick Start", H2),
          steps_table([
              ("Run setup.bat", "Double-click setup.bat. It installs Python if missing, creates a virtual environment, and installs all dependencies."),
              ("Configure .env", "Create a .env file in the project folder. Set DB_SECRET_KEY (generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"). Back this up — if lost, stored broker credentials are unrecoverable."),
              ("Start the server", "Double-click start.bat or run: uvicorn server.main:app --port 8000. The dashboard opens at http://localhost:8000."),
              ("Set your password", "On first launch you are prompted to create a dashboard password."),
              ("Add a broker account", "Go to Broker Accounts → Add Account. Pick your broker, enter API keys, and click Test."),
              ("Enable a strategy", "Go to Bots & Strategies, select your account, and toggle a strategy on."),
          ]),
          Spacer(1, 0.1*inch),
          callout("Keep your .env file private. Never commit it to version control or share it. It contains your encryption key.", "danger"),
          PageBreak()]

    # ── Ch 3 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 3", ChapNum),
          Paragraph("Broker Accounts", H1), HR(),
          Paragraph("TradeBot supports multiple broker accounts simultaneously. Each account has its own type (Paper or Live), credentials, and strategy assignments — managed independently.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Supported Brokers", H2),
          th_table(
              ["Broker", "Asset Class", "Paper Trading"],
              [
                  ["Alpaca",  "US Stocks & ETFs",        "Yes — separate paper API keys (start with PK)"],
                  ["Tradier", "US Stocks & Options",     "Yes — sandbox API at sandbox.tradier.com"],
                  ["Binance", "Crypto Spot (USDT pairs)","Yes — demo keys from demo.binance.com (separate from live)"],
              ],
              [1.2*inch, 2*inch, 2.7*inch]
          ),
          Spacer(1, 0.15*inch),
          Paragraph("Adding an Account", H2),
          steps_table([
              ("Click Add Account", "On the Broker Accounts page, click Add Account. Choose your broker from the tabbed picker (Stocks, Crypto, Forex, Futures)."),
              ("Select Paper or Live", "Each account is independently Paper or Live. For Binance paper trading, use demo keys from demo.binance.com — separate from your live keys."),
              ("Enter API credentials", "Paste your API Key and Secret. Keys are encrypted with AES-256 immediately — the secret is never stored in plaintext."),
              ("Test connectivity", "Click Test on the account card. A green tick means TradeBot can reach the broker and decrypt your credentials successfully."),
              ("Assign strategies", "Go to Bots & Strategies to assign strategies to this account."),
          ]),
          callout("If you lose your DB_SECRET_KEY from .env, stored broker credentials cannot be decrypted. Back up .env securely.", "danger"),
          PageBreak()]

    # ── Ch 4 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 4", ChapNum),
          Paragraph("Strategies & Bots", H1), HR(),
          Paragraph("TradeBot ships with 14 automated strategies. The engine evaluates all enabled strategies every 60 seconds. Stock strategies only run during US market hours; crypto strategies run 24/7.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("4.1  Stock Strategies (9 total)", H2),
          th_table(
              ["Strategy", "Signal Logic", "Best for"],
              [
                  ["Momentum",           "Top actives/gainers + price above 20-day SMA + RSI 40-70",              "Trending markets, high-volume days"],
                  ["RSI Mean Reversion", "Buy RSI < 30 (oversold); exit RSI > 50",                                "Range-bound stocks, post-selloff rebounds"],
                  ["MACD + Volume",      "Bullish MACD crossover confirmed by above-average volume",              "Momentum with volume confirmation"],
                  ["Bollinger Bands",    "Buy price touches lower band + RSI oversold; exit at middle band",      "Low-volatility mean-reverting stocks"],
                  ["Golden Cross",       "50-day SMA crosses above 200-day SMA",                                  "Long-term trend following"],
                  ["SMA Crossover",      "Fast SMA crosses above slow SMA (configurable periods)",                "Short-term trend detection"],
                  ["52-Week Breakout",   "Price closes above 52-week high on strong volume surge",                "Breakout & momentum stocks"],
                  ["EMA Confluence",     "8/21/50/200 EMAs all aligned in same direction; scaled sizing",         "High-conviction trend entries"],
                  ["Classic Patterns",   "Candlestick & continuation patterns; EMA-200 trend filter on entry",   "Pattern-based swing trading"],
              ],
              [1.4*inch, 2.6*inch, 1.9*inch]
          ),
          Spacer(1, 0.15*inch),
          Paragraph("4.2  Crypto Strategies (4 total)", H2),
          th_table(
              ["Strategy", "Signal Logic"],
              [
                  ["Crypto Trend",             "EMA crossover (fast vs. slow). Buy bullish crossover, sell bearish crossover."],
                  ["Crypto RSI Bounce",         "Buy RSI < oversold threshold; sell RSI > overbought threshold."],
                  ["Crypto Volatility Breakout","Buy price touches lower Bollinger Band + oversold RSI; exit at SMA (middle band)."],
                  ["Crypto Grid",               "Divides price range into bands. Buys near band bottoms, sells near tops. Auto-detects range. Trend SMA filter prevents buying in downtrends."],
              ],
              [1.7*inch, 4.2*inch]
          ),
          Spacer(1, 0.1*inch),
          Paragraph("Enabling a Strategy", H2),
          steps_table([
              ("Open Bots & Strategies", "Select a broker account in the left panel. Compatible strategies appear on the right."),
              ("Toggle a strategy on",   "Flip the toggle. The engine picks it up on the next 60-second tick."),
              ("Adjust parameters",      "Expand any strategy to edit notional size, indicator periods, symbol lists, and more. Changes take effect immediately."),
          ]),
          callout("Stock strategies only run during US market hours (9:30 AM – 4:00 PM ET). Crypto runs 24/7.", "tip"),
          PageBreak()]

    # ── Ch 5 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 5", ChapNum),
          Paragraph("Crypto Trading with Binance", H1), HR(),
          Paragraph("TradeBot connects to Binance for 24/7 spot trading. All pairs trade against USDT (e.g., BTC/USDT, ETH/USDT). Paper and live accounts use completely separate API keys.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Getting Binance API Keys", H2),
          steps_table([
              ("Paper Trading — Binance Demo",
               "Go to demo.binance.com, create an account, and generate API keys under API Management. Demo keys only work with the demo exchange — they will not work on live."),
              ("Live Trading — Binance.com",
               "Go to binance.com → API Management. Create a key with Spot & Margin Trading enabled. Disable withdrawals for safety."),
              ("Add in TradeBot",
               "Broker Accounts → Add Account → Crypto tab → Binance → select Paper or Live → paste keys → Test."),
          ]),
          callout("Binance demo keys and live keys are completely separate. Using a live key on a Paper account (or vice versa) will cause a decryption or authentication error.", "danger"),
          Spacer(1, 0.1*inch),
          Paragraph("Common Binance Issues", H2),
          bullet("<b>DB_SECRET_KEY not loaded</b> — Make sure DB_SECRET_KEY is in your .env file. Without it, the app cannot decrypt stored API keys and all Binance ticks will silently fail."),
          bullet("<b>Demo vs. live key mismatch</b> — Paper accounts need keys from demo.binance.com. Live accounts need keys from binance.com."),
          bullet("<b>Insufficient balance</b> — Binance minimum order is ~$10 USDT. Orders below this are skipped with a log entry."),
          bullet("<b>Price in neutral zone</b> — The Crypto Grid strategy only signals near band tops/bottoms. Price in the middle of a band means no signal — this is correct behaviour."),
          PageBreak()]

    # ── Ch 6 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 6", ChapNum),
          Paragraph("Manual Orders", H1), HR(),
          Paragraph("Place trades directly from the Positions & Orders page without waiting for a strategy signal. Manual orders execute as immediate market orders.", Body),
          Spacer(1, 0.1*inch),
          steps_table([
              ("Select an account",        "Use the account dropdown inside the order ticket."),
              ("Choose Buy or Sell",        "Enter a ticker (e.g., AAPL or BTC/USDT) and click Quote for the live price."),
              ("Set quantity or dollar amt","Switch between Shares and Dollars mode, enter your amount, then click Place Order."),
          ]),
          callout("Manual orders bypass the strategy engine and risk guards. They execute immediately.", "danger"),
          PageBreak()]

    # ── Ch 7 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 7", ChapNum),
          Paragraph("Risk Controls", H1), HR(),
          Paragraph("Every signal — from strategies or webhooks — passes through 10 configurable risk guards before an order is placed. The first failing guard blocks the trade and logs the reason.", Body),
          Spacer(1, 0.1*inch),
          th_table(
              ["Guard", "What it does"],
              [
                  ["Kill Switch",        "Master emergency stop. All automated trading halts immediately."],
                  ["Daily Loss Limit",   "Halts trading when today's P&L drops below N% of starting equity."],
                  ["Weekly Loss Limit",  "Same as daily but over a rolling 7-day window."],
                  ["Consecutive Losses", "Blocks new trades after N losses in a row."],
                  ["PDT Protection",     "Prevents a 4th day-trade in a 5-day rolling window (accounts under $25K, stocks only)."],
                  ["Max Positions",      "Caps total open positions (separate limits for stocks and crypto)."],
                  ["Symbol Exposure",    "Prevents allocating more than N% of portfolio to a single symbol."],
                  ["Max Orders/Day",     "Limits total orders submitted in one trading day."],
                  ["Trading Hours",      "Only allows orders between configured start/end times ET. Crypto is exempt."],
                  ["No-Trade List",      "Blacklisted symbols are never traded regardless of signals."],
              ],
              [1.6*inch, 4.3*inch]
          ),
          callout("Recommended starting settings: max daily loss 2%, max positions 5, trading hours 9:30–15:45 ET, PDT protection on.", "good"),
          PageBreak()]

    # ── Ch 8 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 8", ChapNum),
          Paragraph("Kill Switch", H1), HR(),
          Paragraph("The kill switch is your emergency stop. One click halts all automated trading instantly. Manual orders still work.", Body),
          Paragraph("Global vs. Per-Account", H2),
          Paragraph("The global kill switch on the Risk page stops all accounts at once. Each broker account card also has its own per-account kill switch — useful when you want to pause one account while others continue trading.", Body),
          Paragraph("How to activate", H2),
          Paragraph("Go to Risk → click the red Activate Kill Switch button. A red banner appears across all pages. Click Deactivate to resume trading.", Body),
          callout("The kill switch does NOT close existing positions. It only stops new orders. To close all positions, use the close-all button on the Positions page.", "tip"),
          PageBreak()]

    # ── Ch 9 ───────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 9", ChapNum),
          Paragraph("Take-Profit", H1), HR(),
          Paragraph("Automatically close positions when they reach a target gain percentage, without needing a sell signal from the strategy.", Body),
          Paragraph("How it works", H2),
          Paragraph("After every 60-second engine tick, TradeBot scans all open positions. Any position whose unrealized gain equals or exceeds the take-profit threshold triggers an immediate market sell. Stock and crypto accounts each have their own configurable take-profit percentage.", Body),
          Paragraph("Configuration", H2),
          Paragraph("Go to Risk → Take-Profit section. Set Stock Take-Profit % and Crypto Take-Profit % separately. Set to 0 to disable.", Body),
          callout("Take-profit exits bypass the strategy kill switch and normal risk guards — they're designed to lock in gains even when the engine is otherwise paused.", "tip"),
          PageBreak()]

    # ── Ch 10 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 10", ChapNum),
          Paragraph("Price Alerts", H1), HR(),
          Paragraph("Set price thresholds on any symbol. When price crosses your target, you receive an instant notification via all configured channels.", Body),
          Spacer(1, 0.1*inch),
          steps_table([
              ("Go to Settings → Price Alerts", "Enter a symbol, choose Above or Below, and set your target price."),
              ("Save the alert",                "Active alerts are checked every 60-second engine tick using live quotes."),
              ("Get notified",                  "When triggered, alerts fire to all configured channels (Slack, Discord, Telegram, email). The alert is marked triggered and won't re-fire."),
          ]),
          PageBreak()]

    # ── Ch 11 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 11", ChapNum),
          Paragraph("Performance Analytics", H1), HR(),
          Paragraph("Track trading history, per-strategy stats, per-account P&L, and equity curve over time.", Body),
          Spacer(1, 0.1*inch),
          th_table(
              ["Widget", "Description"],
              [
                  ["Equity Curve",          "Portfolio value over time. Toggle 1W, 1M, 3M, 1Y views."],
                  ["Strategy Stats",        "Per-strategy: signals, fills, blocks, win rate, Sharpe ratio."],
                  ["Attribution by Account","Breakdown of signals and fills per strategy × account pair."],
                  ["Top Symbols",           "Most-traded symbols by signal count and fill rate."],
                  ["Daily Activity",        "Bar chart of signals per day over the last 30 days."],
              ],
              [1.8*inch, 4.1*inch]
          ),
          Spacer(1, 0.1*inch),
          Paragraph("Interpreting fill rate", H2),
          Paragraph("Fill rate = filled signals ÷ total signals. Below 50% usually means risk guards are blocking most signals. Check Logs → filter by Blocked to see which guard triggers most.", Body),
          PageBreak()]

    # ── Ch 12 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 12", ChapNum),
          Paragraph("Strategy Health & Drift Monitor", H1), HR(),
          Paragraph("Strategy Health compares live trading performance against backtest benchmarks. It detects when a strategy is drifting from its expected behaviour.", Body),
          Spacer(1, 0.1*inch),
          th_table(
              ["Status", "Meaning", "Action"],
              [
                  ["No Drift",     "Live win rate is within normal range of backtest.", "No action needed."],
                  ["Minor Drift",  "Live performance is below backtest by a noticeable margin.", "Monitor closely. Consider re-tuning."],
                  ["Major Drift",  "Live performance significantly underperforms backtest.", "Pause the strategy and re-tune parameters."],
                  ["No Benchmark", "No backtest has been run for this strategy.", "Run a backtest to enable drift monitoring."],
              ],
              [1.2*inch, 2.5*inch, 2.2*inch]
          ),
          callout("Run a backtest for each strategy you enable. This establishes the benchmark for drift detection and gives the AI Tuner a reference for weekly optimisation.", "tip"),
          PageBreak()]

    # ── Ch 13 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 13", ChapNum),
          Paragraph("Backtesting Studio", H1), HR(),
          Paragraph("Test any of the 14 strategies against historical price data before risking real money. Saved runs persist for comparison.", Body),
          Spacer(1, 0.1*inch),
          steps_table([
              ("Choose strategy & symbols",  "Select from the strategy dropdown. Enter tickers separated by commas (e.g., AAPL, MSFT or BTC/USDT, ETH/USDT)."),
              ("Set date range & costs",     "Set start/end dates (30 days minimum), initial capital, position size %, commission %, and slippage %."),
              ("Run and save",               "Click Run Backtest. Results show total return, win rate, max drawdown, Sharpe ratio, and a full trade log. Name the run to save it."),
          ]),
          Spacer(1, 0.1*inch),
          Paragraph("Key metrics", H2),
          th_table(
              ["Metric", "Meaning"],
              [
                  ["Total Return",  "Net profit as % of starting capital over the test period."],
                  ["Win Rate",      "% of trades that closed with a profit."],
                  ["Max Drawdown",  "Largest peak-to-trough decline. Over 20% is a warning sign."],
                  ["Sharpe Ratio",  "Risk-adjusted return. Above 1.0 acceptable; above 2.0 excellent."],
                  ["Avg Trade P&L", "Average dollar profit/loss per completed trade."],
              ],
              [1.5*inch, 4.4*inch]
          ),
          callout("Past performance does not predict future results. Backtests use daily bar data and assume unlimited liquidity.", "danger"),
          PageBreak()]

    # ── Ch 14 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 14", ChapNum),
          Paragraph("AI Tuning & Trade Explanations", H1), HR(),
          Paragraph("Trade Explanations", H2),
          Paragraph("Every time a trade executes, TradeBot queues an AI explanation job. The AI reads the signal reason (indicator values, crossover details, pattern names) and writes a 2–3 sentence plain-English explanation. Explanations appear in the Logs page next to each signal.", Body),
          Paragraph("Two providers are supported:", Body),
          bullet("<b>Claude</b> (Anthropic API) — requires ANTHROPIC_API_KEY in your .env file"),
          bullet("<b>Ollama</b> (local, free) — requires Ollama running on your machine at localhost:11434"),
          Spacer(1, 0.1*inch),
          Paragraph("Weekly Auto-Tuner", H2),
          Paragraph("Every Sunday at 11 PM ET, the auto-tuner analyses each strategy's live win rate against the backtest benchmark and proposes adjusted parameters (RSI thresholds, EMA periods, notional sizes, etc.) to improve performance. Results are logged on the AI Tuning page.", Body),
          callout("You can trigger a manual tuning run at any time from the AI Tuning page. Suggestions can be applied with one click.", "tip"),
          PageBreak()]

    # ── Ch 15 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 15", ChapNum),
          Paragraph("Webhook Signals", H1), HR(),
          Paragraph("TradeBot can receive trade signals from TradingView, custom scripts, or any HTTP client. Incoming signals go through the full 10-layer risk engine before execution.", Body),
          Spacer(1, 0.1*inch),
          steps_table([
              ("Get your URL and token", "Go to Settings → Webhook section. Copy your unique URL and secret token."),
              ("Send a POST request",    "POST to /api/webhook/signal with header X-Webhook-Token: <token> and a JSON body."),
          ]),
          Spacer(1, 0.1*inch),
          Paragraph("Signal JSON format", H2),
          th_table(
              ["Field", "Type", "Description"],
              [
                  ["symbol",     "string",  "Ticker symbol (e.g., AAPL or BTC/USDT)"],
                  ["side",       "string",  "buy or sell"],
                  ["qty",        "number",  "Shares or units (use this OR notional)"],
                  ["notional",   "number",  "Dollar amount to trade (use this OR qty)"],
                  ["account_id", "integer", "Optional — target a specific broker account by ID"],
              ],
              [1.0*inch, 0.7*inch, 4.2*inch]
          ),
          PageBreak()]

    # ── Ch 16 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 16", ChapNum),
          Paragraph("Notifications", H1), HR(),
          Paragraph("Get alerted on trades, risk blocks, price alerts, and daily summaries via email, Telegram, Slack, or Discord.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Email (Gmail / SMTP)", H2),
          steps_table([
              ("Generate a Gmail App Password", "Google Account → Security → 2-Step Verification → App passwords → generate one for TradeBot."),
              ("Fill in SMTP settings",         "Host: smtp.gmail.com  |  Port: 587  |  Username: your Gmail  |  Password: the App Password."),
          ]),
          Spacer(1, 0.1*inch),
          Paragraph("Telegram", H2),
          steps_table([
              ("Create a bot via BotFather", "Message @BotFather in Telegram, run /newbot, follow the steps, and copy the Bot Token."),
              ("Get your Chat ID",           "Start a chat with your bot, then visit api.telegram.org/bot<TOKEN>/getUpdates to find your chat ID. Paste both into Settings."),
          ]),
          Spacer(1, 0.1*inch),
          Paragraph("Slack & Discord", H2),
          Paragraph("Both use incoming webhooks.", Body),
          bullet("<b>Slack</b>: Apps → Incoming Webhooks → Add to Slack → copy the webhook URL."),
          bullet("<b>Discord</b>: Server Settings → Integrations → Webhooks → New Webhook → copy URL."),
          Paragraph("Paste the URL into Settings → Notifications → Slack Webhook URL or Discord Webhook URL.", Body),
          PageBreak()]

    # ── Ch 17 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 17", ChapNum),
          Paragraph("Going Live with Real Money", H1), HR(),
          callout("Only switch to live trading after at least 2–4 weeks of successful paper trading.", "danger"),
          Spacer(1, 0.1*inch),
          Paragraph("Pre-Live Checklist", H2),
          bullet("Ran paper trading for at least 2–4 weeks"),
          bullet("Understand which strategies are enabled and why"),
          bullet("Daily loss limit is set (2% recommended)"),
          bullet("Position sizes are appropriate for your account size"),
          bullet("Notifications configured (email or Telegram minimum)"),
          bullet("Kill switch accessible from phone/tablet"),
          Spacer(1, 0.15*inch),
          Paragraph("Switching to Live", H2),
          Paragraph("Go to Broker Accounts → Add Account → pick your broker → select Live → enter your live API keys → Test → assign strategies.", Body),
          Paragraph("For Alpaca: your live account requires identity verification and a linked bank account at alpaca.markets.", Body),
          Paragraph("For Binance: generate live API keys at binance.com → API Management with Spot & Margin Trading enabled and withdrawals disabled.", Body),
          PageBreak()]

    # ── Ch 18 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 18", ChapNum),
          Paragraph("VPS Deployment (Ubuntu)", H1), HR(),
          Paragraph("Running TradeBot on a VPS lets it trade 24/7 without keeping your PC on. Recommended: Ubuntu 22.04 or 24.04 LTS on DigitalOcean ($6/mo) or Hetzner CX22 (~€4/mo).", Body),
          Spacer(1, 0.1*inch),
          Paragraph("One-command deploy", H2),
          Paragraph("A deploy.sh script is included in the project. It handles everything automatically:", Body),
          bullet("Installs Python 3, git, ufw, and build tools"),
          bullet("Copies project files to /opt/tradebot"),
          bullet("Creates a Python virtual environment and installs dependencies"),
          bullet("Initialises trading.db (skips if one already exists)"),
          bullet("Creates a .env template if none exists"),
          bullet("Installs and enables a systemd service (auto-starts on reboot, restarts on crash)"),
          bullet("Opens port 8000 and SSH in UFW firewall"),
          Spacer(1, 0.1*inch),
          Paragraph("Deploy steps", H2),
          steps_table([
              ("Clone the repo on your VPS",    "git clone https://github.com/your-repo/TradeBot.git /opt/tradebot-src && cd /opt/tradebot-src"),
              ("Run the deploy script",         "sudo bash deploy.sh"),
              ("Configure .env",                "sudo nano /opt/tradebot/.env — set DB_SECRET_KEY and any notification tokens."),
              ("Start the bot",                 "sudo systemctl start tradebot"),
              ("Check status",                  "sudo systemctl status tradebot\njournalctl -u tradebot -f  (live logs)"),
          ]),
          callout("Dashboard will be accessible at http://<your-vps-ip>:8000. Secure with a strong password and consider a reverse proxy (nginx) with HTTPS.", "note"),
          PageBreak()]

    # ── Ch 19 ──────────────────────────────────────────────────────────────────
    e += [Paragraph("Chapter 19", ChapNum),
          Paragraph("Troubleshooting & FAQ", H1), HR()]

    faq = [
        ("Strategy not placing orders",
         "Check: (1) Strategy is enabled for a broker account on the Bots page. (2) A risk guard isn't blocking it — check Logs for Blocked signals. (3) Stock strategy: is the market open? (4) Crypto: is DB_SECRET_KEY set in .env? (5) Does the symbol meet the strategy criteria?"),
        ("Binance not trading",
         "Most common causes: (1) DB_SECRET_KEY missing from .env — decrypt fails silently. (2) Demo vs. live key mismatch — paper needs demo.binance.com keys. (3) Balance below $10 USDT minimum. (4) Price in neutral zone — Crypto Grid only signals near band tops/bottoms."),
        ("Bot stopped generating signals",
         "Check Logs for the reason. Common: price moved outside strategy criteria (normal), risk guard blocked all signals, or market closed for stock strategies."),
        ("Fill rate is very low (lots of Blocked signals)",
         "A risk guard is blocking most trades. Filter Logs to Blocked and read the reason column — it names exactly which guard triggered. Adjust that guard in Risk Controls."),
        ("PDT rule block",
         "Your account is under $25,000 and used 3 day-trades in a 5-day window. The block lifts automatically. Fund above $25,000 to become PDT-exempt. PDT does not apply to crypto."),
        ("Daily loss limit triggered",
         "The kill switch activated automatically. Review your positions, adjust the loss limit in Risk Controls if needed, then click Deactivate Kill Switch to resume."),
        ("API key error / decryption error",
         "DB_SECRET_KEY in .env is wrong or missing. If you changed it after saving keys, stored credentials are unrecoverable — you must re-enter them. Always back up your .env."),
        ("Email not arriving",
         "Check spam folder. Make sure you used a Gmail App Password (not your regular password). SMTP: smtp.gmail.com, port 587."),
        ("Where is my data stored?",
         "All data lives in trading.db (SQLite) in the project folder. Backtest history, signals, settings, and encrypted credentials all live in this file. Never delete or overwrite it."),
        ("Can I run TradeBot 24/7?",
         "Yes — the server runs continuously. Stock strategies skip orders outside configured trading hours. Crypto strategies run 24/7 with no restriction. Use a VPS or run start.bat on a machine that stays on."),
    ]

    for q, a in faq:
        e += [KeepTogether([
            Paragraph(f"<b>Q: {q}</b>", Body),
            Paragraph(f"A: {a}", Body),
            Spacer(1, 0.06*inch),
        ])]

    e.append(Spacer(1, 0.3*inch))
    e.append(HR())
    e.append(Paragraph("Still stuck? Check the server console output for detailed error messages. The engine logs every skip, block, and error with a full reason.", Good))

    return e


if __name__ == "__main__":
    doc()
