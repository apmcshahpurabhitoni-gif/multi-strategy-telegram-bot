# 🤖 Multi-Strategy 2-Way Interactive Trading Bot

An automated trading bot hosted on **Render** that scans financial markets 24/7 and sends real-time signals to Telegram. It features interactive 2-way Telegram messaging, market diagnostics, and custom visual alerts.

---

## 📈 Active Trading Strategies

1. **Strategy 1: Sweep + Engulfing (4H / 1H)**
   - Monitors liquidity sweeps followed by strong engulfing candles.
   - **Assets:** BTC/USDT (4H), Gold (4H), NIFTY 50 (1H), BANK NIFTY (1H).

2. **Strategy 2: UT Bot ATR Trailing Stop (15m / 1H)**
   - Uses Heikin Ashi candles and ATR trailing stops to trigger buy/sell crossovers.
   - **Assets:** Bitcoin (15m & 1H), Gold (15m & 1H).

---

## 💬 Interactive Telegram Commands

| Command | Action |
| :--- | :--- |
| `hi` / `hello` | Verifies bot connectivity and displays the interactive menu |
| `/check` | Runs an instant manual scan across both strategies |
| `/status` | Tests all Yahoo Finance market data feeds and prints system diagnostics |

---

## ⚙️ Deployment Settings (Render Web Service)

- **Runtime:** `Python 3`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python main.py` (or `python signal_bot.py`)
- **Environment Variables:**
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
