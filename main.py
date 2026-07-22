"""
Unified 2-Way Interactive Trading Bot (Render Web Service Edition)
===================================================================
Features:
- Strategy 1: Sweep + Engulfing (4H/1H)
- Strategy 2: UT Bot ATR Trailing Stop (15m Signal + 5m Confirmed Filter)
- Forex Pairs Added: AUDUSD, USDJPY, NZDUSD, EURUSD, GBPUSD
- Free Chart Image Snapshot Generation (mplfinance)
- Interactive Mute/Unmute Notifications via Inline Keyboards
- TradingView Webhook Alerts Support (/webhook)
- Daily Market Summary (/summary)
"""

import os
import time
import io
import threading
from datetime import datetime, timezone

from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib
matplotlib.use('Agg') # Non-gui backend
import mplfinance as mpf

# ========== SECRETS ==========
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing!")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)

# State for muted assets
muted_assets = set()

# ========== STRATEGY 1 CONFIG ==========
STRAT1_SYMBOLS = [
    {"name": "BTC / USDT",  "ticker": "BTC-USD",   "tf": "4H"},
    {"name": "Gold (XAU)",  "ticker": "GC=F",      "tf": "4H"},
    {"name": "EUR / USD",   "ticker": "EURUSD=X",  "tf": "1H"},
    {"name": "GBP / USD",   "ticker": "GBPUSD=X",  "tf": "1H"},
    {"name": "AUD / USD",   "ticker": "AUDUSD=X",  "tf": "1H"},
    {"name": "USD / JPY",   "ticker": "JPY=X",     "tf": "1H"},
    {"name": "NZD / USD",   "ticker": "NZDUSD=X",  "tf": "1H"},
    {"name": "NIFTY 50",    "ticker": "^NSEI",     "tf": "1H"},
    {"name": "BANK NIFTY",  "ticker": "^NSEBANK",  "tf": "1H"}
]
strat1_state = {}

# ========== STRATEGY 2 CONFIG ==========
UT_SYMBOLS = {
    "Bitcoin (BTC)": "BTC-USD",
    "Gold (XAU)": "GC=F",
    "EUR / USD": "EURUSD=X",
    "GBP / USD": "GBPUSD=X",
    "AUD / USD": "AUDUSD=X",
    "USD / JPY": "JPY=X",
    "NZD / USD": "NZDUSD=X"
}
SENSITIVITY = 1
ATR_PERIOD = 10
USE_HEIKIN_ASHI = True
ut_bot_state = {}

# ========== CHART GENERATOR (100% FREE) ==========
def generate_chart_image(ticker: str, title: str):
    """Generates a candlestick chart PNG image buffer using yfinance + mplfinance."""
    try:
        df = yf.download(ticker, period="5d", interval="15m", progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Plot candlestick chart
        buf = io.BytesIO()
        mpf.plot(
            df.tail(40),
            type='candle',
            style='charles',
            title=f"\n{title} (15m)",
            volume=False,
            savefig=dict(fname=buf, format='png', dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"Chart generation error ({ticker}): {e}")
        return None

# ========== TELEGRAM UTILITY ==========
def safe_send_message(chat_id, text, reply_markup=None):
    try:
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        clean_text = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "").replace("<code>", "").replace("</code>", "")
        bot.send_message(chat_id, clean_text, reply_markup=reply_markup)

def send_signal_with_chart(chat_id, ticker, title, msg_text, tv_symbol):
    """Sends signal text, inline buttons, and chart screenshot if enabled."""
    if title in muted_assets:
        return # Skip muted asset

    # Build Interactive Keyboards
    markup = InlineKeyboardMarkup()
    tv_url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
    btn_chart = InlineKeyboardButton("📈 View TradingView Chart", url=tv_url)
    btn_mute = InlineKeyboardButton("🛑 Mute Asset Notifications", callback_data=f"mute_{title}")
    markup.add(btn_chart)
    markup.add(btn_mute)

    # Generate Chart Buffer
    chart_buf = generate_chart_image(ticker, title)
    
    try:
        if chart_buf:
            bot.send_photo(chat_id, photo=chart_buf, caption=msg_text, parse_mode="HTML", reply_markup=markup)
        else:
            safe_send_message(chat_id, msg_text, reply_markup=markup)
    except Exception as e:
        print(f"Error sending alert photo: {e}")
        safe_send_message(chat_id, msg_text, reply_markup=markup)

# ========== FLASK ROUTES (TradingView Webhooks) ==========
@app.route('/')
def home():
    return "Unified Trading Bot is active and running!"

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    """Endpoint for TradingView webhook signals."""
    try:
        data = request.json or request.data.decode('utf-8')
        if isinstance(data, dict):
            msg = f"<b>🚨 TRADINGVIEW ALERT</b>\n\n{data.get('message', str(data))}"
        else:
            msg = f"<b>🚨 TRADINGVIEW ALERT</b>\n\n<code>{data}</code>"
        
        if TELEGRAM_CHAT_ID:
            safe_send_message(TELEGRAM_CHAT_ID, msg)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "reason": str(e)}), 400

# ========== STRATEGY 1 LOGIC ==========
def get_s1_ohlcv(ticker: str, target_tf: str):
    try:
        data = yf.download(ticker, period="1mo", interval="60m", progress=False, auto_adjust=True)
        if data.empty:
            return None, f"Empty data for {ticker}"

        data = data.reset_index()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [c[0] for c in data.columns]

        if "Datetime" in data.columns:
            data["Datetime"] = pd.to_datetime(data["Datetime"], utc=True)
        elif "Date" in data.columns:
            data["Datetime"] = pd.to_datetime(data["Date"], utc=True)

        if target_tf.lower() == "4h":
            data.set_index("Datetime", inplace=True)
            data = data.resample("4h").agg({
                "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
            }).dropna().reset_index()

        ohlcv = []
        for _, row in data.iterrows():
            dt = row["Datetime"]
            ts = int(pd.Timestamp(dt).timestamp() * 1000)
            ohlcv.append([ts, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])])
        return ohlcv, None
    except Exception as e:
        return None, str(e)

def find_mother_offset(ohlcv: list, max_lookback: int = 50) -> int:
    n = len(ohlcv)
    for i in range(min(max_lookback, n - 2)):
        h_c, l_c = ohlcv[i][2], ohlcv[i][3]
        h_p, l_p = ohlcv[i+1][2], ohlcv[i+1][3]
        if h_c < h_p and l_c > l_p:
            continue
        else:
            return i
    return min(max_lookback, n - 2)

def check_strat1_symbol(display_name: str, ticker: str, target_tf: str):
    ohlcv, err = get_s1_ohlcv(ticker, target_tf)
    if err or not ohlcv or len(ohlcv) < 8:
        return None, None

    off = find_mother_offset(ohlcv)
    m_idx = 1 + off
    if m_idx >= len(ohlcv):
        return None, None

    m_h, m_l = ohlcv[m_idx][2], ohlcv[m_idx][3]
    t_h, t_l, t_c = ohlcv[0][2], ohlcv[0][3], ohlcv[0][4]

    sweep_low = t_l < m_l
    engulf_up = t_h > m_h and t_c > m_h
    long_cond = sweep_low and engulf_up

    sweep_high = t_h > m_h
    engulf_dn = t_l < m_l and t_c < m_l
    short_cond = sweep_high and engulf_dn

    sym_key = f"{ticker}_{target_tf}"
    prev_long = strat1_state.get(f"{sym_key}_prev_long", False)
    prev_short = strat1_state.get(f"{sym_key}_prev_short", False)

    long_sig = long_cond and not prev_long
    short_sig = short_cond and not prev_short

    strat1_state[f"{sym_key}_prev_long"] = long_cond
    strat1_state[f"{sym_key}_prev_short"] = short_cond

    signal = "BUY" if long_sig else ("SELL" if short_sig else None)
    
    if signal:
        active_type = "BUY" if long_cond else "SELL"
        entry = t_c
        sl = t_l if active_type == "BUY" else t_h
        risk = abs(entry - sl)
        tp = entry + (risk * 2.0) if active_type == "BUY" else entry - (risk * 2.0)
        type_emoji = "🟢" if active_type == "BUY" else "🔴"
        now = datetime.now(timezone.utc).strftime("%d %b %Y • %H:%M UTC")
        
        msg = (
            f"<b>{type_emoji} STRATEGY 1 | {active_type} SIGNAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Asset:</b> <code>{display_name}</code>\n"
            f"⏱️ <b>Timeframe:</b> <code>{target_tf}</code>\n"
            f"🕒 <b>Time:</b> <code>{now}</code>\n\n"
            f"🎯 <b>Entry Price:</b> <code>~{entry:.4f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>{sl:.4f}</code>\n"
            f"💰 <b>Take Profit (2.0R):</b> <code>{tp:.4f}</code>"
        )
        return signal, msg

    return None, None

# ========== STRATEGY 2 LOGIC (UT Bot + MTF) ==========
def calculate_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['Close'] = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_open = np.zeros(len(df))
    ha_open[0] = (df['Open'].iloc[0] + df['Close'].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i-1] + ha_df['Close'].iloc[i-1]) / 2
    ha_df['Open'] = ha_open
    ha_df['High'] = ha_df[['Open', 'Close', 'High']].max(axis=1)
    ha_df['Low'] = ha_df[['Open', 'Close', 'Low']].min(axis=1)
    return ha_df

def calculate_ut_bot(df):
    calc_df = calculate_heikin_ashi(df) if USE_HEIKIN_ASHI else df.copy()
    high, low, close = calc_df['High'], calc_df['Low'], calc_df['Close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(ATR_PERIOD).mean()
    n_loss = SENSITIVITY * atr

    x_atr_trailing_stop = np.zeros(len(calc_df))
    for i in range(1, len(calc_df)):
        prev_stop = x_atr_trailing_stop[i-1]
        curr_close = close.iloc[i]
        prev_close = close.iloc[i-1]
        loss = n_loss.iloc[i]

        if curr_close > prev_stop and prev_close > prev_stop:
            x_atr_trailing_stop[i] = max(prev_stop, curr_close - loss)
        elif curr_close < prev_stop and prev_close < prev_stop:
            x_atr_trailing_stop[i] = min(prev_stop, curr_close + loss)
        elif curr_close > prev_stop:
            x_atr_trailing_stop[i] = curr_close - loss
        else:
            x_atr_trailing_stop[i] = curr_close + loss

    calc_df['TrailingStop'] = x_atr_trailing_stop
    ema1 = close
    prev_ema = ema1.shift(1)
    prev_stop = calc_df['TrailingStop'].shift(1)

    above = (ema1 > calc_df['TrailingStop']) & (prev_ema <= prev_stop)
    below = (ema1 < calc_df['TrailingStop']) & (prev_ema >= prev_stop)

    calc_df['Buy'] = (close > calc_df['TrailingStop']) & above
    calc_df['Sell'] = (close < calc_df['TrailingStop']) & below
    calc_df['BullishState'] = close > calc_df['TrailingStop']
    return calc_df

def check_ut_bot_signals():
    alerts = []
    now = datetime.now(timezone.utc).strftime("%d %b %Y • %H:%M UTC")
    
    for asset, symbol in UT_SYMBOLS.items():
        try:
            data_15m = yf.download(symbol, period="5d", interval="15m", progress=False, auto_adjust=True)
            if data_15m.empty or len(data_15m) < ATR_PERIOD + 2:
                continue
            if isinstance(data_15m.columns, pd.MultiIndex):
                data_15m.columns = data_15m.columns.get_level_values(0)
            df_15m = calculate_ut_bot(data_15m)

            data_5m = yf.download(symbol, period="1d", interval="5m", progress=False, auto_adjust=True)
            if data_5m.empty or len(data_5m) < ATR_PERIOD + 2:
                continue
            if isinstance(data_5m.columns, pd.MultiIndex):
                data_5m.columns = data_5m.columns.get_level_values(0)
            df_5m = calculate_ut_bot(data_5m)

            is_15m_buy = bool(df_15m['Buy'].iloc[-2])
            is_15m_sell = bool(df_15m['Sell'].iloc[-2])
            is_5m_bullish = bool(df_5m['BullishState'].iloc[-2])
            is_5m_bearish = not is_5m_bullish

            last_close = round(float(data_15m['Close'].iloc[-2]), 4)
            key = f"{asset}_15m_5m_confirmed"

            prev_buy = ut_bot_state.get(f"{key}_buy", False)
            prev_sell = ut_bot_state.get(f"{key}_sell", False)

            confirmed_buy = is_15m_buy and is_5m_bullish
            confirmed_sell = is_15m_sell and is_5m_bearish

            ut_bot_state[f"{key}_buy"] = confirmed_buy
            ut_bot_state[f"{key}_sell"] = confirmed_sell

            if confirmed_buy and not prev_buy:
                msg = (
                    f"<b>🟢 UT BOT | CONFIRMED BUY SIGNAL</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 <b>Asset:</b> <code>{asset}</code>\n"
                    f"⏱️ <b>Timeframe:</b> <code>15m (Confirmed on 5m)</code>\n"
                    f"💵 <b>Current Price:</b> <code>{last_close}</code>\n"
                    f"🕒 <b>Time:</b> <code>{now}</code>\n\n"
                    f"⚡ <b>Filter:</b> <i>15m Buy aligned with 5m Bullish Trend</i>"
                )
                alerts.append((symbol, asset, msg))
            elif confirmed_sell and not prev_sell:
                msg = (
                    f"<b>🔴 UT BOT | CONFIRMED SELL SIGNAL</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 <b>Asset:</b> <code>{asset}</code>\n"
                    f"⏱️ <b>Timeframe:</b> <code>15m (Confirmed on 5m)</code>\n"
                    f"💵 <b>Current Price:</b> <code>{last_close}</code>\n"
                    f"🕒 <b>Time:</b> <code>{now}</code>\n\n"
                    f"⚡ <b>Filter:</b> <i>15m Sell aligned with 5m Bearish Trend</i>"
                )
                alerts.append((symbol, asset, msg))
        except Exception as e:
            print(f"UT Bot error ({asset}): {e}")

    return alerts

# ========== CALLBACK HANDLERS (Inline Buttons Mute/Unmute) ==========
@bot.callback_query_handler(func=lambda call: call.data.startswith('mute_') or call.data.startswith('unmute_'))
def handle_mute_callback(call):
    action, asset_name = call.data.split('_', 1)
    if action == 'mute':
        muted_assets.add(asset_name)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔔 Unmute Notifications", callback_data=f"unmute_{asset_name}"))
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + f"\n\n🛑 <i>Notifications muted for {asset_name}</i>",
            parse_mode="HTML",
            reply_markup=markup
        )
    elif action == 'unmute':
        muted_assets.discard(asset_name)
        bot.answer_callback_query(call.id, f"Notifications enabled for {asset_name}!")

# ========== TELEGRAM COMMAND HANDLERS ==========
@bot.message_handler(commands=['hi', 'start', 'help'])
@bot.message_handler(func=lambda message: message.text and message.text.lower().strip() in ['hi', 'hello', 'hey'])
def handle_greeting(message):
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    guide = (
        "🤖 <b>ADVANCED TRADING BOT CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>Status:</b> <code>ONLINE 24/7</code>\n"
        f"⏰ <b>Server Time:</b> <code>{now}</code>\n\n"
        "📈 <b>Tracked Assets:</b>\n"
        " ├ <b>Crypto/Gold:</b> <i>BTC, Gold (XAU)</i>\n"
        " ├ <b>Forex Pairs:</b> <i>EURUSD, GBPUSD, AUDUSD, USDJPY, NZDUSD</i>\n"
        " └ <b>Indices:</b> <i>NIFTY 50, BANK NIFTY</i>\n\n"
        "🛠️ <b>Commands:</b>\n"
        "💬 <code>hi</code> - <i>Display Control Panel</i>\n"
        "🔍 <code>/check</code> - <i>Scan all strategy setups</i>\n"
        "⚙️ <code>/status</code> - <i>System diagnostics</i>\n"
        "📊 <code>/summary</code> - <i>Daily market overview</i>"
    )
    safe_send_message(message.chat.id, guide)

@bot.message_handler(commands=['summary'])
def handle_summary(message):
    safe_send_message(message.chat.id, "📊 <i>Generating daily market summary report...</i>")
    summary_lines = []
    
    for name, symbol in UT_SYMBOLS.items():
        try:
            d = yf.download(symbol, period="1d", interval="1m", progress=False)
            if not d.empty:
                cp = round(float(d['Close'].iloc[-1]), 4)
                summary_lines.append(f"• <b>{name}:</b> <code>{cp}</code>")
        except Exception:
            pass

    report = "📊 <b>DAILY MARKET OVERVIEW REPORT</b>\n━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(summary_lines)
    safe_send_message(message.chat.id, report)

@bot.message_handler(commands=['status'])
def handle_status(message):
    safe_send_message(message.chat.id, "⏳ <i>Running diagnostics on all data feeds...</i>")
    results = []
    
    for item in STRAT1_SYMBOLS:
        _, err = get_s1_ohlcv(item["ticker"], item["tf"])
        if err:
            results.append(f"❌ <b>Strat 1 - {item['name']}:</b> <code>{err}</code>")
        else:
            results.append(f"✅ <b>Strat 1 - {item['name']}:</b> <code>OPERATIONAL</code>")

    now = datetime.now(timezone.utc).strftime("%d %b %Y • %H:%M UTC")
    report = f"⚙️ <b>SYSTEM DIAGNOSTICS REPORT</b>\n<i>Generated: {now}</i>\n\n" + "\n".join(results)
    safe_send_message(message.chat.id, report)

@bot.message_handler(commands=['check'])
def handle_check(message):
    safe_send_message(message.chat.id, "🔍 <i>Scanning Strategy 1 and Strategy 2 markets...</i>")
    found = 0

    # Strategy 1 Scan
    for item in STRAT1_SYMBOLS:
        _, msg = check_strat1_symbol(item["name"], item["ticker"], item["tf"])
        if msg:
            tv_sym = item["ticker"].replace("=X", "").replace("-", "")
            send_signal_with_chart(message.chat.id, item["ticker"], item["name"], msg, tv_sym)
            found += 1

    # Strategy 2 Scan
    ut_alerts = check_ut_bot_signals()
    for symbol, asset_name, alert_msg in ut_alerts:
        tv_sym = symbol.replace("=X", "").replace("-", "")
        send_signal_with_chart(message.chat.id, symbol, asset_name, alert_msg, tv_sym)
        found += 1

    if found == 0:
        safe_send_message(message.chat.id, "📊 <b>SCAN COMPLETE:</b> No active signals detected on any strategy right now.")

# ========== BACKGROUND SCANNER ==========
def run_telegram_bot():
    print("Bot listening for Telegram commands...")
    bot.infinity_polling(skip_pending=True)

def run_background_scanner():
    while True:
        try:
            if TELEGRAM_CHAT_ID:
                for item in STRAT1_SYMBOLS:
                    sig, msg = check_strat1_symbol(item["name"], item["ticker"], item["tf"])
                    if sig and msg:
                        tv_sym = item["ticker"].replace("=X", "").replace("-", "")
                        send_signal_with_chart(TELEGRAM_CHAT_ID, item["ticker"], item["name"], msg, tv_sym)

                ut_alerts = check_ut_bot_signals()
                for symbol, asset_name, alert_msg in ut_alerts:
                    tv_sym = symbol.replace("=X", "").replace("-", "")
                    send_signal_with_chart(TELEGRAM_CHAT_ID, symbol, asset_name, alert_msg, tv_sym)
        except Exception as e:
            print(f"Background scanner exception: {e}")
            
        time.sleep(300) # Check every 5 minutes

if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    threading.Thread(target=run_background_scanner, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
