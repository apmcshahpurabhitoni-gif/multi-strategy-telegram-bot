🤖 Multi-Strategy Telegram Trading Bot
<p align="center">
<img src="https://img.shields.io/badge/Python-3.8+-blue.svg" />
<img src="https://img.shields.io/badge/Telegram-Bot-32AFED?logo=telegram" />
<img src="https://img.shields.io/badge/Status-Paper_Trading-success" />
</p>

⚡ An automated, high-confluence paper trading bot that runs directly inside Telegram. It scans Crypto, Forex, Gold, and Indian Indices using dual algorithmic strategies, executing virtual trades with precise risk management and dynamic trailing stop-losses.

✨ Key Features
🧠 Dual Strategy Engine: Combines structural price action (Sweep & Engulfing) with algorithmic trailing stops (UT Bot Alerts).
⏱️ Smart Market Scheduling: Automatically skips closed markets silently (e.g., ignores Nifty at night, ignores Forex on weekends).
🏦 Segmented Virtual Accounts: Isolates paper trading balances into Macro, Nifty, and NY Session accounts to track performance accurately.
🛡️ Dynamic Risk Management: Auto-calculates position sizing (2% risk per trade) and activates a 0.5% trailing stop-loss once in profit.
📈 Interactive Telegram UI: Beautifully formatted messages, inline mute buttons, and on-demand chart generation.
⏱️ Smart Market Scheduling
The bot intelligently manages API usage and prevents false signals by strictly adhering to market hours:

Asset Class
Symbols
Schedule (IST)
🪙 Crypto & Gold	BTC-USD, GC=F	24/7
💱 Forex	EURUSD=X, GBPUSD=X, USDJPY=X	Monday – Friday
📈 Indian Indices	^NSEI, ^NSEBANK	Mon – Fri (09:15 AM – 03:30 PM)

🎯 Trading Strategies
🔵 Strategy 1: Sweep & Engulfing (4H / 1H)
Identifies market manipulation and reversals.

Logic: Detects when price "sweeps" above/below a previous candle's high/low to trap traders, then aggressively reverses and engulfs the range.
Risk/Reward: Strict 1:2 Ratio.
Timeframe: 4H for Global assets, 1H for Nifty.
🟣 Strategy 2: UT Bot Alerts (15m + 5m EMA)
Identifies trend continuations using an ATR-based trailing stop algorithm.

Logic: Buys/Sells on the exact crossover of the UT Bot trailing stop line, confirmed by a 50 EMA filter on the 5m chart.
Risk/Reward: 1:2 Ratio (2x ATR Stop Loss, 4x ATR Take Profit).
Timeframe: 15M trigger, 5M confirmation.
🏦 Virtual Account System
The bot splits your virtual ₹1,00,000 into isolated accounts to track where your alpha is coming from:

🌐 Macro Account: Default account for Crypto, Gold, and Forex.
🇮🇳 Nifty Account: Dedicated account for Nifty 50 and Bank Nifty.
🇺🇸 NY Session Account: Activates between 7:00 PM - 1:30 AM IST. Any global signal triggered during this window is routed here to simulate US session overlap trading.
Note: All accounts are restricted to 3 trades per day to prevent overtrading.

📜 Bot Commands
Command
Description
/start or /help	View the command center & main menu
/check	Force an immediate scan of all open markets
/summary	Get a live price list of all monitored assets
/stats	View win rate, W/L ratio, and total P/L per account
/balance	Check virtual account balances and daily trade limits
/clear	🗑️ Wipe all data and reset balances to ₹1,00,000
/indi1	Force run Strategy 1 (Sweep) diagnostics
/indi2	Force run Strategy 2 (UT Bot) diagnostics

🛠️ Setup & Installation
1. Prerequisites
Python 3.8 or higher
A Telegram Bot Token (via @BotFather)
Your Telegram Chat ID (via @userinfobot)
2. Clone & Configure
bash

git clone https://github.com/apmcshahpurabhitoni-gif/multi-strategy-telegram-bot.git
cd multi-strategy-telegram-bot
Create a .env file in the root directory:

env

TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
PUSHBULLET_TOKEN=your_pushbullet_token_here  # Optional
3. Run Locally
bash

pip install -r requirements.txt
python main.py
☁️ Deploying to Render
This bot is optimized for Render free tier. It includes a built-in web server to prevent the instance from spinning down.

Create a new Web Service on Render and link your GitHub repo.
Set the Environment Variables mentioned above in the Render Dashboard.
Render automatically runs pip install -r requirements.txt and starts the app.
Note: The bot uses absolute file paths (/workspace/*.json) to safely store state across Render restarts.
⚙️ Environment Variables
Variable
Required
Description
TELEGRAM_BOT_TOKEN	✅	Token from Telegram BotFather
TELEGRAM_CHAT_ID	✅	Your personal/group Telegram chat ID
PUSHBULLET_TOKEN	❌	Optional: Sends push notifications to your phone

⚠️ Disclaimer
This is a PAPER TRADING bot.
It does not execute real trades or connect to any exchange APIs. It is designed strictly for educational purposes, strategy backtesting in real-time, and signal analysis. Do not use the generated signals as direct financial advice. Always do your own research (DYOR).

<p align="center">
Made with 💼 & 🐍 by <a href="https://github.com/apmcshahpurabhitoni-gif">apmcshahpurabhitoni-gif</a>
</p>
