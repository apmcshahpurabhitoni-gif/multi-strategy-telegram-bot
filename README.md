# Mavis Trading Bot

A multi-strategy paper-trading bot for Telegram, built around modern retail methodologies (multi-timeframe trend + Smart Money Concepts), with a built-in backtester and a live neobrutalism web dashboard.

> **Status:** Paper trading only. Do not risk real capital without extensive forward-testing.

---

## ✨ Features

- **Two strategies running in parallel**
  - **TrendPulse 1H** — 4H trend filter (EMA50) + 1H MACD/RSI/EMA20 entries on candle close (no repaint)
  - **4H Sweep + FVG** — liquidity-sweep detection on the 4H, then waits for a 1H Fair Value Gap fill
- **Real-time Telegram alerts** with signal age tags (`🔥 FRESH` / `⚠️ STALE`) and stale-warning on restart
- **Neobrutalism web dashboard** at `/dashboard` — 7 tabs, 3 themes, customizable accent
- **Built-in backtester** — equity-curve chart + metrics via `/backtest` or the dashboard
- **Resilient data layer** — yfinance → CoinGecko / Binance fallback for BTC; GC=F → GLD → IAU for Gold
- **Optional Supabase persistence** — survives Render free-tier restarts

---

## 🧠 Strategies

### 1. TrendPulse 1H (Primary)
- **4H filter:** price > EMA50 (uptrend) / < EMA50 (downtrend)
- **1H trigger:** MACD cross + RSI(14) confirmation + EMA20 proximity
- **Risk:** ATR(14)-based SL, 2R TP, 0.5R trailing once in profit
- **No repaint:** signals only emit on the close of the 1H candle

### 2. 4H Sweep + FVG
- **Sweep:** 4H candle wicks above prior high *and* below prior low, then closes back inside
- **FVG fill:** waits up to 24h for price to enter a 1H 3-candle Fair Value Gap
- **Risk:** 1.5R SL beyond the sweep extreme, 3R TP
- **Assets:** NSE stocks + major forex pairs

---

## 🤖 Telegram Commands

| Command | What it does |
|---|---|
| `/start` | Guide + control menu |
| `/check` | Scan all assets now |
| `/test` | Test data feeds (debug) |
| `/summary` | Live prices & status |
| `/stats` | Win rate & P/L per account |
| `/balance` | Virtual account balances |
| `/pending` | Pending sweep setups |
| `/risk` | Exposure & R-multiples |
| `/weekly` | Weekly performance digest |
| `/news` | Economic calendar |
| `/refreshnews` | Force-refresh the news cache |
| `/nifty` | Nifty 50 stock prices |
| `/backtest <SYM> <STRAT> <DAYS>` | Backtest with equity-curve chart |
| `/clear` | Reset everything to ₹1,00,000 |

---

## 🌐 Web Dashboard

Open `/dashboard` on your deployed URL. Seven tabs:

| Tab | What you get |
|---|---|
| 🏠 Overview | Account balances, equity curve, exposure / risk / max drawdown, strategy performance, open-trade R-multiples |
| 💼 Trades | Live open trades with live P/L, progress to TP, close button + pending sweep setups |
| 📡 Signals | Last 24h signals grouped by day, with `🔥 FRESH` (< 1h) or `⚠️ STALE` (> 4h) tags |
| 📜 History | Closed trades grouped by day with daily totals and W/L |
| 📰 News | Economic calendar grouped by day, ET → IST times, impact tags |
| 🇮🇳 Nifty | Nifty 50 + Bank Nifty and 15 NSE stocks (lazy-loaded) |
| 🧪 Backtest | Run strategies on any symbol over 30–365 days — includes an equity-curve chart |

### 🎨 Themes

The dashboard ships with a **neobrutalism** design system (heavy borders, hard shadows, flat color, no gradients on chrome). Three modes are available — click the 🌑/☀️/🌙 button in the top-right to cycle:

| Mode | Look | Use when |
|---|---|---|
| **Normal** (default, 🌑) | Warm grey on off-white with black borders | You want a calm, "terminal" look that doesn't hurt your eyes |
| **Light** (☀️) | White card on off-white bg, black borders, accent from 🎨 | Daytime, bright room, or want a clean paper look |
| **Dark** (🌙) | Dark grey on near-black, off-white borders | Night trading, want high contrast without OLED fatigue |

### 🎨 Customize accent (the 🎨 button)

Click the **🎨** button in the header to open the accent picker. You can:

- Pick one of 16 preset swatches (no blue — the palette stays grey + warm)
- Or punch in a custom hex code (e.g. `#e63946` for crimson, `#06d6a0` for mint)
- The accent drives the active-tab color, the highlight bar on Nifty cards, the news-day pills, the success indicators — everything

Choices are persisted in `localStorage` (`mavis_theme`, `mavis_accent`), so they survive page refresh and even redeploys of the static HTML.

> The active tab's text color is auto-computed from the accent (luminance check), so you can pick any color and the text stays readable.

### Mobile-first

The bottom tab bar uses a 7-column CSS Grid with `safe-area-inset-bottom` for notched phones, and the active tab "pops up" with a hard shadow + spring animation (cubic-bezier overshoot). At ≤360px the labels scale down so nothing overflows.

---

## 📁 Project Structure

```
.
├── main.py              # Core bot: scanner, monitor, Telegram handlers, threads
├── backtest.py          # Backtest engine + matplotlib equity-curve chart
├── dashboard_api.py     # WSGI app: /ping, /webhook, /dashboard, /api/*
├── dashboard/
│   └── index.html       # Single-page dashboard (neobrutalism UI)
├── requirements.txt
├── render.yaml          # Render blueprint
├── Dockerfile           # Container build (optional)
├── .env.example         # Environment variable template
├── .gitignore
├── DEPLOYMENT_GUIDE.md  # Step-by-step deploy for Render / Docker / Local
└── README.md
```

State lives in `/tmp/workspace/*.json`:
- `accounts.json` — virtual account balances & daily trade counts
- `active_trades.json` — currently open paper trades
- `trade_history.json` — closed trades
- `sent_signals.json` — dedup cache for sent alerts
- `pending_sweeps.json` — sweeps waiting for FVG fill
- `reset_state.json` — last daily reset date (isolated to prevent a known dict-key crash)
- `news_cache.json` — 24h ForexFactory calendar cache

> If `SUPABASE_URL` + `SUPABASE_KEY` are set, the bot transparently syncs these to a `bot_data` table.

---

## 🛠️ Tech Stack

| Layer | Tech |
|---|---|
| Language | Python 3.12 |
| Data | yfinance, CoinGecko API, Binance API |
| Analysis | pandas, numpy |
| Bot | pyTelegramBotAPI |
| Charts | matplotlib |
| Web | WSGI (built-in threaded server) |
| Frontend | Vanilla HTML/CSS/JS — neobrutalism design system |
| Storage | JSON files (`/tmp/workspace/`) + optional Supabase |
| Deploy | Render (Web Service) or Docker |

---

## ⚙️ Configuration (Environment Variables)

Copy `.env.example` to `.env` and fill in:

| Var | Required | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | From `@BotFather` |
| `TELEGRAM_CHAT_ID` | ✅ | Your chat id (from `getUpdates`) |
| `WEBHOOK_URL` | ✅ | `https://<your-app>.onrender.com/webhook` |
| `SUPABASE_URL` | optional | For persistent state across restarts |
| `SUPABASE_KEY` | optional | Service-role key (keep secret) |
| `PORT` | optional | Defaults to `8080` |

---

## 🚀 Quickstart (TL;DR)

```bash
git clone https://github.com/<you>/multi-strategy-telegram-bot.git
cd multi-strategy-telegram-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID + WEBHOOK_URL
python main.py
```

Open `http://localhost:8080/dashboard` to see the UI. See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) for Render / Docker deployment.

---

## 🐳 Docker (optional)

```bash
docker build -t mavis-trading-bot .
docker run --rm --env-file .env -p 8080:8080 mavis-trading-bot
```

---

## 🧪 Development

### Local setup
```bash
git clone https://github.com/<you>/multi-strategy-telegram-bot.git
cd multi-strategy-telegram-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in values
python main.py
```

### Threading model
| Thread | Job |
|---|---|
| Main | WSGI server (`/ping`, `/webhook`, `/dashboard`) |
| Scanner | Loops through assets, evaluates both strategies |
| Monitor | Updates open trades, trailing stops, TP/SL checks |
| Pending Sweeps | Watches for FVG fills (90s interval) |
| Daily Reset | Midnight IST reset + digest |
| Weekly Digest | Sunday 21:00 IST summary |

### API endpoints
| Endpoint | Method | Purpose |
|---|---|---|
| `/ping` | GET | Health check (cron-job.org) |
| `/webhook` | POST | Telegram updates |
| `/dashboard` | GET | SPA shell |
| `/api/dashboard` | GET | Full state snapshot |
| `/api/prices?symbols=...` | GET | Live prices |
| `/api/close-trade` | POST | Force-close a trade |
| `/api/backtest?symbol=...&strategy=...&days=...` | GET | Run a backtest |
| `/api/health` | GET | Quick health check |

### Code style
- Python 3.12+, type hints encouraged
- Functions under ~50 lines
- Document non-obvious logic inline
- No magic numbers — use `config.py` if you're adding parameters

### Frontend

`dashboard/index.html` is intentionally a single self-contained file — no build step, no framework. To iterate on the UI:

1. Open `dashboard/index.html` in a browser, OR
2. Run `python -m http.server 8080` in the repo root and visit `http://localhost:8080/dashboard/`
3. Edit and refresh

Theme + accent choices live in `localStorage` under `mavis_theme` and `mavis_accent`. Clear them in DevTools to reset.

---

## ⚠️ Known Issues & Fixes

| Issue | Status | Fix |
|---|---|---|
| Daily Reset crash (`'str' object does not support item assignment`) | ✅ Fixed | `last_reset_date` moved to its own `reset_state.json`; non-dict keys in `accounts.json` are purged on boot. Self-heals on deploy. |
| Stale signals after restart | ✅ Fixed | "✅ BOT STARTED" boot message with timestamp; every signal shows `⏳ Signal Age` (`🔥 FRESH` < 1h, `⚠️ STALE` > 4h). |
| **Backtest crash** — `cannot access local variable 'sl' where it is not associated with a value` | ✅ Fixed | The TrendPulse SHORT branch used `sl, tp, qty = ..., self._calc_qty(... sl)` in a single tuple-unpacking line. Python evaluates the RHS left-to-right and `sl` wasn't bound yet. Now we assign `sl` first, then derive `qty`. |
| **News tab empty** — `No upcoming events found` even when API returns data | ✅ Fixed | `get_cached_news()` was saving the date in a field called `time` while the dashboard was reading `ev.date`. Renamed to `date` (with `currency`, `forecast`, `previous` exposed too). Also widened the flag dictionary to support 2-letter country codes. |
| **Bottom nav buttons squashed on mobile** | ✅ Fixed | Replaced the 7-flex with a `grid-template-columns: repeat(7, 1fr)` layout, removed per-button margins, added `safe-area-inset-bottom`, scaled the active tab with a spring overshoot. |
| Yahoo Finance blocks cloud IPs | ⚠️ Mitigated | BTC → CoinGecko/Binance fallback. Gold → `GC=F` → `GLD` → `IAU` chain. |
| Render free tier sleeps | ⚠️ Mitigated | External cron-job pings `/ping` every 10 min. |

---

## 📝 License

MIT — free to use, modify, and deploy.

## 🙏 Credits

- TrendPulse logic based on multi-timeframe MACD research
- Sweep + FVG based on Smart Money Concepts
- Price fallbacks engineered for Render deployment
- Dashboard design system inspired by [neobrutalism.dev](https://www.neobrutalism.dev/)
- Built with ❤️ for traders who want automation without the BS

> ⚡ **Pro tip:** After deploy, run `/test` to verify data feeds, then `/backtest BTC-USD trendpulse 60` to see the equity-curve chart in action. On the dashboard, hit 🎨 to pick an accent that matches your screen.
