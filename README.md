# 🤖 Mavis — Multi-Strategy Telegram Trading Bot

> A production-grade, paper-trading bot that scans Forex, Crypto, Gold, Nifty 50, and Bank Nifty across multiple timeframes. It fires high-confluence signals via Telegram and serves a real-time web dashboard.

**Live Dashboard:** [multi-strategy-telegram-bot-1.onrender.com/dashboard](https://multi-strategy-telegram-bot-1.onrender.com/dashboard)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📊 **Multi-Account Paper Trading** | 4 isolated accounts — Macro, Nifty, NY Session, Sweep 4H — each with its own balance, limits, and P/L tracking |
| 🎯 **Dual Strategy Engine** | **UT Bot Signals** (15m trend + EMA50 + RSI confluence) + **Smart Money Sweep + FVG** (4H liquidity sweep with 1H Fair Value Gap entry) |
| 🇮🇳 **Nifty 50 Scanner** | Live scanning of 15 most liquid NSE stocks (Reliance, HDFC Bank, ICICI Bank, TCS, Infosys, etc.) |
| 🌐 **Global Markets** | BTC-USD, Gold (GC=F), EUR/USD, GBP/USD, USD/JPY, ^NSEI, ^NSEBANK |
| 📰 **Economic Calendar Alerts** | Auto-fetches high-impact news from Forex Factory; sends morning digest + 30-min pre-news warnings |
| 🛑 **Smart Trailing Stop** | Tiered trailing — breakeven at 1% → lock 30% at 3% → lock 50% at 5% |
| 📈 **Live Web Dashboard** | Real-time balances, open trades, P/L, signal history, pending sweeps, and news — auto-refreshes every 15s |
| 🔔 **Telegram Control Center** | Button menu, mute assets, instant charts, manual scan, balance checks, and full trade history |
| 💾 **State Persistence** | Local JSON + Supabase cloud sync — survives Render redeploys and free-tier restarts |
| 🛡️ **Risk Guards** | Daily trade limits per account, duplicate signal deduplication, 4H sweep cooldowns, market-hours filtering |

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Yahoo Finance │────▶│   Strategy Engine│────▶│  Telegram Bot   │
│   + CoinGecko   │     │  (UT Bot + Sweep)│     │  (pyTelegramBot)│
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │                         │
         ▼                       ▼                         ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Price Cache    │     │  Pending Sweeps  │     │  4 Accounts     │
│  (60s TTL)      │     │  (FVG Watchlist) │     │  (JSON + DB)    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │                         │
         └───────────────────────┴─────────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────┐
                    │   WSGI Web Server    │
                    │  /dashboard  /api/*  │
                    │  (Render-hosted)     │
                    └──────────────────────┘
```

### Strategy 1: UT Bot Signals
- **Timeframe:** 15m primary, 5m confirmation
- **Entry:** UT Bot SuperTrend flip + EMA50 alignment + RSI filter (30–70)
- **SL/TP:** 2× ATR stop / 4× ATR target
- **Accounts:** Macro (default) or NY Session (18:00–01:30 IST)

### Strategy 2: Smart Money Sweep + FVG
- **Timeframe:** 4H sweep detection (built from 1H candles)
- **Entry:** Liquidity sweep → 1H Fair Value Gap formation → price retraces into FVG zone
- **SL:** Sweep extreme (low for bullish, high for bearish)
- **TP:** 2× risk
- **Expiry:** 24h if FVG never fills
- **Accounts:** Nifty (`.NS` stocks) or Sweep 4H (everything else)

---

## 📁 File Structure

```
├── main.py              # Core bot: strategies, execution, monitoring, Telegram handlers
├── dashboard_api.py     # WSGI API: /dashboard, /api/dashboard, /api/prices, /api/health
├── dashboard/
│   └── index.html       # Live web dashboard (dark theme, auto-refresh)
├── requirements.txt     # Python dependencies
├── .gitignore           # Excludes JSON state files & env vars
└── README.md            # This file
```

### State Files (auto-created at runtime)
```
/workspace/
├── accounts.json        # Balances + daily trade counters
├── active_trades.json   # Currently open positions
├── trade_history.json   # Closed trades with P/L
├── sent_signals.json    # Signal deduplication cache
├── pending_sweeps.json  # Sweep setups waiting for FVG
└── muted_assets.json    # User-muted symbols
```

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/apmcshahpurabhitoni-gif/multi-strategy-telegram-bot.git
cd multi-strategy-telegram-bot
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file or set these in your hosting platform:

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | From [@BotFather](https://t.me/botfather) |
| `TELEGRAM_CHAT_ID` | ✅ | Your Telegram user/chat ID |
| `SUPABASE_URL` | ❌ | Supabase REST endpoint (for cloud persistence) |
| `SUPABASE_KEY` | ❌ | Supabase service_role / anon key |
| `WEBHOOK_URL` | ❌ | `https://your-app.onrender.com/webhook` (optional) |
| `PORT` | ❌ | Web server port (default: 10000) |

### 3. Run Locally

```bash
python main.py
```

The bot will:
1. Start the WSGI web server (`:10000`)
2. Load/initialize 4 paper accounts at ₹1,00,000 each
3. Spawn background threads: scanner, monitor, daily reset, pending sweeps, news alerts
4. Begin polling Telegram for commands

---

## 🖥️ Dashboard

Open `http://localhost:10000/dashboard` (or your Render URL) to see:

- **Account Cards** — live balance, daily trades used/remaining, today & week P/L
- **Live Trades** — entry, current price, unrealized P/L, progress bar to TP
- **Today's Signals** — last 24h signals with direction, strategy, and time
- **Trade History** — last 15 closed trades with win/loss and P/L
- **Pending Sweeps** — active sweep setups waiting for FVG formation/fill
- **Economic Calendar** — today's high/medium impact news events

---

## 🤖 Telegram Commands

| Command | What it does |
|---------|--------------|
| `/start` / `/help` | Show welcome + button menu |
| `/menu` | Resend the inline button control panel |
| `/balance` | Show all 4 account balances + trade limits |
| `/stats` | Win rate, W/L count, and total P/L per account |
| `/summary` | Live prices + mute status for all monitored assets |
| `/check` | Manual market scan — instant signal report |
| `/nifty` | Fetch live prices for all 15 Nifty 50 stocks |
| `/pending` | List all sweep setups waiting for FVG |
| `/news` | Full weekly economic calendar |
| `/indi1` | Diagnose Strategy 1 (Sweep) across all assets |
| `/indi2` | Diagnose Strategy 2 (UT Bot) across all assets |
| `/test` | Test data fetch for every monitored symbol |
| `/clear` | **⚠️ RESET** — wipe all balances back to ₹1,00,000 |

### Inline Buttons
- **📊 Dashboard** — Opens the web dashboard in browser
- **🔥 Live Trades** — Lists current open positions
- **📡 Signals** — Today's fired signals
- **📜 History** — Overall trade stats
- **💰 Balances** — Account summary
- **📰 News** — Today's economic calendar
- **📈 Nifty** — Nifty 50 stock prices
- **🔄 Refresh** — Clears price cache
- **📈 Chart** — Generates candlestick chart for the symbol
- **🔇 Mute / 🔊 Unmute** — Stop/start alerts for a symbol

---

## 🛠️ Tech Stack

- **Python 3.11+**
- **pyTelegramBotAPI** — Telegram bot framework
- **yfinance** — Market data (Yahoo Finance)
- **pandas + numpy** — Indicator calculations & data handling
- **matplotlib** — Candlestick chart generation
- **requests** — HTTP for news API + Supabase sync
- **wsgiref** — Built-in WSGI server (zero-dependency web layer)

---

## 🌐 Deployment (Render)

This bot is optimized for [Render](https://render.com) free tier:

1. **Create a Web Service** → Connect your GitHub repo
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `python main.py`
4. **Add Environment Variables** (see table above)
5. **Done.** The bot auto-starts with web dashboard + Telegram polling.

> **Note:** Render free tier sleeps after 15 min of inactivity. The bot uses `bot.polling()` which keeps the dyno awake via active connections. If you prefer webhooks, set `WEBHOOK_URL`.

---

## ⚙️ Configuration

### Account Limits (edit in `main.py`)

```python
ACCOUNT_LIMITS = {
    "macro": 20,      # Global macro trades per day
    "nifty": 5,       # Nifty 50 + Bank Nifty trades per day
    "ny_session": 3,  # NY session window trades per day
    "sweep_4h": 3,    # Sweep/FVG trades per day
}
```

### Monitored Assets (edit in `main.py`)

```python
MONITORED = [
    ("BTC-USD", "Crypto"),
    ("GC=F", "Gold"),
    ("EURUSD=X", "Forex"),
    ("GBPUSD=X", "Forex"),
    ("USDJPY=X", "Forex"),
    ("^NSEI", "NIFTY 50"),
    ("^NSEBANK", "BANK NIFTY"),
] + [(sym, "NSE") for sym, _ in NIFTY_STOCKS]
```

### Risk Per Trade
- Default: **2% of account balance** per trade
- Trailing stop: Breakeven @ 1% → 30% lock @ 3% → 50% lock @ 5%

---

## 🧪 Testing & Diagnostics

```bash
# Test all data feeds
python -c "import main; main.cmd_test(None)"

# Check if dashboard API is healthy
curl https://your-app.onrender.com/api/health

# Get live prices for specific symbols
curl "https://your-app.onrender.com/api/prices?symbols=BTC-USD,GC=F,RELIANCE.NS"

# Get full dashboard snapshot
curl https://your-app.onrender.com/api/dashboard
```

---

## 🗺️ Roadmap

- [ ] SQLite/PostgreSQL migration (replace JSON state files)
- [ ] Correlation guard (prevent 3+ bank stocks simultaneously)
- [ ] Intraday drawdown circuit breaker (pause account after 8% loss)
- [ ] WebSocket real-time dashboard updates
- [ ] Force-close button on dashboard trades
- [ ] `/risk` command showing exposure & max drawdown
- [ ] Prometheus metrics endpoint (`/api/metrics`)
- [ ] Backtesting module for strategy validation

---

## ⚠️ Disclaimer

This is a **paper trading bot** for educational and research purposes. It simulates trades using virtual balances. **Do not use this code with real money** without extensive backtesting, risk assessment, and professional review. The authors are not responsible for any financial losses.

---

## 📄 License

MIT License — feel free to fork, modify, and deploy.

---

## 🙋 Support

- Open an [Issue](../../issues) for bugs or feature requests
- Use `/test` in Telegram if data feeds are failing
- Check `/api/health` on your dashboard URL to verify the bot is alive

> Built with ❤️ for the Indian trading community.
