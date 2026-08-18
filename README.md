# Mavis Trading Bot

A multi-strategy paper-trading bot for Telegram, built around modern retail methodologies (multi-timeframe trend + Smart Money Concepts), with a built-in backtester and a live web dashboard.

> **Status:** Paper trading only. Do not risk real capital without extensive forward-testing.

---

## ✨ Features

- **Two strategies running in parallel**
  - **TrendPulse 1H** — 4H trend filter (EMA50) + 1H MACD/RSI/EMA20 entries on candle close (no repaint)
  - **4H Sweep + FVG** — liquidity-sweep detection on the 4H, then waits for a 1H Fair Value Gap fill
- **Real-time Telegram alerts** with signal age tags (`🔥 FRESH` / `⚠️ STALE`) and stale-warning on restart
- **Web dashboard** at `/dashboard` — overview, trades, signals, history, Nifty, news, backtest
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

Open `/dashboard` on your deployed URL. Six tabs:

| Tab | What you get |
|---|---|
| 🏠 Overview | Account balances, equity curve, exposure / risk / max drawdown, strategy performance, open-trade R-multiples |
| 🔥 Trades | Live open trades with live P/L, progress to TP, close button + pending sweep setups |
| 📡 Signals | Last 24h signals grouped by day, with `🔥 FRESH` (< 1h) or `⚠️ STALE` (> 4h) tags |
| 📜 History | Closed trades grouped by day with daily totals and W/L |
| 📈 Nifty | Nifty 50 + Bank Nifty and 15 NSE stocks (lazy-loaded) |
| 📰 News | Economic calendar grouped by day, ET → IST times, impact tags |
| 🧪 Backtest | Run strategies on any symbol over 30–180 days — includes an equity-curve chart |

---

## 📁 Project Structure

```
.
├── main.py              # Core bot: scanner, monitor, Telegram handlers, threads
├── backtest.py          # Backtest engine + matplotlib equity-curve chart
├── dashboard_api.py     # WSGI app: /ping, /webhook, /dashboard, /api/*
├── dashboard/
│   └── index.html       # Single-page dashboard
├── requirements.txt
├── render.yaml          # Render blueprint
├── Dockerfile           # Container build (optional)
├── .env.example         # Environment variable template
├── .gitignore
└── README.md
```

State lives in `/tmp/workspace/*.json`:
- `accounts.json` — virtual account balances & daily trade counts
- `active_trades.json` — currently open paper trades
- `trade_history.json` — closed trades
- `sent_signals.json` — dedup cache for sent alerts
- `pending_sweeps.json` — sweeps waiting for FVG fill
- `reset_state.json` — last daily reset date (isolated to prevent a known dict-key crash)

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

## 🚀 Deployment Guide

### Step 1 — Telegram setup
1. Talk to `@BotFather` → `/newbot` → copy the token.
2. Send `/start` to your bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy your `chat_id`.

### Step 2 — (Recommended) Supabase for persistence
Render's free tier has ephemeral disk — without Supabase, `accounts.json` and friends vanish on restart.
1. Create a free project at [supabase.com](https://supabase.com).
2. In the SQL editor, create the `bot_data` table:
   ```sql
   create table if not exists bot_data (
     key text primary key,
     value jsonb,
     updated_at timestamptz default now()
   );
   alter table bot_data enable row level security;
   create policy "service role full access" on bot_data
     for all using (true) with check (true);
   ```
3. Settings → API → copy Project URL + `service_role` key.

### Step 3 — Deploy to Render
1. Push your repo to GitHub.
2. Render → **New +** → **Web Service** → connect the repo.
3. Settings:
   - **Environment:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `python main.py`
4. Add the env vars from the table above in the Render dashboard.
5. Click **Deploy**.

Or use the included `render.yaml` blueprint: Render → **New +** → **Blueprint** → pick the repo. It wires everything up automatically.

### Step 4 — Keep it alive (free tier)
Render spins down after 15 min of inactivity.
1. Sign up at [cron-job.org](https://cron-job.org).
2. Create a cron job: `GET https://<your-app>.onrender.com/ping` every 10 minutes, 24/7.

### Step 5 — Verify
Within ~60 seconds of deploy you should see in Telegram:

```
✅ BOT STARTED
Started At: 18-Aug-2026 10:48 IST

⚠️ Any signal/sweep message older than this one is STALE — do not act on it.
```

Then run `/test` to verify data feeds.

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

### Code style
- Python 3.12+, type hints encouraged
- Functions under ~50 lines
- Document non-obvious logic inline
- No magic numbers — use `config.py` if you're adding parameters

---

## ⚠️ Known Issues & Fixes

| Issue | Status | Fix |
|---|---|---|
| Daily Reset crash (`'str' object does not support item assignment`) | ✅ Fixed | `last_reset_date` moved to its own `reset_state.json`; non-dict keys in `accounts.json` are purged on boot. Self-heals on deploy. |
| Stale signals after restart | ✅ Fixed | "✅ BOT STARTED" boot message with timestamp; every signal shows `⏳ Signal Age` (`🔥 FRESH` < 1h, `⚠️ STALE` > 4h). |
| Yahoo Finance blocks cloud IPs | ⚠️ Mitigated | BTC → CoinGecko/Binance fallback. Gold → `GC=F` → `GLD` → `IAU` chain. |
| Render free tier sleeps | ⚠️ Mitigated | External cron-job pings `/ping` every 10 min. |
| News tab shows "No upcoming events" | ⚠️ Mitigated | Date parser fixed; `/refreshnews` force-refreshes the cache; clear error state if the upstream API is down. |

---

## 📝 License

MIT — free to use, modify, and deploy.

## 🙏 Credits

- TrendPulse logic based on multi-timeframe MACD research
- Sweep + FVG based on Smart Money Concepts
- Price fallbacks engineered for Render deployment
- Built with ❤️ for traders who want automation without the BS

> ⚡ **Pro tip:** After deploy, run `/test` to verify data feeds, then `/backtest BTC-USD trendpulse 60` to see the equity-curve chart in action.
