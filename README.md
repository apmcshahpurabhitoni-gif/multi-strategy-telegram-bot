🤖 Multi-Strategy Trading Bot & Dashboard


⚡ A high-confluence paper trading system that operates seamlessly via Telegram and features a live Web Dashboard. Built from the ground up to survive Yahoo Finance rate-limits and run efficiently on serverless free tiers (512MB RAM).

✨ Key Features
🧠 Dual Strategy Engine: Structural price action (Sweep & Engulfing) combined with algorithmic trailing stops (UT Bot Alerts).
🌐 Live Web Dashboard & REST API: Track balances, view active trades, and download CSV exports via a clean web interface.
⏱️ Smart Market Scheduling: Ignores closed markets automatically (Nifty sleeps at night, Forex sleeps on weekends).
🏦 Segmented Virtual Accounts: Isolates paper trading into 4 distinct accounts to track alpha by session.
🛡️ Aggressive Rate Limiting: Custom circuit-breakers and backoff algorithms prevent Yahoo Finance IP bans.
📈 Interactive Telegram UI: On-demand chart generation, inline mute buttons, and manual trade closing.
🖥️ Web Dashboard & API
Unlike standard Telegram bots, this system runs a lightweight Flask server exposing a live dashboard and REST API for external integrations.

Endpoint	Method	Description
/dashboard	GET	Visual web interface for the bot
/api/balance	GET	JSON payload of all 4 account balances & limits
/api/active	GET	List of all currently open paper trades
/api/history	GET	Last 50 closed trades
/api/export	GET	Download the full trade_log.csv
/api/close/<SYMBOL>	POST	Manually close a specific trade via API
/api/clear	POST	Wipe all data and reset accounts
⏱️ Smart Market Scheduling
The bot strictly adheres to real market hours to prevent false signals and optimize API usage:

Asset Class	Symbols	Schedule (IST)
🪙 Crypto & Gold	BTC-USD, GC=F	24/7
💱 Forex	EURUSD=X, GBPUSD=X, USDJPY=X	Monday – Friday
📈 Indian Indices	^NSEI, ^NSEBANK	Mon – Fri (09:15 AM – 03:30 PM)
🎯 Trading Strategies
🔵 Strategy 1: Sweep & Engulfing (4H / 1H)
Identifies market manipulation and reversals.

Logic: Detects when price "sweeps" a previous high/low to trap traders, then aggressively reverses and engulfs the range.
Risk/Reward: Strict 1:2 Ratio.
Routing: Routes to SWEEP_4H account.
🟣 Strategy 2: UT Bot Alerts (15m + 5m EMA)
Identifies trend continuations using an ATR-based trailing stop algorithm.

Logic: Buys/Sells on the exact crossover of the UT Bot trailing stop, confirmed by a 50 EMA filter on the 5m chart and RSI.
Risk/Reward: 1:2 Ratio (1.5x ATR SL, 3x ATR TP).
Routing: Routes to NY_SESSION or MACRO depending on time of day.
🏦 Virtual Account System
The bot splits your virtual ₹1,00,000 into 4 isolated accounts:

🏢 Macro Account (20 trades/day): Default bucket for global assets.
🇮🇳 Nifty Account (3 trades/day): Dedicated to Indian Indices.
🗽 NY Session Account (3 trades/day): Activates during US market hours (8:00 PM - 2:30 AM IST).
🌊 Sweep 4H Account (3 trades/day): Dedicated strictly to the 4H Sweep strategy.
Note: All accounts feature a dynamic 0.5% trailing stop-loss that activates at 1.5% profit.

📜 Telegram Commands
Command	Description
/check	Force an immediate scan of all open markets
/summary	Get a live price list of all 7 monitored assets
/active	View open positions with live Unrealized P/L
/close SYMBOL	Manually close a specific trade (e.g., /close BTC-USD)
/stats	View win rate, W/L ratio, and net P/L per account
/balance	Check balances, daily limits, and U.PnL
/export	Download the trade history as a CSV file
/clear	🗑️ Wipe all data and reset balances to ₹1,00,000
/indi1	Force run Strategy 1 (Sweep) diagnostics
/indi2	Force run Strategy 2 (UT Bot) diagnostics
🛠️ Setup & Installation
1. Prerequisites
Python 3.9+
A Telegram Bot Token (@BotFather)
Your Telegram Chat ID (@userinfobot)
2. Clone & Configure
git clone https://github.com/apmcshahpurabhitoni-gif/multi-strategy-telegram-bot.gitcd multi-strategy-telegram-bot
Create a .env file in the root directory:

env

TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
PUSHBULLET_TOKEN=your_pushbullet_token_here  # Optional
3. Run Locally
bash

pip install -r requirements.txt
python main.py
Access the dashboard at: http://localhost:10000/dashboard

☁️ Deploying to Render (Free Tier)
This bot is heavily optimized for Render's 512MB RAM free tier.

Includes an exponential backoff circuit-breaker to survive Yahoo Finance rate limits.
Aggressively manages memory (gc.collect()) and uses minimal Pandas/Numpy footprints.
Uses relative ./data/ paths to safely persist state across Render restarts.
Create a new Web Service on Render and link your GitHub repo.
Add the environment variables listed above.
Render will automatically detect requirements.txt and start the service via Gunicorn.
Your dashboard will be live at https://your-app-name.onrender.com/dashboard.
⚙️ Environment Variables
Variable
Required
Description
TELEGRAM_BOT_TOKEN	✅	Token from Telegram BotFather
TELEGRAM_CHAT_ID	✅	Your personal/group Telegram chat ID
PUSHBULLET_TOKEN	❌	Optional: Sends push notifications to your phone
PORT	❌	Auto-set by Render, defaults to 10000 locally

⚠️ Disclaimer
This is a PAPER TRADING bot.
It does not execute real trades or connect to any exchange APIs. It is designed strictly for educational purposes, real-time strategy backtesting, and signal analysis. Do not use the generated signals as direct financial advice. Always do your own research (DYOR).

<p align="center">
Built with 💼, 🐍, and ☕ by <a href="https://github.com/apmcshahpurabhitoni-gif">apmcshahpurabhitoni-gif</a>
</p>
```
