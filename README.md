# 🤖 Multi-Strategy 2-Way Interactive Trading Bot

> Automated trading signals scanner with Telegram integration. Monitors crypto, forex, gold, and Indian markets — sends real-time alerts directly to your phone.

---

## 📈 Strategies

### Strategy 1 — Sweep + Engulfing (4H / 1H)
Detects liquidity sweeps followed by strong engulfing candles. Used on BTC, Gold, NIFTY 50, and BANK NIFTY.

### Strategy 2 — UT Bot ATR Trailing Stop (15m)
Heikin Ashi candles with ATR trailing stop crossovers, filtered by 5m EMA and 15m RSI. Used on BTC, Gold, and forex pairs.

---

## 💬 Telegram Commands

| Command | What it does |
|---|---|
| `/start` | Show command menu |
| `/check` | Scan all assets right now |
| `/summary` | Live prices for all monitored assets |
| `/stats` | Win rate and P/L report |
| `/balance` | Virtual account balances |
| `/clear` | Reset everything to ₹1,00,000 |
| `/indi1` | Diagnose Strategy 1 signals |
| `/indi2` | Diagnose Strategy 2 signals |

---

## 📊 Monitored Markets

| Asset | Ticker | Schedule |
|---|---|---|
| 🪙 Bitcoin | BTC-USD | 24/7 |
| 🟡 Gold | GC=F | 24/7 |
| 💱 EUR/USD | EURUSD=X | Mon–Fri |
| 💱 GBP/USD | GBPUSD=X | Mon–Fri |
| 💱 USD/JPY | USDJPY=X | Mon–Fri |
| 📈 NIFTY 50 | ^NSEI | Mon–Fri, 09:15–15:30 IST |
| 📈 BANK NIFTY | ^NSEBANK | Mon–Fri, 09:15–15:30 IST |

> Markets are skipped automatically when closed. No noise on weekends.

---

## ⚙️ Setup

### 1. Clone the repo
```bash
git clone https://github.com/apmcshahpurabhitoni-gif/multi-strategy-telegram-bot.git
cd multi-strategy-telegram-bot
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set environment variables

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token_from_botfather"
export TELEGRAM_CHAT_ID="your_chat_id"
```

Get your bot token from [@BotFather](https://t.me/BotFather) on Telegram.

Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot).

### 4. Run
```bash
python main.py
```

---

## 🚀 Deploy on Render (Free Tier)

- **Runtime:** Python 3
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python main.py`
- **Port:** `10000`
- **Environment Variables:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

---

## 📂 Project Structure

```
multi-strategy-telegram-bot/
├── main.py          # Everything — bot, strategies, scanner, handlers
└── requirements.txt # Dependencies
```

---

## ⚠️ Disclaimer

This bot runs **paper trades only**. It does not execute real trades on any exchange. Use it for educational and signal purposes only. Trading involves risk — always do your own research.
