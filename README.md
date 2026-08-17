# 🤖 Mavis Trading Bot

> **Multi-strategy paper trading bot** with real-time Telegram alerts, web dashboard, and automated risk management.  
> Built for **Gold (XAU/USD)**, **Bitcoin (BTC/USD)**, **Forex**, and **NSE stocks**.

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![Deploy](https://img.shields.io/badge/Deploy-Render-green)](https://render.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 🎯 What It Does

| Feature | Description |
|---------|-------------|
| 📊 **TrendPulse 1H** | Multi-timeframe momentum strategy (4H trend + 1H MACD/RSI entry) |
| 🧹 **4H Sweep + FVG** | Smart Money Concepts — liquidity sweep detection with Fair Value Gap fills |
| 📡 **Telegram Alerts** | Instant signal, entry, exit, and news notifications |
| 🌐 **Web Dashboard** | Live trades (with one-tap force close), balances, P&L, strategy stats, R-multiples, and equity charts |
| 📰 **Economic Calendar** | Auto-fetches high-impact news + 30-min pre-release warnings |
| 💰 **4 Virtual Accounts** | Macro, Nifty, NY Session, Sweep 4H — each with independent risk |
| 🛡️ **Risk Management** | 2% risk per trade, trailing stops, max drawdown tracking |

---

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/yourusername/mavis-trading-bot.git
cd mavis-trading-bot
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHAT_ID=your_telegram_user_id
WEBHOOK_URL=https://your-app.onrender.com/webhook
# Optional:
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
```

### 3. Run Locally

```bash
python main.py
```

### 4. Deploy to Render

| Setting | Value |
|---------|-------|
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python main.py` |
| **Health Check** | `/ping` → `pong` |

> 💡 **Keep Alive:** Free tier sleeps after 15 min. Use [cron-job.org](https://cron-job.org) to ping `/ping` every 10 minutes.

---

## 📈 Strategies

### Strategy 1: TrendPulse 1H ⭐ (Primary)

**Replaces the old UT Bot** with a well-researched, non-repainting system.

```
4H Trend Filter:    Close > EMA(50) → Only LONGs
                    Close < EMA(50) → Only SHORTs

Volatility Guard:   ATR(14)/Close > 0.05% (Crypto)
                    ATR(14)/Close > 0.03% (Gold/Forex)
                    → Skip if too flat (chop)

1H Entry:           MACD line crosses Signal line
                    AND RSI(14) > 50 (LONG) / < 50 (SHORT)
                    AND Close > EMA(20) (LONG) / < EMA(20) (SHORT)

Exit:               MACD crosses opposite direction on 1H
SL:                 Entry ± 1.5 × ATR(14)
TP:                 Entry ± 3.0 × ATR(14)
```

**Why it wins:**
- ✅ No repainting (uses confirmed closed candles)
- ✅ Trend-aligned (filters counter-trend trades)
- ✅ Chop-filtered (skips low-volatility periods)
- ✅ Tight stops (0.6% Gold, 1.2% BTC)
- ✅ Research-backed (Sharpe ~1.07 in literature)

### Strategy 2: 4H Sweep + FVG

**Smart Money Concepts** for NSE stocks and forex.

```
Sweep:      4H candle breaks previous high AND low (liquidity grab)
FVG:        Wait for 1H Fair Value Gap to form
Entry:      Price enters FVG zone
SL:         Sweep extreme
TP:         2× risk
Expiry:     24 hours if no fill
```

---

## 🌐 Web Dashboard

Open `/dashboard` on your deployed URL. Six tabs:

| Tab | What You Get |
|-----|--------------|
| 🏠 **Overview** | Account balances, equity curve, exposure/risk/max drawdown, **Strategy Performance** (win rate, W/L, avg P/L per strategy), **Open Trade Risk** (per-trade R-multiples), quick status, last-updated timestamp |
| 🔥 **Trades** | Live open trades with entry/current price, live P/L (₹), progress to TP, market, opened time, and a **Close button** (force-closes at market via `/api/close-trade`) + pending sweep setups with FVG zones and expiry |
| 📡 **Signals** | Last 24h signals grouped by day, with strategy, status, and running P/L |
| 📜 **History** | Closed trades grouped by day with daily totals and W/L — badge shows "15 of N" total |
| 📈 **Nifty** | Nifty 50 + Bank Nifty and 15 NSE stocks (lazy-loaded, error state with retry) |
| 📰 **News** | Economic calendar grouped by day with ET → IST times and impact tags |
| 🧪 **Backtest** | Run **TrendPulse 1H** or **4H Sweep + FVG** on any symbol over 30–180 days — win rate, profit factor, Sharpe, max drawdown, and a full trade list |

**API endpoints:** `/api/dashboard` (snapshot), `/api/prices?symbols=...`, `/api/close-trade` (POST), `/api/backtest?symbol=BTC-USD&strategy=trendpulse&days=60`, `/api/health`

---

## 🤖 Telegram Commands

| Command | What It Does |
|---------|-------------|
| `/start` | Show guide + control menu |
| `/menu` | Inline button dashboard |
| `/check` | Scan all assets now |
| `/test` | Test data feeds (debug) |
| `/summary` | Live prices & status |
| `/stats` | Win rate & P/L per account |
| `/balance` | Virtual account balances |
| `/indi1` | Diagnose Strategy 1 (Sweep) |
| `/indi2` | Diagnose Strategy 2 (TrendPulse) |
| `/pending` | Pending sweep setups |
| `/risk` | Exposure & R-multiples |
| `/weekly` | Weekly performance digest |
| `/news` | Economic calendar |
| `/nifty` | Nifty 50 stock prices |
| `/clear` | Reset everything to ₹1,00,000 |

---

## 🏦 Account Structure

| Account | Assets | Balance | Daily Limit |
|---------|--------|---------|-------------|
| **Macro** | BTC, Gold, Forex | ₹1,00,000 | 20 trades |
| **NY Session** | Same (18:00–01:30 IST) | ₹1,00,000 | 3 trades |
| **Nifty** | NSE stocks, indices | ₹1,00,000 | 5 trades |
| **Sweep 4H** | Non-NSE sweeps | ₹1,00,000 | 3 trades |

**Risk per trade:** 2% of account balance  
**Trailing stops:** Breakeven at +1%, lock 30% at +3%, lock 50% at +5%

---

## 📊 Monitored Assets

| Asset | Type | Market Hours (IST) |
|-------|------|-------------------|
| BTC-USD | Crypto | 24/7 |
| GC=F (Gold) | Commodity | 24/7 |
| EURUSD=X | Forex | Sun 15:00 – Fri 23:30 |
| GBPUSD=X | Forex | Sun 15:00 – Fri 23:30 |
| USDJPY=X | Forex | Sun 15:00 – Fri 23:30 |
| ^NSEI | Index | Mon–Fri 09:15–15:30 |
| ^NSEBANK | Index | Mon–Fri 09:15–15:30 |
| 15 NSE Stocks | Equities | Mon–Fri 09:15–15:30 |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.12 |
| **Data** | yfinance, CoinGecko API, Binance API |
| **Analysis** | pandas, numpy |
| **Bot** | pyTelegramBotAPI |
| **Charts** | matplotlib |
| **Web** | WSGI (built-in) |
| **Storage** | JSON files + Supabase (optional) |
| **Deploy** | Render (Web Service) |

---

## 📁 Project Structure

```
mavis-trading-bot/
├── main.py                 # Core bot (2,064 lines)
├── dashboard_api.py        # Web dashboard routes
├── requirements.txt        # Dependencies
├── .env                    # Environment variables (gitignored)
├── README.md               # This file
└── DOCUMENTATION.md        # Full technical docs
```

---

## ⚠️ Known Issues & Fixes

### Yahoo Finance Blocks Render
**Problem:** Yahoo blocks cloud IPs → prices show ₹0  
**Fixes applied:**
- BTC → CoinGecko API + Binance klines fallback
- Gold → GC=F → GLD → IAU fallback chain
- Still failing? Run on VPS with residential IP

### Free Tier Sleeps
**Problem:** Render free tier sleeps after 15 min idle  
**Fix:** Use cron-job.org to ping `/ping` every 10 minutes

### Webhook 409 Conflict
**Problem:** Multiple instances or polling + webhook clash  
**Fix:** Set `WEBHOOK_URL` env var, restart service

---

## 📚 Research References

| Strategy | Source | Metrics |
|----------|--------|---------|
| Multi-Timeframe MACD | Published quant research | Sharpe 1.07, Calmar 0.87 |
| Donchian Breakout | arxum.com / Turtle Traders | PF 5.58, Max DD -5.9% |
| Dual Momentum | Quantpedia / Antonacci GEM | 12.01% CAGR, 1.37 Sharpe |
| Smart Money Concepts | ICT (Inner Circle Trader) | Liquidity sweep + FVG |

---

## 📝 License

MIT License — free to use, modify, and deploy.

---

## 🙏 Credits

- **TrendPulse strategy** based on multi-timeframe MACD research
- **Sweep + FVG** based on Smart Money Concepts
- **Price fallbacks** engineered for Render deployment
- Built with ❤️ for traders who want automation without the BS

---

> **⚡ Pro Tip:** Start with `/test` after deploy to verify data feeds, then `/indi2` to see TrendPulse scanning live markets.
