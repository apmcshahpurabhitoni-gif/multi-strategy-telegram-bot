"""
Unified 2-Way Interactive Trading Bot (Render Web Service Edition)
===================================================================
Features:
- Strategy 1: Sweep + Engulfing (4H/1H)
- Strategy 2: UT Bot ATR Trailing Stop (15m Signal + 5m Confirmed Filter)
- Telegram 2-Way Commands: 'hi', '/check', '/status'
- Robust Direct Messaging (Fixes 'has no access to message' error)
- Rich HTML Telegram Message Formatting
"""

import os
import time
import threading
from datetime import datetime, timezone

from flask import Flask
import telebot
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# ========== SECRETS ==========
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing!")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Flask Server (Required to keep Render Web Service active)
app = Flask(__name__)

@app.route('/')
def home():
    return "Unified Trading Bot is active and running!"

# ========== STRATEGY 1 CONFIG (Sweep + Engulfing) ==========
STRAT1_SYMBOLS = [
    {"name": "BTC / USDT",  "ticker": "BTC-USD",   "tf": "4H"},
    {"name": "Gold (XAU)",  "ticker": "GC=F",      "tf": "4H"},
    {"name": "NIFTY 50",    "ticker": "^NSEI",     "tf": "1H"},
    {"name": "BANK NIFTY",  "ticker": "^NSEBANK",  "tf": "1H"}
]
strat1_state = {}

# ========== STRATEGY 2 CONFIG (UT Bot with 5m/15m MTF Confirmation Filter) ==========
UT_SYMBOLS = {
    "Bitcoin (BTC)": "BTC-USD",
    "Gold (XAU)": "GC=F"
}
SENSITIVITY = 1
ATR_PERIOD = 10
USE_HEIKIN_ASHI = True
ut_bot_state = {}

# ========== TELEGRAM UTILITY ==========
def send_telegram_alert(message):
    if not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")

# ========== STRATEGY 1 LOGIC (Sweep + Engulfing) ==========
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
        return None, f"⚠️ <b>{display_name} Error:</b> {err or 'Insufficient data'}"

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
    
    if signal or long_cond or short_cond:
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
            f"🎯 <b>Entry Price:</b> <code>~{entry:.2f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>{sl:.2f}</code>\n"
            f"💰 <b>Take Profit (2.0R):</b> <code>{tp:.2f}</code>\n\n"
            f"📉 <b>Trigger High/Low:</b> <code>{t_h:.2f} / {t_l:.2f}</code>\n"
            f"📦 <b>Mother Range:</b> <code>{m_h:.2f} / {m_l:.2f}</code>"
        )
        return signal, msg

    return None, None

# ========== STRATEGY 2 LOGIC (UT Bot + MTF Filter) ==========
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
            # Fetch 15m Data
            data_15m = yf.download(symbol, period="5d", interval="15m", progress=False, auto_adjust=True)
            if data_15m.empty or len(data_15m) < ATR_PERIOD + 2:
                continue
            if isinstance(data_15m.columns, pd.MultiIndex):
                data_15m.columns = data_15m.columns.get_level_values(0)
            df_15m = calculate_ut_bot(data_15m)

            # Fetch 5m Data
            data_5m = yf.download(symbol, period="1d", interval="5m", progress=False, auto_adjust=True)
            if data_5m.empty or len(data_5m) < ATR_PERIOD + 2:
                continue
            if isinstance(data_5m.columns, pd.MultiIndex):
                data_5m.columns = data_5m.columns.get_level_values(0)
            df_5m = calculate_ut_bot(data_5m)

            # Analyze Signals
            is_15m_buy = bool(df_15m['Buy'].iloc[-2])
            is_15m_sell = bool(df_15m['Sell'].iloc[-2])
            
            is_5m_bullish = bool(df_5m['BullishState'].iloc[-2])
            is_5m_bearish = not is_5m_bullish

            last_close = round(float(data_15m['Close'].iloc[-2]), 2)
            key = f"{asset}_15m_5m_confirmed"

            prev_buy = ut_bot_state.get(f"{key}_buy", False)
            prev_sell = ut_bot_state.get(f"{key}_sell", False)

            # Filter: 15m Signal MUST be confirmed by 5m Trend State
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
                    f"💵 <b>Current Price:</b> <code>${last_close}</code>\n"
                    f"🕒 <b>Time:</b> <code>{now}</code>\n\n"
                    f"⚡ <b>Filter:</b> <i>15m Buy Signal aligned with 5m Bullish Trend</i>"
                )
                alerts.append(msg)
            elif confirmed_sell and not prev_sell:
                msg = (
                    f"<b>🔴 UT BOT | CONFIRMED SELL SIGNAL</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 <b>Asset:</b> <code>{asset}</code>\n"
                    f"⏱️ <b>Timeframe:</b> <code>15m (Confirmed on 5m)</code>\n"
                    f"💵 <b>Current Price:</b> <code>${last_close}</code>\n"
                    f"🕒 <b>Time:</b> <code>{now}</code>\n\n"
                    f"⚡ <b>Filter:</b> <i>15m Sell Signal aligned with 5m Bearish Trend</i>"
                )
                alerts.append(msg)

        except Exception as e:
            print(f"UT Bot MTF error ({asset}): {e}")

    return alerts

# ========== TELEGRAM COMMAND HANDLERS ==========
def get_help_guide():
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    return (
        "🤖 <b>TRADING BOT CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>Status:</b> <code>ONLINE & RUNNING 24/7</code>\n"
        f"⏰ <b>Server Time:</b> <code>{now}</code>\n\n"
        "📈 <b>Active Algorithms:</b>\n"
        " ├ <b>Strategy 1:</b> <i>Sweep + Engulfing (4H/1H)</i>\n"
        " └ <b>Strategy 2:</b> <i>UT Bot ATR (15m + 5m Confirmed)</i>\n\n"
        "🛠️ <b>Interactive Commands:</b>\n\n"
        "💬 Send <code>hi</code> / <code>hello</code>\n"
        "└ <i>Verifies connection & brings up this menu</i>\n\n"
        "🔍 Send <code>/check</code>\n"
        "└ <i>Triggers instant scan on both strategies</i>\n\n"
        "⚙️ Send <code>/status</code>\n"
        "└ <i>Runs live diagnostic test on all market feeds</i>"
    )

@bot.message_handler(commands=['hi', 'start', 'help'])
@bot.message_handler(func=lambda message: message.text and message.text.lower().strip() in ['hi', 'hello', 'hey', 'hi!', 'hello!'])
def handle_greeting(message):
    bot.send_message(message.chat.id, get_help_guide(), parse_mode="HTML")

@bot.message_handler(commands=['status'])
def handle_status(message):
    bot.send_message(message.chat.id, "⏳ <i>Running diagnostics across Strategy 1 & Strategy 2...</i>", parse_mode="HTML")
    results = []
    
    # Strat 1 Diagnostics
    for item in STRAT1_SYMBOLS:
        _, err = get_s1_ohlcv(item["ticker"], item["tf"])
        if err:
            results.append(f"❌ <b>Strat 1 - {item['name']}:</b> <code>{err}</code>")
        else:
            results.append(f"✅ <b>Strat 1 - {item['name']}:</b> <code>OPERATIONAL</code>")

    # Strat 2 Diagnostics
    for asset, symbol in UT_SYMBOLS.items():
        try:
            d = yf.download(symbol, period="1d", interval="5m", progress=False)
            if not d.empty:
                results.append(f"✅ <b>Strat 2 - {asset} (15m/5m):</b> <code>OPERATIONAL</code>")
            else:
                results.append(f"❌ <b>Strat 2 - {asset}:</b> <code>EMPTY DATA</code>")
        except Exception as e:
            results.append(f"❌ <b>Strat 2 - {asset}:</b> <code>{e}</code>")

    now = datetime.now(timezone.utc).strftime("%d %b %Y • %H:%M UTC")
    report = f"⚙️ <b>SYSTEM DIAGNOSTICS REPORT</b>\n<i>Generated: {now}</i>\n\n" + "\n".join(results)
    bot.send_message(message.chat.id, report, parse_mode="HTML")

@bot.message_handler(commands=['check'])
def handle_check(message):
    bot.send_message(message.chat.id, "🔍 <i>Scanning Strategy 1 and Strategy 2 markets...</i>", parse_mode="HTML")
    found = 0

    # Scan Strategy 1
    for item in STRAT1_SYMBOLS:
        _, msg = check_strat1_symbol(item["name"], item["ticker"], item["tf"])
        if msg and "Error" not in msg:
            bot.send_message(message.chat.id, msg, parse_mode="HTML")
            found += 1

    # Scan Strategy 2
    ut_alerts = check_ut_bot_signals()
    for alert in ut_alerts:
        bot.send_message(message.chat.id, alert, parse_mode="HTML")
        found += 1

    if found == 0:
        bot.send_message(message.chat.id, "📊 <b>SCAN COMPLETE:</b> No active signals detected on any strategy right now.")

# ========== BACKGROUND WORKERS ==========
def run_telegram_bot():
    print("Bot listening for Telegram commands...")
    bot.infinity_polling(skip_pending=True)

def run_background_scanner():
    """Scans all markets automatically in background threads."""
    while True:
        try:
            # Check Strategy 1
            for item in STRAT1_SYMBOLS:
                sig, msg = check_strat1_symbol(item["name"], item["ticker"], item["tf"])
                if sig and msg and "Error" not in msg:
                    send_telegram_alert(msg)

            # Check Strategy 2
            ut_alerts = check_ut_bot_signals()
            for alert in ut_alerts:
                send_telegram_alert(alert)

        except Exception as e:
            print(f"Background scanner exception: {e}")
            
        time.sleep(300) # Check every 5 minutes

if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    threading.Thread(target=run_background_scanner, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
