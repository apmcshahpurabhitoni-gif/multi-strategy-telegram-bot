import os
import threading
import time
import io
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pandas as pd
import yfinance as yf
import mplfinance as mpf

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT VARIABLES
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
PORT = int(os.environ.get("PORT", 10000))

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)

# Track muted assets in-memory
muted_assets = set()

# Supported Assets Checklist
ASSETS = {
    "BTC-USD": "Crypto",
    "GC=F": "Gold",
    "EURUSD=X": "Forex",
    "GBPUSD=X": "Forex",
    "AUDUSD=X": "Forex",
    "USDJPY=X": "Forex",
    "NZDUSD=X": "Forex",
    "^NSEI": "NIFTY 50",
    "^NSEBANK": "BANK NIFTY"
}

# ==========================================
# 2. FLASK SERVER ENDPOINTS (FOR CRON-JOB)
# ==========================================
@app.route('/', methods=['GET'])
def home():
    """Main dashboard endpoint."""
    return "Trading Bot Server is Running Live!", 200

@app.route('/ping', methods=['GET'])
def ping():
    """
    Lightweight health-check endpoint.
    Returns 'OK' (2 bytes) to ensure cron-job.org stays strictly 
    under its 64 KB response limit while keeping Render awake 24/7.
    """
    return "OK", 200

# ==========================================
# 3. CHART GENERATION HELPER
# ==========================================
def generate_chart_image(ticker, df):
    """Generates a candlestick chart and returns it as a BytesIO image buffer."""
    df_chart = df.tail(30).copy()
    
    # Custom dark styling
    mc = mpf.make_marketcolors(up='g', down='r', edge='inherit', wick='inherit', volume='in')
    s  = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
    
    buf = io.BytesIO()
    mpf.plot(
        df_chart,
        type='candle',
        style=s,
        title=f"\n{ticker} - Candlestick View",
        ylabel='Price',
        savefig=dict(fname=buf, dpi=100, pad_inches=0.25, format='png')
    )
    buf.seek(0)
    return buf

# ==========================================
# 4. TELEGRAM BOT HANDLERS & INTERACTIVITY
# ==========================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 *Multi-Strategy Trading Bot Active*\n\n"
        "• *Strategy 1:* Sweep + Engulfing (4H / 1H)\n"
        "• *Strategy 2:* UT Bot Signals (15m / 5m)\n\n"
        "Use the buttons below or commands:\n"
        "• `/check` - Run market scan immediately\n"
        "• `/summary` - Get quick asset status"
    )
    
    # Inline interactive panel
    markup = InlineKeyboardMarkup()
    btn_check = InlineKeyboardButton("🔍 Check Markets Now", callback_data="run_check")
    btn_summary = InlineKeyboardButton("📊 Get Summary", callback_data="run_summary")
    markup.add(btn_check, btn_summary)
    
    bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['check'])
def handle_check(message):
    bot.reply_to(message, "🔍 Scanning all assets across strategies...")
    scan_markets(chat_id=message.chat.id)

@bot.message_handler(commands=['summary'])
def handle_summary(message):
    summary_msg = "📊 *Market Summary Snapshot*\n\n"
    for symbol, category in ASSETS.items():
        status = "🔇 Muted" if symbol in muted_assets else "🟢 Active"
        summary_msg += f"• *{symbol}* ({category}): {status}\n"
    bot.reply_to(message, summary_msg, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if call.data == "run_check":
        bot.answer_callback_query(call.id, "Starting market scan...")
        scan_markets(chat_id=call.message.chat.id)
    elif call.data == "run_summary":
        bot.answer_callback_query(call.id, "Generating summary...")
        handle_summary(call.message)
    elif call.data.startswith("chart_"):
        symbol = call.data.replace("chart_", "")
        bot.answer_callback_query(call.id, f"Fetching chart for {symbol}...")
        send_chart_to_chat(call.message.chat.id, symbol)
    elif call.data.startswith("mute_"):
        symbol = call.data.replace("mute_", "")
        muted_assets.add(symbol)
        bot.answer_callback_query(call.id, f"Muted alerts for {symbol}")
        bot.send_message(call.message.chat.id, f"🔇 Alerts for *{symbol}* have been muted.", parse_mode="Markdown")

def send_chart_to_chat(chat_id, symbol):
    """Fetches historical price data and uploads candlestick chart photo to Telegram."""
    try:
        data = yf.download(symbol, period="5d", interval="1h", progress=False)
        if not data.empty:
            chart_buffer = generate_chart_image(symbol, data)
            bot.send_photo(chat_id, photo=chart_buffer, caption=f"📈 *{symbol}* 1-Hour Candlestick Snapshot", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, f"⚠️ Unable to retrieve chart data for {symbol}.")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error generating chart: {str(e)}")

def scan_markets(chat_id=None):
    """Core market scanner for strategies."""
    for symbol in ASSETS.keys():
        if symbol in muted_assets:
            continue
            
        try:
            # Download recent data for analysis
            df = yf.download(symbol, period="5d", interval="15m", progress=False)
            if df.empty:
                continue

            # --- Mock Signal Evaluation Logic ---
            # Replace/expand with actual Sweep + Engulfing or UT Bot condition evaluation
            latest_close = float(df['Close'].iloc[-1])
            prev_close = float(df['Close'].iloc[-2])
            
            # Example trigger condition
            if latest_close > prev_close * 1.002:  # Example 0.2% jump
                alert_text = (
                    f"🚨 *SIGNAL ALERT: {symbol}*\n"
                    f"• *Type:* UT Bot / Sweep Trigger\n"
                    f"• *Current Price:* `{latest_close:.4f}`\n"
                    f"• *Status:* Bullish momentum detected"
                )
                
                # Interactive buttons attached to alert
                markup = InlineKeyboardMarkup()
                btn_chart = InlineKeyboardButton("📈 View Chart", callback_data=f"chart_{symbol}")
                btn_mute = InlineKeyboardButton("🔇 Mute Asset", callback_data=f"mute_{symbol}")
                markup.add(btn_chart, btn_mute)

                if chat_id:
                    bot.send_message(chat_id, alert_text, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            print(f"Error scanning {symbol}: {e}")

# ==========================================
# 5. BACKGROUND BOT THREAD & RUNNER
# ==========================================
def run_telebot():
    """Runs Telegram polling continuously in a background thread."""
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            print(f"Bot polling error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    # Start Telegram polling thread
    bot_thread = threading.Thread(target=run_telebot, daemon=True)
    bot_thread.start()
    
    # Run Flask Web Server
    app.run(host='0.0.0.0', port=PORT)
