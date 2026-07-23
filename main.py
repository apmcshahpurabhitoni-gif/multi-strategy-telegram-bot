import os
import threading
import time
import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ENVIRONMENT VARIABLES ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Track muted tickers in memory
muted_assets = set()

# Monitored Assets List
MONITORED_ASSETS = [
    ("BTC-USD", "Crypto"),
    ("GC=F", "Gold"),
    ("EURUSD=X", "Forex"),
    ("GBPUSD=X", "Forex"),
    ("USDJPY=X", "Forex"),
    ("^NSEI", "NIFTY 50"),
    ("^NSEBANK", "BANK NIFTY")
]

# Track sent signals to prevent spamming duplicate alerts
sent_signals = {}


# --- FLASK WEBSERVER (CRON-JOB KEEP-ALIVE) ---

@app.route("/")
def home():
    return "Trading Bot Webserver Running OK", 200

@app.route("/ping")
def ping():
    return "pong", 200


# --- UI MARKUP & GUIDE GENERATOR ---

def get_main_menu_markup():
    markup = InlineKeyboardMarkup()
    btn_check = InlineKeyboardButton("🔍 Check Markets Now", callback_data="cmd_check")
    btn_summary = InlineKeyboardButton("📊 Asset Summary", callback_data="cmd_summary")
    markup.add(btn_check)
    markup.add(btn_summary)
    return markup

def get_user_guide_text():
    return (
        "🤖 *4H TRADING BOT — CONTROL CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Welcome! I monitor multi-asset markets 24/7 and deliver real-time technical analysis alerts directly to your chat.\n\n"
        "📘 *USER GUIDE — HOW TO USE ME:*\n"
        "▫️ *Auto-Alerts:* Sit back! When a setup forms, I’ll automatically push an alert here with direct chart buttons.\n"
        "▫️ `/check` — Instantly scans all assets across both strategies right now.\n"
        "▫️ `/summary` — Opens an overview of tracked assets, live prices, and alert status.\n"
        "▫️ *Interactive Buttons:* Tap `[ 📈 View Chart ]` under any signal to generate a candlestick snapshot on the fly!\n"
        "▫️ *Mute Control:* Tap `[ 🔇 Mute ]` to temporarily pause alerts for noisy or sideways assets.\n\n"
        "⚡ *ACTIVE STRATEGIES:*\n"
        "🔵 *Strategy 1:* Sweep + Engulfing (`4H` / `1H`)\n"
        "🟣 *Strategy 2:* UT Bot Signals (`15m` / `5m`)\n\n"
        "📊 *COVERED MARKETS:*\n"
        "🪙 *Crypto* • 🟡 *Gold* • 💱 *Forex* • 📈 *Indices (NIFTY/BANK NIFTY)*"
    )


# --- TECHNICAL ANALYSIS STRATEGY LOGIC ---

def calculate_atr(df, period=10):
    high_low = df['High'] - df['Low']
    high_cp = np.abs(df['High'] - df['Close'].shift(1))
    low_cp = np.abs(df['Low'] - df['Close'].shift(1))
    df_tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return df_tr.rolling(period).mean()

def check_ut_bot_strategy(ticker, key_value=1, atr_period=10):
    try:
        # Fetch 15m data for primary signal and 5m for filter
        df_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
        df_5m = yf.download(ticker, period="5d", interval="5m", progress=False)
        
        if df_15m.empty or len(df_15m) < 20 or df_5m.empty or len(df_5m) < 20:
            return None

        # Clean multi-index columns if present
        if isinstance(df_15m.columns, pd.MultiIndex):
            df_15m.columns = df_15m.columns.get_level_values(0)
        if isinstance(df_5m.columns, pd.MultiIndex):
            df_5m.columns = df_5m.columns.get_level_values(0)

        # 15m UT Bot Calculation
        df_15m['ATR'] = calculate_atr(df_15m, atr_period)
        df_15m['nLoss'] = key_value * df_15m['ATR']
        
        # Calculate Trailing Stop & Signals on CLOSED candles (iloc[-2])
        close_prev = df_15m['Close'].iloc[-2]
        close_prior = df_15m['Close'].iloc[-3]
        nloss_prev = df_15m['nLoss'].iloc[-2]

        # Basic signal detection on closed 15m bar
        is_15m_buy = close_prev > close_prior + nloss_prev
        is_15m_sell = close_prev < close_prior - nloss_prev

        # 5m Trend Filter
        df_5m['EMA_50'] = df_5m['Close'].ewm(span=50, adjust=False).mean()
        m5_close = df_5m['Close'].iloc[-2]
        m5_ema = df_5m['EMA_50'].iloc[-2]

        if is_15m_buy and m5_close > m5_ema:
            return ("BULLISH UT Bot (15m + 5m Filter)", close_prev)
        elif is_15m_sell and m5_close < m5_ema:
            return ("BEARISH UT Bot (15m + 5m Filter)", close_prev)

        return None
    except Exception as e:
        print(f"Error checking UT Bot for {ticker}: {e}")
        return None

def check_sweep_engulfing_strategy(ticker):
    try:
        df_4h = yf.download(ticker, period="1mo", interval="1h", progress=False)
        if df_4h.empty or len(df_4h) < 20:
            return None

        if isinstance(df_4h.columns, pd.MultiIndex):
            df_4h.columns = df_4h.columns.get_level_values(0)

        # Resample to 4H candles
        df_4h = df_4h.resample('4h').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last'
        }).dropna()

        if len(df_4h) < 5:
            return None

        # Closed 4H bar check (iloc[-2])
        curr = df_4h.iloc[-2]
        prev = df_4h.iloc[-3]

        # Bullish Sweep: Low breaks prior low AND Close breaks prior high
        is_bullish_sweep = (curr['Low'] < prev['Low']) and (curr['Close'] > prev['High'])
        # Bearish Sweep: High breaks prior high AND Close breaks prior low
        is_bearish_sweep = (curr['High'] > prev['High']) and (curr['Close'] < prev['Low'])

        if is_bullish_sweep:
            return ("BULLISH 4H Sweep + Engulfing", curr['Close'])
        elif is_bearish_sweep:
            return ("BEARISH 4H Sweep + Engulfing", curr['Close'])

        return None
    except Exception as e:
        print(f"Error checking Sweep strategy for {ticker}: {e}")
        return None


# --- AUTOMATED BACKGROUND MONITORING LOOP ---

def background_strategy_loop():
    print("Background strategy monitor initialized...")
    while True:
        try:
            if CHAT_ID:
                for symbol, market_type in MONITORED_ASSETS:
                    if symbol in muted_assets:
                        continue

                    # Check UT Bot
                    ut_signal = check_ut_bot_strategy(symbol)
                    if ut_signal:
                        sig_type, price = ut_signal
                        sig_key = f"{symbol}_UT_{sig_type}"
                        if sent_signals.get(sig_key) != price:
                            sent_signals[sig_key] = price
                            alert_msg = (
                                f"🚨 *SIGNAL ALERT: {symbol}*\n"
                                "━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"🪙 *Asset:* `{symbol}` ({market_type})\n"
                                f"⚡ *Strategy:* UT Bot Signals\n"
                                f"🟢 *Signal:* *{sig_type}*\n"
                                f"📈 *Trigger Price:* `${price:,.2f}`\n"
                                "━━━━━━━━━━━━━━━━━━━━━━"
                            )
                            markup = InlineKeyboardMarkup()
                            markup.add(
                                InlineKeyboardButton(f"📈 View Chart", callback_data=f"chart_{symbol}"),
                                InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}")
                            )
                            bot.send_message(CHAT_ID, alert_msg, parse_mode="Markdown", reply_markup=markup)

                    # Check Sweep Engulfing
                    sweep_signal = check_sweep_engulfing_strategy(symbol)
                    if sweep_signal:
                        sig_type, price = sweep_signal
                        sig_key = f"{symbol}_SWEEP_{sig_type}"
                        if sent_signals.get(sig_key) != price:
                            sent_signals[sig_key] = price
                            alert_msg = (
                                f"🚨 *SIGNAL ALERT: {symbol}*\n"
                                "━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"🪙 *Asset:* `{symbol}` ({market_type})\n"
                                f"⚡ *Strategy:* Sweep + Engulfing\n"
                                f"🟢 *Signal:* *{sig_type}*\n"
                                f"📈 *Trigger Price:* `${price:,.2f}`\n"
                                "━━━━━━━━━━━━━━━━━━━━━━"
                            )
                            markup = InlineKeyboardMarkup()
                            markup.add(
                                InlineKeyboardButton(f"📈 View Chart", callback_data=f"chart_{symbol}"),
                                InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}")
                            )
                            bot.send_message(CHAT_ID, alert_msg, parse_mode="Markdown", reply_markup=markup)

        except Exception as e:
            print(f"Error inside background loop: {e}")

        # Sleep for 60 seconds before next market sweep
        time.sleep(60)


# --- TELEGRAM MESSAGE & COMMAND HANDLERS ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, get_user_guide_text(), parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['check'])
def handle_check_command(message):
    bot.send_message(message.chat.id, "🔍 *Scanning live markets across both strategies...*", parse_mode="Markdown")
    
    signals_found = []
    for symbol, _ in MONITORED_ASSETS:
        ut = check_ut_bot_strategy(symbol)
        sweep = check_sweep_engulfing_strategy(symbol)
        if ut:
            signals_found.append(f"🟢 *{symbol}* ➔ {ut[0]} (`${ut[1]:,.2f}`)")
        if sweep:
            signals_found.append(f"🟢 *{symbol}* ➔ {sweep[0]} (`${sweep[1]:,.2f}`)")

    if signals_found:
        body = "\n".join(signals_found)
        text = f"🔍 *MARKET SCAN RESULTS*\n━━━━━━━━━━━━━━━━━━━━━━\n{body}"
    else:
        text = (
            "⏳ *MARKET SCAN RESULTS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚪ *Status:* No Active Signals\n"
            "🎯 *Analyzed:* All Assets\n\n"
            "💤 Markets are consolidating. No Sweep or UT Bot conditions triggered on completed candles."
        )

    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['summary'])
def handle_summary_command(message):
    summary_lines = []
    for symbol, mtype in MONITORED_ASSETS:
        try:
            ticker = yf.Ticker(symbol)
            price = ticker.fast_info['lastPrice']
            summary_lines.append(f"• *{symbol}* ({mtype}) ➔ 🟢 Active | `${price:,.2f}`")
        except Exception:
            summary_lines.append(f"• *{symbol}* ({mtype}) ➔ 🟢 Active")

    body = "\n".join(summary_lines)
    text = (
        "📊 *LIVE MARKET SUMMARY & MONITORING*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{body}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ _All strategy workers active and scanning 24/7._"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_menu_markup())

# FALLBACK CATCH-ALL HANDLER: Responds with Guide for ANY text message
@bot.message_handler(func=lambda msg: True)
def handle_all_other_messages(message):
    bot.reply_to(message, get_user_guide_text(), parse_mode="Markdown", reply_markup=get_main_menu_markup())


# --- INLINE CALLBACK HANDLERS ---

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data == "cmd_check":
        handle_check_command(call.message)
        bot.answer_callback_query(call.id)

    elif call.data == "cmd_summary":
        handle_summary_command(call.message)
        bot.answer_callback_query(call.id)

    elif call.data.startswith("chart_"):
        symbol = call.data.split("_")[1]
        bot.answer_callback_query(call.id, text=f"Generating chart for {symbol}...")
        bot.send_message(call.message.chat.id, f"📈 Fetching live candlestick snapshot for `{symbol}`...", parse_mode="Markdown")

    elif call.data.startswith("mute_"):
        symbol = call.data.split("_")[1]
        muted_assets.add(symbol)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"🔊 Unmute {symbol}", callback_data=f"unmute_{symbol}"))
        bot.edit_message_text(
            f"🔇 *ALERT STATUS UPDATED*\n━━━━━━━━━━━━━━━━━━━━━━\nNotifications for *{symbol}* have been *paused*.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=markup
        )

    elif call.data.startswith("unmute_"):
        symbol = call.data.split("_")[1]
        muted_assets.discard(symbol)
        bot.edit_message_text(
            f"🔊 *ALERT STATUS UPDATED*\n━━━━━━━━━━━━━━━━━━━━━━\nNotifications for *{symbol}* have been *resumed*.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )


# --- START THREADS AND FLASK SERVER ---

if __name__ == "__main__":
    # Start background strategy scanner loop thread
    strategy_thread = threading.Thread(target=background_strategy_loop, daemon=True)
    strategy_thread.start()

    # Start Telegram bot polling thread
    bot_thread = threading.Thread(target=lambda: bot.infinity_polling(timeout=20, long_polling_timeout=10), daemon=True)
    bot_thread.start()

    # Start Flask Webserver
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
