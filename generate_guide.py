"""Generate TradeBot Setup Guide PDF."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle, HRFlowable, PageBreak)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

OUT = "TradeBot_Setup_Guide.pdf"

ACCENT  = colors.HexColor("#5b8def")
GREEN   = colors.HexColor("#16c784")
RED     = colors.HexColor("#ea3943")
DARK    = colors.HexColor("#0d1117")
PANEL   = colors.HexColor("#161b27")
MUTE    = colors.HexColor("#7f8aa3")
WHITE   = colors.white
YELLOW  = colors.HexColor("#f0b90b")

styles = getSampleStyleSheet()

def S(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], **kw)

Title     = S("Title",     fontSize=28, textColor=WHITE, spaceAfter=6, alignment=TA_CENTER, fontName="Helvetica-Bold")
SubTitle  = S("SubTitle",  fontSize=13, textColor=MUTE,  spaceAfter=20, alignment=TA_CENTER)
H1        = S("H1",        fontSize=18, textColor=ACCENT, spaceBefore=18, spaceAfter=8, fontName="Helvetica-Bold")
H2        = S("H2",        fontSize=13, textColor=WHITE,  spaceBefore=12, spaceAfter=6, fontName="Helvetica-Bold")
Body      = S("Body",      fontSize=10, textColor=colors.HexColor("#c8d6e8"), spaceAfter=6, leading=16)
Note      = S("Note",      fontSize=9,  textColor=YELLOW,  spaceAfter=6, leftIndent=12, leading=14)
Code      = S("Code",      fontSize=9,  fontName="Courier", textColor=GREEN, backColor=PANEL, spaceAfter=6, leftIndent=12, leading=14)
BulletSt  = S("Bullet",   fontSize=10, textColor=colors.HexColor("#c8d6e8"), spaceAfter=4, leftIndent=16, leading=15, bulletIndent=6)

def doc():
    d = SimpleDocTemplate(OUT, pagesize=letter,
                          leftMargin=0.85*inch, rightMargin=0.85*inch,
                          topMargin=0.85*inch, bottomMargin=0.85*inch)
    d.build(story(), onFirstPage=bg_page, onLaterPages=bg_page)
    print(f"[OK] Generated: {OUT}")

def bg_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
    # footer
    canvas.setFillColor(MUTE)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(letter[0]/2, 0.45*inch, f"TradeBot  |  Page {doc.page}")
    canvas.restoreState()

def HR():
    return HRFlowable(width="100%", thickness=1, color=colors.HexColor("#243049"), spaceAfter=10, spaceBefore=4)

def bullet(text):
    return Paragraph(f"<bullet>•</bullet> {text}", BulletSt)

def story():
    e = []

    # ── Cover ──────────────────────────────────────────────────────────────
    e += [Spacer(1, 1.2*inch),
          Paragraph("📈 TradeBot", Title),
          Paragraph("Complete Setup & User Guide", SubTitle),
          Spacer(1, 0.3*inch),
          HR()]

    box_data = [["Automated Stock Trading Bot",
                 "7 Built-in Strategies  |  Risk Controls  |  Live Dashboard"]]
    box = Table(box_data, colWidths=["100%"])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), PANEL),
        ("TEXTCOLOR",  (0,0),(0,0), WHITE),
        ("TEXTCOLOR",  (0,1),(0,1), MUTE),
        ("ALIGN",      (0,0),(-1,-1), "CENTER"),
        ("FONTNAME",   (0,0),(0,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0),(0,0), 13),
        ("FONTSIZE",   (0,1),(0,1), 10),
        ("TOPPADDING", (0,0),(-1,-1), 16),
        ("BOTTOMPADDING",(0,0),(-1,-1), 16),
        ("ROUNDEDCORNERS",[8]),
    ]))
    e += [box, PageBreak()]

    # ── Ch 1: What is TradeBot ────────────────────────────────────────────
    e += [Paragraph("Chapter 1 — What is TradeBot?", H1), HR(),
          Paragraph("TradeBot is an automated trading bot that connects to your brokerage account and places stock trades automatically, based on proven technical analysis strategies.", Body),
          Paragraph("It runs on your Windows PC and monitors the market every minute while it is open. You control everything from a web dashboard in your browser — no coding or command-line knowledge required.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("What it does:", H2),
          bullet("Scans the market for stocks matching your chosen strategy"),
          bullet("Places buy and sell orders automatically on your behalf"),
          bullet("Monitors your positions and P&amp;L in a live dashboard"),
          bullet("Sends you email or Telegram alerts when trades execute"),
          bullet("Protects your account with a daily loss limit and kill switch"),
          Spacer(1, 0.15*inch),
          Paragraph("⚠️ Important Disclaimer", H2),
          Paragraph("TradeBot is a tool — not financial advice. Past strategy performance does not guarantee future results. Always start with paper (practice) trading before using real money. Never risk money you cannot afford to lose.", Note),
          Paragraph("Paper trading vs. Live trading:", H2),
          Paragraph("<b>Paper trading</b> uses fake money in a simulated account. Your bot places real-looking trades but no actual money changes hands. This is the default and is recommended for all new users.", Body),
          Paragraph("<b>Live trading</b> uses real money in your brokerage account. Only switch to live after you are confident in how your strategies perform on paper.", Body),
          PageBreak()]

    # ── Ch 2: Installation ────────────────────────────────────────────────
    e += [Paragraph("Chapter 2 — Installation", H1), HR(),
          Paragraph("System Requirements", H2),
          bullet("Windows 10 or Windows 11 (64-bit)"),
          bullet("Internet connection"),
          bullet("At least 500 MB free disk space"),
          bullet("A free Alpaca Markets account (see Section 2.2)"),
          Spacer(1, 0.15*inch),
          Paragraph("Step 1 — Get a Free Alpaca Account", H2),
          Paragraph("Alpaca Markets is a commission-free brokerage with a free paper trading account. TradeBot uses their API to place trades.", Body),
          bullet("Go to <b>https://alpaca.markets</b>"),
          bullet("Click <b>Get Started</b> → sign up with your email"),
          bullet("No credit card required for paper trading"),
          bullet("After signing up, log into your dashboard"),
          Spacer(1, 0.15*inch),
          Paragraph("Step 2 — Get Your API Keys", H2),
          Paragraph("API keys let TradeBot securely connect to your Alpaca account.", Body),
          bullet("In Alpaca, click your name (top right) → <b>API Keys</b>"),
          bullet("Click <b>Regenerate</b> under Paper Trading"),
          bullet("Copy your <b>API Key ID</b> and <b>Secret Key</b> — save them safely"),
          Paragraph("⚠️ Your Secret Key is only shown once. Copy it now and store it somewhere safe.", Note),
          Spacer(1, 0.15*inch),
          Paragraph("Step 3 — Run the Installer", H2),
          Paragraph("TradeBot comes with a one-click installer that handles everything automatically.", Body),
          bullet("Open the TradeBot folder"),
          bullet("Double-click <b>setup.bat</b>"),
          bullet("Wait for it to finish (1–3 minutes on first run)"),
          bullet("Your browser will open automatically to the Setup Wizard"),
          Paragraph("If Windows shows a security warning, click 'More info' → 'Run anyway'.", Note),
          PageBreak()]

    # ── Ch 3: Setup Wizard ────────────────────────────────────────────────
    e += [Paragraph("Chapter 3 — Setup Wizard", H1), HR(),
          Paragraph("The Setup Wizard runs automatically on first launch. It walks you through connecting your broker and configuring your bot in 4 steps.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Step 1 — Connect Your Broker", H2),
          bullet("Paste your <b>API Key</b> and <b>API Secret</b> from Alpaca"),
          bullet("Select <b>Paper Trading</b> (recommended for beginners)"),
          bullet("Click <b>Test Connection</b> — you should see your account equity"),
          bullet("Click <b>Continue</b>"),
          Spacer(1, 0.1*inch),
          Paragraph("Step 2 — Risk Settings", H2),
          bullet("<b>Amount Per Trade</b>: How many dollars to invest per signal. $500 is a safe start."),
          bullet("<b>Daily Loss Limit</b>: The bot stops all trading if your account drops this % in one day. 2% recommended."),
          bullet("<b>Max Open Positions</b>: Maximum number of stocks the bot can hold at once."),
          Spacer(1, 0.1*inch),
          Paragraph("Step 3 — Choose Your First Strategy", H2),
          Paragraph("Pick one strategy to start with. You can enable more later.", Body),
          bullet("<b>Momentum Breakout</b> (Recommended) — finds trending stocks automatically"),
          bullet("<b>52-Week High Breakout</b> — buys stocks at new yearly highs with volume"),
          bullet("<b>MACD + Volume</b> — fewer but higher-confidence signals"),
          bullet("<b>Manual Only</b> — no auto-trading, just use the dashboard"),
          Spacer(1, 0.1*inch),
          Paragraph("Step 4 — Set Your Password", H2),
          Paragraph("Choose a password to protect your dashboard. Anyone on your network who knows your PC's IP address could access the bot without it.", Body),
          PageBreak()]

    # ── Ch 4: Dashboard ───────────────────────────────────────────────────
    e += [Paragraph("Chapter 4 — Using the Dashboard", H1), HR(),
          Paragraph("Open your browser and go to <b>http://localhost:8000</b> while TradeBot is running.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Account Cards (top row)", H2),
          bullet("<b>Equity</b> — total value of your account including open positions"),
          bullet("<b>Cash</b> — uninvested cash available to buy stocks"),
          bullet("<b>Day P&L</b> — profit or loss for today"),
          bullet("<b>Total P&L</b> — all-time profit or loss"),
          bullet("<b>Positions</b> — number of stocks currently held"),
          Spacer(1, 0.1*inch),
          Paragraph("Market Scanner", H2),
          Paragraph("Shows the most active stocks, top gainers, and top losers right now. Refreshes every 60 seconds during market hours.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Positions Table", H2),
          Paragraph("Lists every stock currently held, with live price, quantity, and unrealized P&L. Click <b>Close</b> to sell a position manually.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Bot Signals Log", H2),
          Paragraph("Every action the bot takes — buys, sells, and blocked orders — is logged here with the reason and timestamp.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Manual Order Panel", H2),
          bullet("Type a ticker (e.g. AAPL) and click <b>Get Quote</b> to see the current price"),
          bullet("Choose <b>Shares</b> or <b>USD Amount</b> mode"),
          bullet("Click <b>Buy</b> or <b>Sell</b> to place an order immediately"),
          PageBreak()]

    # ── Ch 5: Strategies ─────────────────────────────────────────────────
    e += [Paragraph("Chapter 5 — Strategies Explained", H1), HR(),
          Paragraph("Each strategy has a toggle to enable/disable it, and a Configure Parameters section to customize how it behaves.", Body),
          Spacer(1, 0.1*inch)]

    strat_rows = [
        ["Strategy", "Best For", "Approx. Historical Return*"],
        ["SMA Crossover",         "Trending markets",    "7–9% CAGR"],
        ["RSI Mean Reversion",    "Sideways markets",    "6–9% CAGR"],
        ["Momentum Breakout",     "Rising markets",      "10–14% CAGR"],
        ["Bollinger Band",        "Choppy/range markets","9–12% CAGR"],
        ["52-Week High Breakout", "Trending markets",    "12–16% CAGR"],
        ["MACD + Volume",         "Trending markets",    "10–13% CAGR"],
        ["Golden Cross (50/200)", "Long-term holds",     "7–10% CAGR"],
    ]
    t = Table(strat_rows, colWidths=[2.2*inch, 2*inch, 2.1*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0),  ACCENT),
        ("TEXTCOLOR",    (0,0), (-1,0),  WHITE),
        ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 9),
        ("BACKGROUND",   (0,1), (-1,-1), PANEL),
        ("TEXTCOLOR",    (0,1), (-1,-1), colors.HexColor("#c8d6e8")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [PANEL, colors.HexColor("#1a2233")]),
        ("ALIGN",        (0,0), (-1,-1), "LEFT"),
        ("PADDING",      (0,0), (-1,-1), 8),
        ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#243049")),
    ]))
    e += [t,
          Spacer(1, 0.1*inch),
          Paragraph("* Historical returns are estimates from backtesting. Not a guarantee of future performance.", Note),
          Spacer(1, 0.15*inch),
          Paragraph("Key Parameters (same across all strategies):", H2),
          bullet("<b>notional</b> — Dollar amount per trade (e.g. 500 = buy $500 worth per signal)"),
          bullet("<b>symbols</b> — Which stocks to watch (leave empty when using Auto-discover)"),
          bullet("<b>use_scanner</b> — Let the bot find stocks automatically from the market"),
          bullet("<b>max_positions</b> — Maximum positions open at once for this strategy"),
          PageBreak()]

    # ── Ch 6: Risk Controls ───────────────────────────────────────────────
    e += [Paragraph("Chapter 6 — Risk Controls", H1), HR(),
          Paragraph("Risk controls protect your account from large losses. They are always active and cannot be bypassed by strategies.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("🛑 Kill Switch", H2),
          Paragraph("The red Kill Switch button immediately halts ALL automated trading. The bot will not place any new orders until you press it again to resume.", Body),
          Paragraph("The kill switch also activates automatically if your daily loss limit is hit.", Note),
          Spacer(1, 0.1*inch),
          Paragraph("Daily Loss Limit", H2),
          Paragraph("If your account loses more than this percentage in a single day, the kill switch activates automatically and all trading stops. Default: 2%.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("PDT Rule (Pattern Day Trader)", H2),
          Paragraph("US regulations limit accounts under $25,000 to 3 'day trades' per 5 business days. TradeBot tracks your day trade count and blocks buy orders if you are at the limit.", Body),
          Paragraph("A day trade = buying and selling the same stock in the same day. Accounts over $25,000 equity are exempt.", Note),
          Spacer(1, 0.1*inch),
          Paragraph("Position Sizing", H2),
          bullet("<b>Fixed (qty)</b> — Always trades the exact share count or dollar amount you set in strategy params"),
          bullet("<b>% of Portfolio</b> — Calculates the trade size as a percentage of your total account value"),
          Paragraph("Position size mode is in Risk Controls → Position Size Mode.", Body),
          PageBreak()]

    # ── Ch 7: Notifications ───────────────────────────────────────────────
    e += [Paragraph("Chapter 7 — Notifications", H1), HR(),
          Paragraph("TradeBot can send you instant alerts via email or Telegram whenever a trade executes, a trade is blocked, or at end of day.", Body),
          Spacer(1, 0.1*inch),
          Paragraph("Setting up Email Alerts (Gmail)", H2),
          bullet("In the dashboard, click the 🔔 bell icon (top right)"),
          bullet("Enable <b>Email Alerts</b>"),
          bullet("Enter your Gmail address in <b>Send alerts to</b>"),
          bullet("SMTP: <b>smtp.gmail.com</b>  |  Port: <b>587</b>"),
          bullet("Email login: your Gmail address"),
          bullet("App password: create one at <b>myaccount.google.com → Security → App Passwords</b>"),
          bullet("Click <b>Send test email</b> to verify, then <b>Save Settings</b>"),
          Paragraph("You must use an App Password, not your regular Gmail password.", Note),
          Spacer(1, 0.15*inch),
          Paragraph("Setting up Telegram Alerts", H2),
          bullet("Open Telegram and search for <b>@BotFather</b>"),
          bullet("Send /newbot, follow the steps — copy the <b>Bot Token</b>"),
          bullet("Search for <b>@userinfobot</b> to get your <b>Chat ID</b>"),
          bullet("Paste both into TradeBot's notification settings and test"),
          PageBreak()]

    # ── Ch 8: Going Live ──────────────────────────────────────────────────
    e += [Paragraph("Chapter 8 — Going Live (Real Money)", H1), HR(),
          Paragraph("⚠️ Only switch to live trading after you are satisfied with how your strategies perform on paper over at least 2–4 weeks.", Note),
          Spacer(1, 0.1*inch),
          Paragraph("Pre-Live Checklist", H2),
          bullet("✅ Ran paper trading for at least 2 weeks"),
          bullet("✅ Understand which strategies are enabled and why"),
          bullet("✅ Daily loss limit is set to a comfortable level"),
          bullet("✅ Position sizes are appropriate for your account size"),
          bullet("✅ Notifications are configured so you are alerted on every trade"),
          bullet("✅ Kill switch is accessible from your phone/tablet"),
          Spacer(1, 0.15*inch),
          Paragraph("To switch to live trading:", H2),
          Paragraph("Re-run setup.bat and go through the Setup Wizard again, selecting <b>Live Trading</b> and entering your Alpaca live account API keys.", Body),
          Paragraph("Your live Alpaca account requires identity verification and a linked bank account. Go to https://alpaca.markets to complete this.", Body),
          PageBreak()]

    # ── Ch 9: Troubleshooting ────────────────────────────────────────────
    e += [Paragraph("Chapter 9 — Troubleshooting", H1), HR()]

    faq = [
        ("Bot is running but no trades are being placed",
         "Check: (1) At least one strategy is enabled (toggle is green). (2) Market is open — bot only trades Mon–Fri 9:30am–4pm EST. (3) Kill switch is OFF. (4) Click 'Run now' to force a tick and see the bot signals log."),
        ("Strategies show 0 signals",
         "This is normal. Strategies only trigger when their conditions are met. SMA Crossover and Golden Cross may go days without a signal. Try enabling Momentum Breakout which scans more stocks."),
        ("'Connection refused' when opening the dashboard",
         "The bot server is not running. Double-click start.bat and wait for the terminal to say 'Application startup complete', then refresh the browser."),
        ("Trade was BLOCKED — PDT limit",
         "Your account is under $25,000 and you have used 3 day trades this week. The block lifts automatically after 5 business days, or fund your account above $25,000 to become PDT-exempt."),
        ("Trade was BLOCKED — daily loss limit",
         "Your account lost more than your configured limit today. The kill switch has been automatically activated. Review your positions, then click 'Resume Trading' in the Risk Controls panel."),
        ("API key error on startup",
         "Your API keys in .env may have expired or been regenerated. Re-run setup.bat to enter your new keys."),
        ("Email notifications not arriving",
         "Check your spam folder. Make sure you are using an App Password (not your Gmail password). Verify SMTP is smtp.gmail.com and port is 587."),
    ]

    for q, a in faq:
        e += [Paragraph(f"<b>Q: {q}</b>", Body),
              Paragraph(f"A: {a}", Body),
              Spacer(1, 0.05*inch)]

    return e


if __name__ == "__main__":
    doc()
