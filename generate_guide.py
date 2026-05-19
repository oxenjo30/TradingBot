"""Generate TradeBot User Guide PDF.
Covers all 14 strategies and all current features.
Run:  python generate_guide.py
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── Page geometry ──────────────────────────────────────────────────────────────
PW, PH = letter          # 612 x 792 pt
ML = MR = 0.75 * inch   # left / right margin
MT = 0.9 * inch          # top margin (below accent stripe)
MB = 0.65 * inch         # bottom margin (above footer)
CW = PW - ML - MR        # usable content width  ≈ 468 pt

# ── TradeBot colour palette ───────────────────────────────────────────────────
BG      = colors.HexColor("#080D14")   # page background
CARD    = colors.HexColor("#0F172A")   # card / table row dark
CARD2   = colors.HexColor("#141E2E")   # alternating row
BORDER  = colors.HexColor("#1E2D45")   # dividers / grid lines
BLUE    = colors.HexColor("#3B82F6")   # primary accent
PURPLE  = colors.HexColor("#8B5CF6")   # secondary accent
GREEN   = colors.HexColor("#10B981")
YELLOW  = colors.HexColor("#F59E0B")
RED     = colors.HexColor("#EF4444")
TEXT    = colors.HexColor("#E6EBF5")   # body text
MUTED   = colors.HexColor("#94A3B8")   # sub-text / labels
WHITE   = colors.white

# ── Style helpers ─────────────────────────────────────────────────────────────
def ps(name, **kw):
    base = kw.pop("parent", None)
    defaults = dict(fontName="Helvetica", fontSize=10,
                    textColor=TEXT, leading=16, spaceAfter=0, spaceBefore=0)
    defaults.update(kw)
    return ParagraphStyle(name, parent=base, **defaults)

# Named styles
S_TITLE   = ps("title",   fontName="Helvetica-Bold", fontSize=28,
                textColor=WHITE, alignment=TA_CENTER, leading=34)
S_COVER_S = ps("covers",  fontName="Helvetica",      fontSize=11,
                textColor=MUTED, alignment=TA_CENTER, leading=16)
S_CHAP    = ps("chap",    fontName="Helvetica-Bold", fontSize=9,
                textColor=BLUE, leading=12, spaceAfter=2)
S_H1      = ps("h1",      fontName="Helvetica-Bold", fontSize=20,
                textColor=BLUE, leading=26, spaceBefore=4, spaceAfter=6)
S_H2      = ps("h2",      fontName="Helvetica-Bold", fontSize=13,
                textColor=TEXT, leading=18, spaceBefore=10, spaceAfter=4)
S_H3      = ps("h3",      fontName="Helvetica-Bold", fontSize=10,
                textColor=MUTED, leading=14, spaceBefore=6, spaceAfter=3)
S_BODY    = ps("body",    fontSize=10, textColor=TEXT, leading=16, spaceAfter=5)
S_MUTED   = ps("muted",   fontSize=10, textColor=MUTED, leading=15, spaceAfter=4)
S_NOTE    = ps("note",    fontSize=9,  textColor=YELLOW, leading=14)
S_DANGER  = ps("danger",  fontSize=9,  textColor=RED,    leading=14)
S_GOOD    = ps("good",    fontSize=9,  textColor=GREEN,  leading=14)
S_TIP     = ps("tip",     fontSize=9,  textColor=colors.HexColor("#93C5FD"), leading=14)
S_CODE    = ps("code",    fontName="Courier", fontSize=9,
                textColor=colors.HexColor("#93C5FD"), leading=14)
S_TH      = ps("th",      fontName="Helvetica-Bold", fontSize=9,
                textColor=WHITE, leading=13)
S_TD      = ps("td",      fontSize=9,  textColor=TEXT, leading=13)
S_TDB     = ps("tdb",     fontName="Helvetica-Bold", fontSize=9,
                textColor=TEXT, leading=13)
S_STEP_N  = ps("stepn",   fontName="Helvetica-Bold", fontSize=11,
                textColor=BLUE, alignment=TA_CENTER, leading=14)
S_STEP_T  = ps("stept",   fontName="Helvetica-Bold", fontSize=10,
                textColor=TEXT, leading=14)
S_STEP_D  = ps("stepd",   fontSize=9, textColor=MUTED, leading=13)
S_TOC     = ps("toc",     fontSize=10, textColor=MUTED, leading=16)
S_TOC_B   = ps("tocb",    fontName="Helvetica-Bold", fontSize=10,
                textColor=TEXT, leading=16)
S_FOOT    = ps("foot",    fontSize=8, textColor=MUTED, leading=10)
S_BULL    = ps("bull",    fontSize=10, textColor=TEXT, leading=16,
                leftIndent=14, spaceAfter=3)

def HR():
    return HRFlowable(width="100%", thickness=1, color=BORDER,
                      spaceAfter=8, spaceBefore=2)

def SP(h=0.1):
    return Spacer(1, h * inch)

def bullet(txt):
    return Paragraph(f"• &nbsp;{txt}", S_BULL)

# ── Callout boxes ─────────────────────────────────────────────────────────────
_CALLOUT = {
    "tip":    (colors.HexColor("#0C1A2E"), colors.HexColor("#1E3A5F"),
               BLUE,   "INFO"),
    "note":   (colors.HexColor("#1C1A00"), colors.HexColor("#3D3600"),
               YELLOW, "NOTE"),
    "danger": (colors.HexColor("#1C0000"), colors.HexColor("#3D0000"),
               RED,    "WARNING"),
    "good":   (colors.HexColor("#001C0E"), colors.HexColor("#003D1C"),
               GREEN,  "TIP"),
}

def callout(text, kind="note"):
    bg, border_c, txt_c, label = _CALLOUT.get(kind, _CALLOUT["note"])
    label_st = ps(f"cl_{kind}", fontName="Helvetica-Bold", fontSize=8,
                  textColor=txt_c, leading=11)
    body_st  = ps(f"cb_{kind}", fontSize=9, textColor=txt_c, leading=14)
    t = Table(
        [[Paragraph(label, label_st), Paragraph(text, body_st)]],
        colWidths=[0.55 * inch, CW - 0.55 * inch - 20],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("LINEABOVE",     (0, 0), (-1, 0),  1.5, border_c),
        ("LINEBELOW",     (0, 0), (-1, -1), 1.5, border_c),
        ("LINEBEFORE",    (0, 0), (0, -1),  1.5, border_c),
        ("LINEAFTER",     (-1, 0), (-1, -1), 1.5, border_c),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return KeepTogether([SP(0.08), t, SP(0.1)])

# ── Steps table ───────────────────────────────────────────────────────────────
def steps(rows):
    """rows = list of (title, description) tuples."""
    num_w  = 0.32 * inch
    body_w = CW - num_w
    data = []
    for i, (title, desc) in enumerate(rows):
        cell = [Paragraph(title, S_STEP_T)]
        if desc:
            cell.append(Paragraph(desc, S_STEP_D))
        data.append([Paragraph(str(i + 1), S_STEP_N), cell])

    t = Table(data, colWidths=[num_w, body_w])
    n = len(data)
    style = [
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (0, -1),  0),
        ("LEFTPADDING",   (1, 0), (1, -1),  8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("BACKGROUND",    (0, 0), (-1, -1), CARD),
        ("LINEABOVE",     (0, 0), (-1, 0),  0.5, BORDER),
        ("LINEBELOW",     (0, n-1), (-1, n-1), 0.5, BORDER),
    ]
    for r in range(n - 1):
        style.append(("LINEBELOW", (0, r), (-1, r), 0.5, BORDER))
    t.setStyle(TableStyle(style))
    return KeepTogether([SP(0.08), t, SP(0.1)])

# ── Data tables ───────────────────────────────────────────────────────────────
def dtable(headers, rows, col_widths, bold_first=True):
    """Render a styled header + data table."""
    head_cells = [Paragraph(h, S_TH) for h in headers]
    body_rows  = []
    for row in rows:
        st0 = S_TDB if bold_first else S_TD
        body_rows.append(
            [Paragraph(str(c), st0 if ci == 0 else S_TD) for ci, c in enumerate(row)]
        )

    data = [head_cells] + body_rows
    n    = len(data)
    t    = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        # Header row
        ("BACKGROUND",    (0, 0),  (-1, 0),  BLUE),
        ("TOPPADDING",    (0, 0),  (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 6),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 8),
        ("VALIGN",        (0, 0),  (-1, -1), "TOP"),
        ("GRID",          (0, 0),  (-1, -1), 0.5, BORDER),
        ("LINEABOVE",     (0, 0),  (-1, 0),  0, BORDER),
    ]
    for r in range(1, n):
        bg = CARD if r % 2 == 1 else CARD2
        style.append(("BACKGROUND", (0, r), (-1, r), bg))

    t.setStyle(TableStyle(style))
    return KeepTogether([SP(0.06), t, SP(0.12)])

# ── Page canvas (background + header stripe + footer) ─────────────────────────
def _page_canvas(canvas, doc):
    canvas.saveState()
    W, H = letter

    # Dark background
    canvas.setFillColor(BG)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)

    # Top accent gradient (simulate with two rects)
    canvas.setFillColor(BLUE)
    canvas.rect(0, H - 3, W * 0.6, 3, fill=1, stroke=0)
    canvas.setFillColor(PURPLE)
    canvas.rect(W * 0.4, H - 3, W * 0.6, 3, fill=1, stroke=0)

    # Footer bar
    canvas.setFillColor(CARD)
    canvas.rect(0, 0, W, MB - 0.1 * inch, fill=1, stroke=0)
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(0, MB - 0.1 * inch, W, MB - 0.1 * inch)

    # Footer text
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(ML, 0.22 * inch, "TradeBot — Complete User Guide")
    canvas.setFillColor(BLUE)
    canvas.drawRightString(W - MR, 0.22 * inch, f"Page {doc.page}")

    canvas.restoreState()

# ── Cover page canvas (no footer page number) ─────────────────────────────────
def _cover_canvas(canvas, doc):
    canvas.saveState()
    W, H = letter

    # Full dark background
    canvas.setFillColor(BG)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)

    # Top gradient stripe — thicker on cover
    canvas.setFillColor(BLUE)
    canvas.rect(0, H - 5, W * 0.55, 5, fill=1, stroke=0)
    canvas.setFillColor(PURPLE)
    canvas.rect(W * 0.45, H - 5, W * 0.55, 5, fill=1, stroke=0)

    # Bottom bar
    canvas.setFillColor(CARD)
    canvas.rect(0, 0, W, 0.5 * inch, fill=1, stroke=0)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(W / 2, 0.18 * inch,
                             "Confidential — For authorized use only")

    canvas.restoreState()


# ── Document ──────────────────────────────────────────────────────────────────
def build():
    out = "TradeBot_Installation_Guide.pdf"
    doc = SimpleDocTemplate(
        out,
        pagesize=letter,
        leftMargin=ML, rightMargin=MR,
        topMargin=MT,  bottomMargin=MB,
    )
    doc.build(
        _story(),
        onFirstPage=_cover_canvas,
        onLaterPages=_page_canvas,
    )
    print(f"[OK] {out}")


# ── Story ─────────────────────────────────────────────────────────────────────
def _story():
    e = []

    # ─────────────────────────────────────────────────────────────────────────
    # COVER
    # ─────────────────────────────────────────────────────────────────────────
    e += [
        SP(1.2),
        Paragraph("TradeBot", S_TITLE),
        SP(0.1),
        Paragraph("Complete User Guide", S_COVER_S),
        SP(0.35),
        HRFlowable(width="100%", thickness=1.5,
                   color=BORDER, spaceAfter=20, spaceBefore=0),
        SP(0.1),
    ]

    # Feature summary cards on cover
    features = [
        ["14 Built-in\nStrategies",   "9 stock + 4 crypto\n+ EMA + Patterns"],
        ["10-Layer\nRisk Engine",      "Kill switch, loss limits\nPDT, exposure caps"],
        ["Stocks &\nCrypto 24/7",     "Alpaca, Tradier,\nBinance spot"],
        ["AI-Powered",                 "Explanations + weekly\nauto-tuner"],
        ["Backtesting\nStudio",        "Historical simulation\n+ drift monitor"],
        ["Webhooks &\nAlerts",         "TradingView signals\nSlack/Discord/Telegram"],
    ]
    cw = CW / 3 - 4
    ft_data = [[
        _feat_cell(f[0], f[1]) for f in features[:3]
    ], [
        _feat_cell(f[0], f[1]) for f in features[3:]
    ]]
    ft = Table(ft_data, colWidths=[cw, cw, cw], rowHeights=[0.9 * inch, 0.9 * inch])
    ft.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 2),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 2),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    e += [ft, SP(0.4)]

    e += [
        HRFlowable(width="100%", thickness=1, color=BORDER,
                   spaceAfter=12, spaceBefore=0),
        Paragraph(
            "Automated algorithmic trading · 60-second engine tick · "
            "Multi-layer risk controls · All from one dashboard",
            S_COVER_S,
        ),
        PageBreak(),
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # TABLE OF CONTENTS
    # ─────────────────────────────────────────────────────────────────────────
    e += [
        Paragraph("Table of Contents", S_H1),
        HR(),
        SP(0.05),
    ]
    toc = [
        ("1",  "What is TradeBot?",                         True),
        ("2",  "Installation & First-time Setup",           True),
        ("3",  "Broker Accounts",                           True),
        ("4",  "Strategies & Bots",                         True),
        ("",   "  4.1  Stock Strategies (9 total)",         False),
        ("",   "  4.2  Crypto Strategies (4 total)",        False),
        ("5",  "Crypto Trading with Binance",               True),
        ("6",  "Manual Orders",                             True),
        ("7",  "Risk Controls",                             True),
        ("8",  "Kill Switch",                               True),
        ("9",  "Take-Profit",                               True),
        ("10", "Price Alerts",                              True),
        ("11", "Performance Analytics",                     True),
        ("12", "Strategy Health & Drift Monitor",           True),
        ("13", "Backtesting Studio",                        True),
        ("14", "AI Tuning & Trade Explanations",            True),
        ("15", "Webhook Signals",                           True),
        ("16", "Notifications",                             True),
        ("17", "Going Live with Real Money",                True),
        ("18", "VPS Deployment",                            True),
        ("19", "Troubleshooting & FAQ",                     True),
    ]
    for num, title, bold in toc:
        st = S_TOC_B if bold else S_TOC
        e.append(Paragraph(
            f'<font color="#3B82F6"><b>{num}</b></font>&nbsp;&nbsp;&nbsp;{title}'
            if num else title,
            st,
        ))
    e.append(PageBreak())

    # ─────────────────────────────────────────────────────────────────────────
    # CHAPTERS
    # ─────────────────────────────────────────────────────────────────────────

    # Ch 1 ────────────────────────────────────────────────────────────────────
    e += chapter(1, "What is TradeBot?") + [
        p("TradeBot is an automated algorithmic trading platform that connects "
          "to your broker accounts, runs 14 built-in strategies on a 60-second "
          "engine tick, enforces multi-layer risk controls, explains every trade "
          "with AI, and supports both stocks and crypto — all from one web "
          "dashboard."),
        p("It runs continuously on your PC or a VPS. No coding required."),
        SP(0.05),
        h2("Key Principles"),
        bullet("<b>Paper-first</b> — defaults to paper trading. No real money at risk until "
               "you explicitly add a live account."),
        bullet("<b>Transparent</b> — every signal, block, and order is logged with a full reason."),
        bullet("<b>Risk-first</b> — 10 configurable guards run before every order."),
        bullet("<b>AI-assisted</b> — every trade gets a plain-English explanation and "
               "weekly parameter tuning."),
        SP(0.1),
        callout("TradeBot is a tool, not financial advice. Past strategy performance "
                "does not guarantee future results. Always start with paper trading.",
                "danger"),
        PageBreak(),
    ]

    # Ch 2 ────────────────────────────────────────────────────────────────────
    e += chapter(2, "Installation & First-time Setup") + [
        h2("System Requirements"),
        bullet("Windows 10/11 64-bit  <b>or</b>  Ubuntu 22.04/24.04 LTS (VPS)"),
        bullet("Python 3.11 or newer"),
        bullet("Internet connection  ·  500 MB free disk space"),
        SP(0.1),
        h2("Windows — Quick Start"),
        steps([
            ("Run setup.bat",
             "Double-click setup.bat. Installs Python if missing, creates a venv, "
             "and installs all pip dependencies."),
            ("Configure .env",
             "Create a .env file in the project folder. Set DB_SECRET_KEY — generate "
             "with:  python -c \"from cryptography.fernet import Fernet; "
             "print(Fernet.generate_key().decode())\"  — back this up securely."),
            ("Start the server",
             "Double-click start.bat or run: uvicorn server.main:app --port 8000. "
             "Dashboard opens at http://localhost:8000"),
            ("Set your password",
             "On first launch you are prompted to create a dashboard password."),
            ("Add a broker account",
             "Broker Accounts → Add Account → pick broker → enter API keys → Test."),
            ("Enable a strategy",
             "Bots & Strategies → select account → toggle a strategy on."),
        ]),
        callout("Keep your .env file private. It contains your AES-256 encryption key. "
                "Never commit it to version control.", "danger"),
        PageBreak(),
    ]

    # Ch 3 ────────────────────────────────────────────────────────────────────
    e += chapter(3, "Broker Accounts") + [
        p("TradeBot supports multiple broker accounts simultaneously. Each has its own "
          "Paper/Live type, credentials, and strategy assignments — managed independently."),
        h2("Supported Brokers"),
        dtable(
            ["Broker", "Asset Class", "Paper Trading"],
            [
                ["Alpaca",  "US Stocks & ETFs",         "Separate paper API keys (start with PK)"],
                ["Tradier", "US Stocks & Options",      "Sandbox API at sandbox.tradier.com"],
                ["Binance", "Crypto Spot (USDT pairs)", "Demo keys from demo.binance.com"],
            ],
            [0.85*inch, 1.7*inch, CW - 0.85*inch - 1.7*inch],
        ),
        h2("Adding an Account"),
        steps([
            ("Click Add Account",
             "Broker Accounts page → Add Account → choose broker from the "
             "tabbed picker (Stocks, Crypto, Forex, Futures)."),
            ("Select Paper or Live",
             "Each account is independently Paper or Live. Binance paper requires "
             "demo keys from demo.binance.com — separate from live keys."),
            ("Enter API credentials",
             "Paste your API Key and Secret. Encrypted with AES-256 immediately. "
             "The secret is never stored in plaintext."),
            ("Test connectivity",
             "Click Test on the account card. Green tick = credentials valid."),
            ("Assign strategies",
             "Go to Bots & Strategies to link strategies to this account."),
        ]),
        callout("If you lose DB_SECRET_KEY from .env, stored broker credentials cannot "
                "be decrypted. Back up .env securely.", "danger"),
        PageBreak(),
    ]

    # Ch 4 ────────────────────────────────────────────────────────────────────
    e += chapter(4, "Strategies & Bots") + [
        p("TradeBot ships with 14 automated strategies. The engine evaluates all "
          "enabled strategies every 60 seconds. Stock strategies only run during US "
          "market hours; crypto strategies run 24/7."),
        h2("4.1  Stock Strategies (9 total)"),
        dtable(
            ["Strategy", "Signal Logic", "Best For"],
            [
                ["Momentum",
                 "Top actives + price above 20-day SMA + RSI 40–70",
                 "Trending markets"],
                ["RSI Mean Reversion",
                 "Buy RSI < 30; exit RSI > 50",
                 "Range-bound stocks"],
                ["MACD + Volume",
                 "Bullish MACD crossover + above-average volume",
                 "Momentum with confirmation"],
                ["Bollinger Bands",
                 "Buy lower band + oversold RSI; exit middle band",
                 "Low-volatility stocks"],
                ["Golden Cross",
                 "50-day SMA crosses above 200-day SMA",
                 "Long-term trend following"],
                ["SMA Crossover",
                 "Fast SMA crosses above slow SMA (configurable periods)",
                 "Short-term trend detection"],
                ["52-Week Breakout",
                 "Price closes above 52-week high on strong volume",
                 "Breakout & momentum"],
                ["EMA Confluence",
                 "8/21/50/200 EMAs all aligned; scaled sizing by count",
                 "High-conviction entries"],
                ["Classic Patterns",
                 "Candlestick & continuation patterns; EMA-200 trend filter",
                 "Pattern-based swing trades"],
            ],
            [1.15*inch, 2.35*inch, CW - 1.15*inch - 2.35*inch],
        ),
        h2("4.2  Crypto Strategies (4 total)"),
        dtable(
            ["Strategy", "Signal Logic"],
            [
                ["Crypto Trend",
                 "EMA crossover (fast vs. slow). Buy bullish, sell bearish."],
                ["Crypto RSI Bounce",
                 "Buy RSI < oversold threshold; sell RSI > overbought threshold."],
                ["Crypto Volatility Breakout",
                 "Buy lower Bollinger Band + oversold RSI; exit at SMA (middle band)."],
                ["Crypto Grid",
                 "Divides price range into bands. Buys near band bottoms, sells near "
                 "tops. Auto-detects range from recent history. Trend SMA filter "
                 "prevents entries in downtrends."],
            ],
            [1.5*inch, CW - 1.5*inch],
        ),
        h2("Enabling a Strategy"),
        steps([
            ("Open Bots & Strategies",
             "Select a broker account on the left. Compatible strategies appear on the right."),
            ("Toggle on",
             "Flip the toggle. Picked up on the next 60-second tick."),
            ("Adjust parameters",
             "Expand a strategy to edit notional size, indicator periods, symbol lists. "
             "Changes take effect immediately."),
        ]),
        callout("Stock strategies only run during US market hours (9:30 AM – 4:00 PM ET). "
                "Crypto runs 24/7.", "tip"),
        PageBreak(),
    ]

    # Ch 5 ────────────────────────────────────────────────────────────────────
    e += chapter(5, "Crypto Trading with Binance") + [
        p("TradeBot connects to Binance for 24/7 spot trading. All pairs trade against "
          "USDT (e.g., BTC/USDT, ETH/USDT). Paper and live accounts use completely "
          "separate API keys."),
        h2("Getting Binance API Keys"),
        steps([
            ("Paper Trading — Binance Demo",
             "Go to demo.binance.com, create an account, and generate API keys under "
             "API Management. Demo keys only work with the demo exchange."),
            ("Live Trading — Binance.com",
             "Go to binance.com → API Management. Enable Spot & Margin Trading. "
             "Disable withdrawals for safety."),
            ("Add in TradeBot",
             "Broker Accounts → Add Account → Crypto tab → Binance → select "
             "Paper or Live → paste keys → Test."),
        ]),
        callout("Demo keys and live keys are completely separate. Using a live key on "
                "a Paper account (or vice versa) will cause an authentication error.", "danger"),
        h2("Common Binance Issues"),
        bullet("<b>DB_SECRET_KEY missing</b> — Without it the app cannot decrypt stored "
               "API keys and Binance ticks fail silently. Check your .env file."),
        bullet("<b>Key mismatch</b> — Paper accounts need keys from demo.binance.com; "
               "live accounts need keys from binance.com."),
        bullet("<b>Insufficient balance</b> — Minimum order is ~$10 USDT. Orders below "
               "this are skipped with a log entry."),
        bullet("<b>Neutral zone</b> — Crypto Grid only signals near band tops/bottoms. "
               "Price in the middle of a band = no signal. This is correct behaviour."),
        PageBreak(),
    ]

    # Ch 6 ────────────────────────────────────────────────────────────────────
    e += chapter(6, "Manual Orders") + [
        p("Place trades directly from the Positions & Orders page without waiting for a "
          "strategy signal."),
        steps([
            ("Select an account",
             "Use the account dropdown inside the order ticket."),
            ("Choose Buy or Sell",
             "Enter a ticker (e.g., AAPL or BTC/USDT) and click Quote for the live price."),
            ("Set amount",
             "Switch between Shares and Dollars mode, enter your amount, "
             "then click Place Order."),
        ]),
        callout("Manual orders bypass the strategy engine and all risk guards. "
                "They execute immediately as market orders.", "danger"),
        PageBreak(),
    ]

    # Ch 7 ────────────────────────────────────────────────────────────────────
    e += chapter(7, "Risk Controls") + [
        p("Every signal — from strategies or webhooks — passes through 10 configurable "
          "risk guards before an order is placed. The first failing guard blocks the "
          "trade and logs the reason."),
        dtable(
            ["Guard", "What It Does"],
            [
                ["Kill Switch",        "Master emergency stop. All automated trading halts instantly."],
                ["Daily Loss Limit",   "Halts trading when today's P&L drops below N% of starting equity."],
                ["Weekly Loss Limit",  "Same as daily but over a rolling 7-day window."],
                ["Consecutive Losses", "Blocks new trades after N losses in a row."],
                ["PDT Protection",     "Prevents a 4th day-trade in a 5-day rolling window "
                                       "(accounts under $25K, stocks only)."],
                ["Max Positions",      "Caps total open positions — separate limits for stocks and crypto."],
                ["Symbol Exposure",    "Prevents allocating more than N% of portfolio to one symbol."],
                ["Max Orders/Day",     "Limits total orders submitted in one trading day."],
                ["Trading Hours",      "Only allows orders between configured start/end times ET. "
                                       "Crypto strategies are exempt."],
                ["No-Trade List",      "Blacklisted symbols are never traded regardless of signals."],
            ],
            [1.35*inch, CW - 1.35*inch],
        ),
        callout("Recommended starting settings: max daily loss 2%, max positions 5, "
                "trading hours 9:30–15:45 ET, PDT protection on.", "good"),
        PageBreak(),
    ]

    # Ch 8 ────────────────────────────────────────────────────────────────────
    e += chapter(8, "Kill Switch") + [
        p("The kill switch is your emergency stop. One click halts all automated trading "
          "instantly. Manual orders still work."),
        h2("Global vs. Per-Account"),
        p("The <b>global kill switch</b> on the Risk page stops all accounts at once. "
          "Each broker account card also has its own <b>per-account kill switch</b> — "
          "useful when you want to pause one account while others continue trading."),
        h2("How to Activate"),
        p("Risk page → red <b>Activate Kill Switch</b> button. A red banner appears "
          "across all pages. Click <b>Deactivate</b> to resume."),
        callout("The kill switch does NOT close existing positions. It only stops new "
                "orders. To close all positions, use the close-all button on the "
                "Positions page.", "tip"),
        PageBreak(),
    ]

    # Ch 9 ────────────────────────────────────────────────────────────────────
    e += chapter(9, "Take-Profit") + [
        p("Automatically close positions when they reach a target gain percentage, "
          "without needing a sell signal from the strategy."),
        h2("How It Works"),
        p("After every 60-second engine tick, TradeBot scans all open positions. Any "
          "position whose unrealized gain meets or exceeds the take-profit threshold "
          "triggers an immediate market sell. Stock and crypto accounts each have their "
          "own configurable take-profit percentage."),
        h2("Configuration"),
        p("Go to <b>Risk</b> → Take-Profit section. Set <b>Stock Take-Profit %</b> and "
          "<b>Crypto Take-Profit %</b> separately. Set to 0 to disable."),
        callout("Take-profit exits run even when the engine kill switch is active — "
                "they're designed to lock in gains regardless.", "tip"),
        PageBreak(),
    ]

    # Ch 10 ───────────────────────────────────────────────────────────────────
    e += chapter(10, "Price Alerts") + [
        p("Set price thresholds on any symbol. When price crosses your target, "
          "you receive an instant notification via all configured channels."),
        steps([
            ("Go to Settings → Price Alerts",
             "Enter a symbol, choose Above or Below, and set your target price."),
            ("Save the alert",
             "Active alerts are checked every 60-second engine tick."),
            ("Get notified",
             "When triggered, alerts fire to all configured channels "
             "(Slack, Discord, Telegram, email). The alert is marked triggered "
             "and won't re-fire."),
        ]),
        PageBreak(),
    ]

    # Ch 11 ───────────────────────────────────────────────────────────────────
    e += chapter(11, "Performance Analytics") + [
        p("Track trading history, per-strategy stats, per-account P&L, and equity "
          "curve over time."),
        dtable(
            ["Widget", "Description"],
            [
                ["Equity Curve",          "Portfolio value over time — 1W, 1M, 3M, 1Y views."],
                ["Strategy Stats",        "Per-strategy: signals, fills, blocks, win rate, Sharpe ratio."],
                ["Attribution by Account","Breakdown of signals and fills per strategy × account."],
                ["Top Symbols",           "Most-traded symbols by signal count and fill rate."],
                ["Daily Activity",        "Bar chart of signals per day over the last 30 days."],
            ],
            [1.5*inch, CW - 1.5*inch],
        ),
        h2("Interpreting Fill Rate"),
        p("Fill rate = filled signals ÷ total signals. Below 50% usually means risk "
          "guards are blocking most signals. Filter Logs to <b>Blocked</b> and read "
          "the reason column."),
        PageBreak(),
    ]

    # Ch 12 ───────────────────────────────────────────────────────────────────
    e += chapter(12, "Strategy Health & Drift Monitor") + [
        p("Strategy Health compares live trading performance against backtest "
          "benchmarks. It detects when a strategy drifts from expected behaviour."),
        dtable(
            ["Status", "Meaning", "Recommended Action"],
            [
                ["No Drift",
                 "Live win rate within normal range of backtest.",
                 "No action needed."],
                ["Minor Drift",
                 "Live performance below backtest by a noticeable margin.",
                 "Monitor closely. Consider re-tuning."],
                ["Major Drift",
                 "Live performance significantly underperforms backtest.",
                 "Pause the strategy and re-tune parameters."],
                ["No Benchmark",
                 "No backtest has been run for this strategy yet.",
                 "Run a backtest to enable drift monitoring."],
            ],
            [1.0*inch, 1.9*inch, CW - 1.0*inch - 1.9*inch],
        ),
        callout("Run a backtest for every strategy you enable. This establishes the "
                "benchmark for drift detection and gives the AI Tuner a reference "
                "for weekly optimisation.", "tip"),
        PageBreak(),
    ]

    # Ch 13 ───────────────────────────────────────────────────────────────────
    e += chapter(13, "Backtesting Studio") + [
        p("Test any of the 14 strategies against historical price data before risking "
          "real money. Saved runs persist for comparison."),
        steps([
            ("Choose strategy & symbols",
             "Select from the strategy dropdown. Enter tickers separated by commas "
             "(e.g., AAPL, MSFT or BTC/USDT, ETH/USDT)."),
            ("Set date range & costs",
             "Set start/end dates (30 days minimum), initial capital, position size %, "
             "commission %, and slippage %."),
            ("Run and save",
             "Click Run Backtest. Results show total return, win rate, max drawdown, "
             "Sharpe ratio, and a full trade log. Name the run to save it."),
        ]),
        h2("Key Metrics"),
        dtable(
            ["Metric", "Meaning"],
            [
                ["Total Return",  "Net profit as % of starting capital over the test period."],
                ["Win Rate",      "% of trades that closed with a profit."],
                ["Max Drawdown",  "Largest peak-to-trough decline. Over 20% is a warning sign."],
                ["Sharpe Ratio",  "Risk-adjusted return. Above 1.0 acceptable; above 2.0 excellent."],
                ["Avg Trade P&L", "Average dollar profit/loss per completed trade."],
            ],
            [1.2*inch, CW - 1.2*inch],
        ),
        callout("Past performance does not predict future results. Backtests use daily "
                "bar data and assume unlimited liquidity.", "danger"),
        PageBreak(),
    ]

    # Ch 14 ───────────────────────────────────────────────────────────────────
    e += chapter(14, "AI Tuning & Trade Explanations") + [
        h2("Trade Explanations"),
        p("Every trade execution queues an AI explanation job. The AI reads the signal "
          "reason (indicator values, crossover details, pattern names) and writes a "
          "2–3 sentence plain-English explanation visible in the Logs page."),
        p("Two providers supported:"),
        bullet("<b>Claude</b> (Anthropic API) — requires ANTHROPIC_API_KEY in .env"),
        bullet("<b>Ollama</b> (local, free) — requires Ollama running at localhost:11434"),
        SP(0.1),
        h2("Weekly Auto-Tuner"),
        p("Every Sunday at 11 PM ET, the auto-tuner analyses each strategy's live "
          "win rate vs. the backtest benchmark and proposes adjusted parameters "
          "(RSI thresholds, EMA periods, notional sizes) to improve performance. "
          "Results appear on the AI Tuning page."),
        callout("Trigger a manual tuning run at any time from the AI Tuning page. "
                "Suggestions can be applied with one click.", "tip"),
        PageBreak(),
    ]

    # Ch 15 ───────────────────────────────────────────────────────────────────
    e += chapter(15, "Webhook Signals") + [
        p("TradeBot can receive trade signals from TradingView, custom scripts, or "
          "any HTTP client. Incoming signals pass through the full 10-layer risk "
          "engine before execution."),
        steps([
            ("Get your URL and token",
             "Settings → Webhook section. Copy your unique URL and secret token."),
            ("Send a POST request",
             "POST to /api/webhook/signal with header "
             "X-Webhook-Token: <token> and a JSON body."),
        ]),
        h2("Signal JSON Format"),
        dtable(
            ["Field", "Type", "Description"],
            [
                ["symbol",     "string",  "Ticker (e.g., AAPL or BTC/USDT)"],
                ["side",       "string",  "buy or sell"],
                ["qty",        "number",  "Shares or units (use this OR notional)"],
                ["notional",   "number",  "Dollar amount to trade (use this OR qty)"],
                ["account_id", "integer", "Optional — target a specific broker account"],
            ],
            [0.8*inch, 0.65*inch, CW - 0.8*inch - 0.65*inch],
        ),
        callout("Webhook signals pass through all risk guards — exactly the same as "
                "strategy signals.", "tip"),
        PageBreak(),
    ]

    # Ch 16 ───────────────────────────────────────────────────────────────────
    e += chapter(16, "Notifications") + [
        p("Get alerted on trades, risk blocks, price alerts, and daily summaries "
          "via email, Telegram, Slack, or Discord."),
        h2("Email (Gmail / SMTP)"),
        steps([
            ("Generate a Gmail App Password",
             "Google Account → Security → 2-Step Verification → App passwords → "
             "generate one named TradeBot."),
            ("Fill in SMTP settings",
             "Host: smtp.gmail.com  |  Port: 587  |  "
             "Username: your Gmail  |  Password: the App Password."),
        ]),
        h2("Telegram"),
        steps([
            ("Create a bot via BotFather",
             "Message @BotFather in Telegram → /newbot → follow prompts → copy the token."),
            ("Get your Chat ID",
             "Start a chat with your bot, then visit "
             "api.telegram.org/bot<TOKEN>/getUpdates to find your chat_id. "
             "Paste both into Settings."),
        ]),
        h2("Slack & Discord"),
        bullet("<b>Slack</b>: Apps → Incoming Webhooks → Add to Slack → copy webhook URL."),
        bullet("<b>Discord</b>: Server Settings → Integrations → Webhooks → "
               "New Webhook → copy URL."),
        p("Paste the URL into <b>Settings → Notifications</b>."),
        PageBreak(),
    ]

    # Ch 17 ───────────────────────────────────────────────────────────────────
    e += chapter(17, "Going Live with Real Money") + [
        callout("Only switch to live trading after at least 2–4 weeks of successful "
                "paper trading with results you understand.", "danger"),
        h2("Pre-Live Checklist"),
        bullet("Ran paper trading for at least 2–4 weeks"),
        bullet("Understand which strategies are enabled and why"),
        bullet("Daily loss limit is set (2% recommended)"),
        bullet("Position sizes are appropriate for your account size"),
        bullet("Notifications configured — email or Telegram at minimum"),
        bullet("Kill switch accessible from your phone / tablet"),
        SP(0.1),
        h2("Switching to Live"),
        p("Broker Accounts → Add Account → pick broker → select <b>Live</b> → enter "
          "live API keys → Test → assign strategies."),
        bullet("<b>Alpaca live</b>: requires identity verification and a linked bank "
               "account at alpaca.markets."),
        bullet("<b>Binance live</b>: generate keys at binance.com → API Management "
               "with Spot & Margin Trading enabled and withdrawals disabled."),
        PageBreak(),
    ]

    # Ch 18 ───────────────────────────────────────────────────────────────────
    e += chapter(18, "VPS Deployment (Ubuntu)") + [
        p("Run TradeBot on a VPS for 24/7 operation without keeping your PC on."),
        h2("Recommended Hosting"),
        dtable(
            ["Provider", "Plan", "Price", "Notes"],
            [
                ["DigitalOcean", "Basic Droplet 1GB",  "$6/mo",  "Ubuntu 22.04 LTS"],
                ["Hetzner",      "CX22 (2 vCPU, 4GB)", "~€4/mo", "Best price/performance"],
            ],
            [1.0*inch, 1.5*inch, 0.7*inch, CW - 1.0*inch - 1.5*inch - 0.7*inch],
        ),
        h2("One-Command Deploy"),
        p("The included deploy.sh script handles everything:"),
        steps([
            ("Clone the repo",
             "git clone https://github.com/your-repo/TradeBot.git /opt/tradebot-src"),
            ("Run deploy",
             "cd /opt/tradebot-src && sudo bash deploy.sh"),
            ("Configure .env",
             "sudo nano /opt/tradebot/.env — set DB_SECRET_KEY and notification tokens."),
            ("Start the bot",
             "sudo systemctl start tradebot"),
            ("Monitor",
             "sudo systemctl status tradebot\n"
             "journalctl -u tradebot -f    (live log stream)"),
        ]),
        callout("Dashboard is at http://<your-vps-ip>:8000. Use a strong password "
                "and consider nginx + HTTPS for production.", "note"),
        PageBreak(),
    ]

    # Ch 19 ───────────────────────────────────────────────────────────────────
    e += chapter(19, "Troubleshooting & FAQ")

    faq_items = [
        ("Strategy not placing orders",
         "Check: (1) Strategy toggled on for a broker account. "
         "(2) A risk guard blocking it — filter Logs to Blocked. "
         "(3) Stock strategy: is the market open? "
         "(4) Crypto: DB_SECRET_KEY set in .env? "
         "(5) Does the symbol meet strategy criteria?"),
        ("Binance not trading",
         "Most common: (1) DB_SECRET_KEY missing from .env — decrypt fails silently. "
         "(2) Demo vs. live key mismatch. "
         "(3) Balance below $10 USDT minimum. "
         "(4) Price in neutral zone (Crypto Grid only signals near band edges)."),
        ("Very low fill rate — mostly Blocked signals",
         "A risk guard is blocking most trades. Filter Logs to Blocked and read the "
         "reason column — it names exactly which guard triggered. Adjust in Risk Controls."),
        ("PDT rule block",
         "Account under $25,000 has used 3 day-trades in a 5-day window. Block lifts "
         "automatically. Fund above $25,000 to become PDT-exempt. PDT does not apply "
         "to crypto."),
        ("Daily loss limit triggered",
         "Kill switch activated automatically. Review positions, adjust the limit if "
         "needed, then click Deactivate Kill Switch to resume."),
        ("API key / decryption error",
         "DB_SECRET_KEY in .env is wrong or missing. If you changed it after saving "
         "keys, stored credentials are unrecoverable — re-enter them. Always back up .env."),
        ("Email notifications not arriving",
         "Check spam folder. Use a Gmail App Password (not your regular password). "
         "SMTP: smtp.gmail.com, port 587."),
        ("Where is my data stored?",
         "All data lives in trading.db (SQLite) in the project folder. Never delete "
         "or overwrite this file — it holds all credentials, settings, and history."),
        ("Can I run TradeBot 24/7?",
         "Yes — the server runs continuously. Stock strategies skip orders outside "
         "market hours. Crypto runs 24/7. Use a VPS or keep your machine on."),
    ]

    for q, a in faq_items:
        e.append(KeepTogether([
            Paragraph(f"<b>Q: {q}</b>", S_BODY),
            Paragraph(f"A: {a}", S_MUTED),
            SP(0.06),
        ]))

    e += [
        SP(0.2),
        HR(),
        callout("Still stuck? Check the server console output. The engine logs every "
                "skip, block, and error with a full reason.", "good"),
    ]

    return e


# ── Shortcut helpers used in story ────────────────────────────────────────────
def chapter(num, title):
    return [
        Paragraph(f"Chapter {num}", S_CHAP),
        Paragraph(title, S_H1),
        HR(),
    ]

def h2(txt):
    return Paragraph(txt, S_H2)

def p(txt):
    return Paragraph(txt, S_BODY)

def _feat_cell(title, desc):
    """Mini feature card for the cover page."""
    st_t = ps(f"ft_{title[:4]}", fontName="Helvetica-Bold", fontSize=9,
              textColor=BLUE, leading=12)
    st_d = ps(f"fd_{title[:4]}", fontSize=8, textColor=MUTED, leading=12)
    inner = Table(
        [[Paragraph(title, st_t)], [Paragraph(desc, st_d)]],
        colWidths=[None],
    )
    inner.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    outer = Table(
        [[inner]],
        colWidths=[CW / 3 - 8],
    )
    outer.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), CARD),
        ("LINEABOVE",     (0, 0), (-1, 0),  1.5, BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    return outer


if __name__ == "__main__":
    build()
