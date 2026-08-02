# Multi-Strategy Telegram Trading Bot

A multi-account, multi-strategy paper trading bot for Forex, Crypto, Gold, and Indian indices (NIFTY 50, BANK NIFTY). Sends signals via Telegram and serves a live web dashboard.

---

## What It Does

| Feature | Description |
|---------|-------------|
| **4 Trading Accounts** | Macro, Nifty, NY Session, Sweep 4H — each with independent balances and daily trade limits |
| **2 Strategies** | Sweep + Engulfing (4H/1H) and UT Bot Signals (15m) |
| **FVG Wait System** | Sweep setups wait for Fair Value Gap formation before entering |
| **Live Dashboard** | Web dashboard at `/dashboard` showing balances, open trades, signals, P/L charts, and economic calendar |
| **Telegram Alerts** | Real-time signal alerts, trade closures, pending sweep updates, and economic news |
| **Auto Reset** | Midnight IST daily reset of trade counters |

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Telegram Bot  │────▶│    main.py      │────▶│  Yahoo Finance  │
│  (Commands &    │     │  (Trading logic) │     │  (Price data)   │
│   Webhook)      │     │                 │     │                 │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │ dashboard_api.py│
                        │  (/api/dashboard)│
                        └────────┬────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │dashboard/index.html
                        │  (Live Dashboard)│
                        └─────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `main.py` | Bot core — strategies, trade execution, monitoring, Telegram handlers, WSGI server |
| `dashboard_api.py` | API layer — serves `/api/dashboard`, `/api/prices`, `/dashboard` |
| `dashboard/index.html` | Self-contained dashboard UI (single file, no build step) |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container config for Render |
| `render.yaml` | Render deployment config |

### Files NOT Used (Dead Code)

These were from an abandoned React/Vite setup and serve no purpose:

```
src/              ← React app (never deployed)
server.ts         ← Express dev server
vite.config.ts    ← Vite config
package.json      ← Node deps
tsconfig.json     ← TypeScript config
bun.lock          ← Lock file
index.html        ← Vite entry point (not the dashboard)
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Your bot token from [@BotFather](https://t.me/botfather) |
| `TELEGRAM_CHAT_ID` | ✅ | Your Telegram chat ID (send `/start` to [@userinfobot](https://t.me/userinfobot)) |
| `WEBHOOK_URL` | ✅ | `https://your-app.onrender.com/webhook` |
| `PORT` | ❌ | Defaults to `10000` |

---

## Deployment (Render)

1. **Fork / clone** this repo
2. **Create Web Service** on [Render](https://render.com)
3. **Set environment variables** above
4. **Deploy** — Render uses `Dockerfile` + `render.yaml`

The bot auto-starts and begins scanning markets every few minutes.

---

## Telegram Commands

| Command | What it does |
|---------|-------------|
| `/start` | Show command guide |
| `/test` | Test Yahoo Finance data fetch |
| `/check` | Manually scan all assets now |
| `/summary` | Live prices & mute status |
| `/stats` | Win rate & P/L per account |
| `/balance` | Show all account balances |
| `/clear` | Reset everything to ₹1,00,000 |
| `/indi1` | Diagnose Sweep strategy |
| `/indi2` | Diagnose UT Bot strategy |
| `/pending` | Show sweep setups waiting for FVG |
| `/news` | Today's economic calendar |

---

## Dashboard

Visit `https://your-app.onrender.com/dashboard`

### Sections

| Section | Data Source |
|---------|-------------|
| **Total Equity** | Sum of all 4 account balances |
| **Today P/L** | Sum of today's closed trade P/L |
| **This Week** | Sum of last 7 days closed trade P/L |
| **Open Trades** | Live tracked active trades with current price |
| **Win Rate** | Wins / (Wins + Losses) for today |
| **Account Cards** | Per-account balance, daily trades used/limit, P/L |
| **Today's Signals** | Signals fired in last 24h |
| **Cumulative P/L** | Equity curve from trade history |
| **Daily P/L** | Bar chart of daily P/L (Week / 30D toggle) |
| **Last Closed Trades** | Last 15 closed trades |
| **Pending Setups** | Sweeps waiting for FVG fill |
| **Weekly Economic Calendar** | Upcoming forex news with ET + IST times |

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /dashboard` | Serves the dashboard HTML |
| `GET /api/dashboard` | Full snapshot (accounts, trades, signals, history, news) |
| `GET /api/prices?symbols=...` | Batch live prices |
| `GET /api/health` | Health check |
| `GET /ping` | Render health check |

---

## Known Issues & Fixes

### Dashboard shows `--:--:--` and all zeros
**Cause:** `renderAll()` had `if (!state.snapshot) return;` which bailed when API was slow.  
**Fix:** Remove the guard — always render with MOCK fallback if API fails.

### Dashboard clock shows wrong time
**Cause:** IST calculation was `new Date(now.getTime() + (5.5 * 60 - offset) * 60 * 1000)` which adds 11 hours for IST browsers.  
**Fix:** Use `new Date(now.getTime() + (now.getTimezoneOffset() + 330) * 60 * 1000)`.

### News shows "undefined" and wrong times
**Cause:** API returns ISO datetime strings (`2026-08-02T17:00:00-04:00`) but dashboard expected separate `date` + `time` fields.  
**Fix:** Parse ISO dates with `new Date()` and format to IST using `toLocaleTimeString('en-GB', { timeZone: 'Asia/Kolkata' })`.

### API timeout on first load
**Cause:** 12-second fetch timeout is too short for Render cold-start + snapshot build.  
**Fix:** Increase to 30 seconds.

---

## Data Storage

All data is stored as JSON files in `/workspace/` (Render persistent disk):

| File | Contents |
|------|----------|
| `accounts.json` | Account balances & daily trade counters |
| `active_trades.json` | Currently open trades |
| `trade_history.json` | Closed trades with P/L |
| `sent_signals.json` | Deduplication cache for signals |
| `pending_sweeps.json` | Sweep setups waiting for FVG |
| `muted_assets.json` | User-muted symbols |

---

## Strategies

### Strategy 1: Sweep + Engulfing (4H / 1H)
- Detects sweep candles on 4H (forex/gold) or 1H (Nifty)
- Registers pending setup
- Monitors 1H for Fair Value Gap (FVG) formation
- Enters trade when price fills the FVG zone
- SL at sweep extreme, TP at 2R

### Strategy 2: UT Bot Signals (15m)
- Uses ATR-based trailing stop (UT Bot logic)
- Confirms with 5m EMA50 and 15m RSI
- Enters on trend reversal signals
- SL/TP calculated from ATR multiples

---

## License

MIT
