import os
import json
import threading
import time
import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# CRITICAL: Set matplotlib backend BEFORE importing pyplot
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO

# --- ENVIRONMENT VARIABLES ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- PERSISTENCE FILES ---
MUTE_FILE = "muted_assets.json"
SIGNALS_FILE = "sent_signals.json"

def load_json(filepath, default):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
    return default

def save_json(filepath, data):
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")

muted_assets = set(load_json(MUTE_FILE, []))
sent_signals = load_json(SIGNALS_FILE, {})

MONITORED_ASSETS = [
    ("BTC-USD", "Crypto"),
    ("GC=F", "Gold"),
    ("EURUSD=X", "Forex"),
    ("GBPUSD=X", "Forex"),
    ("USDJPY=X", "Forex"),
    ("^NSEI", "NIFTY 50"),
    ("^NSEBANK", "BANK NIFTY")
]

# --- FLASK WEBSERVER ---
@app.route("/")
def home():
    return "Trading Bot Webserver Running OK", 200

@app.route("/ping")
def ping():
    return "pong", 200

# --- UI MARKUP ---
def get_main_menu_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔍 Check Markets Now", callback_data="cmd_check"))
    markup.add(InlineKeyboardButton("📊 Asset Dashboard", callback_data="cmd_summary"))
    return markup

def get_user_guide_text():
    return (
        "🤖 *━━ PREMIUM TRADING TERMINAL ━━*\n\n"
        "⚙️ *ACTIVE CONFIGURATIONS:*\n"
        "├ 🟣 *UT Bot:* `Key Value: 2 | ATR: 1`\n"
        "└ 🔵 *Sweep:* Normal & Mother\-Child\n\n"
        "📘 *HOW TO USE:*\n"
        "▫️ `/check` \-\> Instant multi\-asset scan\n"
        "▫️ `/summary` \-\> Live prices & mute status\n"
        "▫️ Tap `📈 View Chart` for dark\-mode charts\n"
        "▫️ Tap `🔇 Mute` to pause sideways assets\n\n"
        "🛡️ _All alerts include ATR based SL/TP_"
    )

# --- CHART GENERATOR ---
def generate_chart(symbol):
    try:
        df = yf.download(symbol, period="5d", interval="1h", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if df.empty: return None

        fig, ax = plt.subplots(figsize=(12, 6), facecolor='#0d1117')
        ax.set_facecolor('#0d1117')
        colors = ['#00ff88' if c >= o else '#ff4444' for o, c in zip(df['Open'], df['Close'])]
        
        for i in range(len(df)):
            ax.plot([df.index[i], df.index[i]], [df['Low'].iloc[i], df['High'].iloc[i]], color=colors[i], linewidth=1)
            ax.plot([df.index[i], df.index[i]], [df['Open'].iloc[i], df['Close'].iloc[i]], color=colors[i], linewidth=4)
        
        ax.set_title(f'{symbol} | 1H Chart', color='white', fontsize=14, fontweight='bold')
        ax.tick_params(colors='gray', labelsize=8)
        for spine in ax.spines.values(): spine.set_color('#30363d')
        ax.grid(True, color='#21262d', linestyle='--', linewidth=0.5)
        
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='#0d1117')
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        print(f"Chart error: {e}")
        return None

# --- TECHNICAL ANALYSIS CORE ---

def calculate_atr(df, period=1):
    high_low = df['High'] - df['Low']
    high_cp = np.abs(df['High'] - df['Close'].shift(1))
    low_cp = np.abs(df['Low'] - df['Close'].shift(1))
    df_tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    # Wilder's Smoothing (RMA) exactly like TradingView
    return df_tr.ewm(alpha=1/period, adjust=False).mean()

def calculate_sl_tp(signal_type, price, atr):
    if "BULLISH" in signal_type:
        sl = price - (atr * 1.5)
        tp = price + (atr * 3.0)
    else:
        sl = price + (atr * 1.5)
        tp = price - (atr * 3.0)
    return sl, tp

def format_rr(sl, tp, price):
    risk = abs(price - sl)
    reward = abs(tp - price)
    if risk == 0: return "N/A"
    return f"1:{reward/risk:.1f}"


# --- STRATEGY 1: SWEEP + ENGULFING ---
def check_sweep_engulfing_strategy(ticker):
    try:
        df_1h = yf.download(ticker, period="1mo", interval="1h", progress=False)
        if df_1h.empty or len(df_1h) < 30: return None
        if isinstance(df_1h.columns, pd.MultiIndex): df_1h.columns = df_1h.columns.get_level_values(0)

        df_4h = df_1h.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}).dropna()
        if len(df_4h) < 5: return None

        df_4h['ATR'] = calculate_atr(df_4h, 10) # Keep standard 10 for 4H structural stops
        
        c1 = df_4h.iloc[-2] 
        c2 = df_4h.iloc[-3] 
        c3 = df_4h.iloc[-4] 
        
        atr_val = df_4h['ATR'].iloc[-2]
        is_inside_bar = (c2['High'] <= c3['High']) and (c2['Low'] >= c3['Low'])
        
        if not is_inside_bar:
            is_bullish = (c1['Low'] < c2['Low']) and (c1['Close'] > c2['High'])
            is_bearish = (c1['High'] > c2['High']) and (c1['Close'] < c2['Low'])
            if is_bullish: return ("BULLISH 4H Normal Sweep", c1['Close'], atr_val)
            if is_bearish: return ("BEARISH 4H Normal Sweep", c1['Close'], atr_val)
        else:
            is_mc_bullish = (c1['Low'] < c3['Low']) and (c1['Close'] > c3['High'])
            is_mc_bearish = (c1['High'] > c3['High']) and (c1['Close'] < c3['Low'])
            if is_mc_bullish: return ("BULLISH 4H Mother-Child Sweep", c1['Close'], atr_val)
            if is_mc_bearish: return ("BEARISH 4H Mother-Child Sweep", c1['Close'], atr_val)

        return None
    except Exception as e:
        print(f"Error Sweep {ticker}: {e}")
        return None


# --- STRATEGY 2: EXACT UT BOT (KV=2, ATR=1) ---
def check_ut_bot_strategy(ticker, key_value=2, atr_period=1):
    try:
        df_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
        df_5m = yf.download(ticker, period="5d", interval="5m", progress=False)
        if df_15m.empty or len(df_15m) < 30 or df_5m.empty or len(df_5m) < 50: return None
        
        if isinstance(df_15m.columns, pd.MultiIndex): df_15m.columns = df_15m.columns.get_level_values(0)
        if isinstance(df_5m.columns, pd.MultiIndex): df_5m.columns = df_5m.columns.get_level_values(0)

        df_15m['xATR'] = calculate_atr(df_15m, atr_period)
        df_15m['nLoss'] = key_value * df_15m['xATR']
        
        src = df_15m['Close'].values
        nLoss = df_15m['nLoss'].values
        ts = np.zeros(len(df_15m))
        pos = np.zeros(len(df_15m))
        
        for i in range(1, len(df_15m)):
            prev_ts = ts[i-1]
            prev_src = src[i-1]
            
            if src[i] > prev_ts and prev_src > prev_ts:
                ts[i] = max(prev_ts, src[i] - nLoss[i])
            elif src[i] < prev_ts and prev_src < prev_ts:
                ts[i] = min(prev_ts, src[i] + nLoss[i])
            elif src[i] > prev_ts:
                ts[i] = src[i] - nLoss[i]
            else:
                ts[i] = src[i] + nLoss[i]
                
            if prev_src < prev_ts and src[i] > ts[i]:
                pos[i] = 1
            elif prev_src > prev_ts and src[i] < ts[i]:
                pos[i] = -1
            else:
                pos[i] = pos[i-1]
                
        df_15m['xATRTrailingStop'] = ts
        
        i = len(df_15m) - 2
        curr_src = src[i]
        curr_ts = ts[i]
        prev_src = src[i-1]
        prev_ts = ts[i-1]
        atr_val = df_15m['xATR'].iloc[i]
        
        is_buy = (curr_src > curr_ts) and (prev_src <= prev_ts)
        is_sell = (curr_src < curr_ts) and (prev_src >= prev_ts)
        
        df_5m['EMA_50'] = df_5m['Close'].ewm(span=50, adjust=False).mean()
        m5_close = df_5m['Close'].iloc[-2]
        m5_ema = df_5m['EMA_50'].iloc[-2]

        if is_buy and m5_close > m5_ema:
            return ("BULLISH UT Bot (15m+5m)", curr_src, atr_val)
        elif is_sell and m5_close < m5_ema:
            return ("BEARISH UT Bot (15m+5m)", curr_src, atr_val)
            
        return None
    except Exception as e:
        print(f"Error UT Bot {ticker}: {e}")
        return None


# --- PREMIUM FORMATTING FUNCTION ---
def build_signal_message(symbol, market_type, strat_name, sig_type, price, sl, tp, rr):
    is_bull = "BULLISH" in sig_type
    emoji = "🟢" if is_bull else "🔴"
    
    return (
        f"{emoji} *━━━ SIGNAL ALERT ━━━* {emoji}\n"
        f"🪙 *Asset:* `{symbol}` \`({market_type})\`\n"
        f"├──────────────────────┈\n"
        f"⚙️ *Strategy Details*\n"
        f"├ Type: *{strat_name}*\n"
        f"├ Setup: *{sig_type}*\n"
        f"└ Sensitivity: `KV 2 | ATR 1`\n"
        f"├──────────────────────┈\n"
        f"📊 *Trade Setup*\n"
        f"├ 🎯 *Entry:* `${price:,.2f}`\n"
        f"├ 🛑 *Stop Loss:* `${sl:,.2f}`\n"
        f"├ 🎯 *Take Profit:* `${tp:,.2f}`\n"
        f"└ 📈 *Risk:Reward:* `{rr}`\n"
        f"├──────────────────────┈\n"
    )


# --- BACKGROUND MONITORING LOOP ---
def background_strategy_loop():
    print("Background strategy monitor initialized...")
    while True:
        try:
            if CHAT_ID:
                for symbol, market_type in MONITORED_ASSETS:
                    if symbol in muted_assets:
                        time.sleep(0.5)
                        continue

                    # Notice key_value=2, atr_period=1 explicitly passed here
                    ut_signal = check_ut_bot_strategy(symbol, key_value=2, atr_period=1)
                    sweep_signal = check_sweep_engulfing_strategy(symbol)
                    
                    signals_to_send = []
                    if ut_signal: signals_to_send.append(("UT Bot Alerts", ut_signal))
                    if sweep_signal: signals_to_send.append(("Sweep Engulfing", sweep_signal))

                    for strat_name, signal_data in signals_to_send:
                        sig_type, price, atr_val = signal_data
                        sl, tp = calculate_sl_tp(sig_type, price, atr_val)
                        rr = format_rr(sl, tp, price)
                        sig_key = f"{symbol}_{strat_name}_{sig_type}"
                        
                        if sent_signals.get(sig_key) != price:
                            sent_signals[sig_key] = price
                            save_json(SIGNALS_FILE, sent_signals)
                            
                            alert_msg = build_signal_message(symbol, market_type, strat_name, sig_type, price, sl, tp, rr)
                            
                            markup = InlineKeyboardMarkup()
                            markup.add(
                                InlineKeyboardButton(f"📈 View Chart", callback_data=f"chart_{symbol}"),
                                InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}")
                            )
                            bot.send_message(CHAT_ID, alert_msg, parse_mode="Markdown", reply_markup=markup)
                    
                    time.sleep(0.5)
        except Exception as e:
            print(f"Error inside background loop: {e}")
        time.sleep(60)

# --- TELEGRAM HANDLERS ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, get_user_guide_text(), parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['check'])
def handle_check_command(message):
    bot.send_message(message.chat.id, "🔍 *━ SCANNING MARKETS ━*", parse_mode="Markdown")
    signals_found = []
    
    for symbol, _ in MONITORED_ASSETS:
        ut = check_ut_bot_strategy(symbol, key_value=2, atr_period=1)
        sweep = check_sweep_engulfing_strategy(symbol)
        if ut: signals_found.append(f"  🟢 *{symbol}* ➔ {ut[0]} \(`${ut[1]:,.2f}`\)")
        if sweep: signals_found.append(f"  🔵 *{symbol}* ➔ {sweep[0]} \(`${sweep[1]:,.2f}`\)")
        time.sleep(0.5)

    if signals_found:
        text = (
            "🎯 *━ SCAN RESULTS ━*\n"
            "├──────────────────────┈\n" +
            "\n".join(signals_found) +
            "\n├──────────────────────┈\n"
            "⚡ *Active setups found above*"
        )
    else:
        text = (
            "⏳ *━ SCAN RESULTS ━*\n"
            "├──────────────────────┈\n"
            "  ⚪ *Status:* No Active Signals\n"
            "  💤 *Action:* Markets are consolidating\n"
            "├──────────────────────┈\n"
            "  🛡️ _Waiting for high probability setups_"
        )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['summary'])
def handle_summary_command(message):
    summary_lines = []
    for symbol, mtype in MONITORED_ASSETS:
        status = "🔇 Muted" if symbol in muted_assets else "🟢 Active"
        try:
            price = yf.Ticker(symbol).fast_info['lastPrice']
            summary_lines.append(f"  ├ {status} *{symbol}* \({mtype}\) ➔ `${price:,.2f}`")
        except:
            summary_lines.append(f"  ├ {status} *{symbol}* \({mtype}\)")
        time.sleep(0.5)
        
    text = (
        "📊 *━ MARKET DASHBOARD ━*\n"
        "├──────────────────────┈\n" +
        "\n".join(summary_lines) +
        "\n├──────────────────────┈\n"
        "⚙️ _UT Bot: KV 2 | ATR 1_"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(func=lambda msg: True)
def handle_all_other_messages(message):
    bot.reply_to(message, get_user_guide_text(), parse_mode="Markdown", reply_markup=get_main_menu_markup())

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
        bot.answer_callback_query(call.id, text="Generating dark-mode chart...")
        chart_buf = generate_chart(symbol)
        if chart_buf:
            bot.send_photo(call.message.chat.id, chart_buf, caption=f"📈 *{symbol}* | 1H Dark\-Mode Chart", parse_mode="Markdown")
        else:
            bot.send_message(call.message.chat.id, "❌ Failed to generate chart.", parse_mode="Markdown")
            
    elif call.data.startswith("mute_"):
        symbol = call.data.split("_")[1]
        muted_assets.add(symbol)
        save_json(MUTE_FILE, list(muted_assets))
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"🔊 Unmute {symbol}", callback_data=f"unmute_{symbol}"))
        bot.edit_message_text(
            f"🔇 *━━ ASSET MUTED ━━*\n├──────────────────────┈\n└ Notifications for *{symbol}* are now *paused*.", 
            chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=markup)
        
    elif call.data.startswith("unmute_"):
        symbol = call.data.split("_")[1]
        muted_assets.discard(symbol)
        save_json(MUTE_FILE, list(muted_assets))
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}"))
        bot.edit_message_text(
            f"🔊 *━━ ASSET UNMUTED ━━*\n├──────────────────────┈\n└ Notifications for *{symbol}* have *resumed*.", 
            chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=markup)

# --- START THREADS AND FLASK SERVER ---
if __name__ == "__main__":
    strategy_thread = threading.Thread(target=background_strategy_loop, daemon=True)
    strategy_thread.start()
    bot_thread = threading.Thread(target=lambda: bot.infinity_polling(timeout=20, long_polling_timeout=10), daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
