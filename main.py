import os
import json
import threading
import time
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
import pytz

# CRITICAL: Set matplotlib backend BEFORE importing pyplot
import matplotlib
matplotlib.use('Agg')

# --- ENVIRONMENT VARIABLES ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
if not TOKEN: raise ValueError("TELEGRAM_BOT_TOKEN not set!")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

IST = pytz.timezone('Asia/Kolkata')
json_lock = threading.Lock()

# --- FILE PATHS ---
ACCOUNTS_FILE = "accounts.json"
ACTIVE_TRADES_FILE = "active_trades.json"
HISTORY_FILE = "trade_history.json"

# --- PERSISTENCE HELPERS (Thread-Safe) ---
def load_json(filepath, default):
    with json_lock:
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f: return json.load(f)
        except Exception as e: print(f"Error loading {filepath}: {e}")
    return default

def save_json(filepath, data):
    with json_lock:
        try:
            with open(filepath, 'w') as f: json.dump(data, f, indent=4)
        except Exception as e: print(f"Error saving {filepath}: {e}")

# --- PUSHBULLET NOTIFICATION BRIDGE ---
def send_phone_notification(text):
    try:
        token = os.environ.get("PUSHBULLET_TOKEN")
        if token:
            clean_text = text.replace("*", "").replace("`", "").replace("➔", "->")
            payload = {"type": "note", "title": "💼 Trading Bot Alert", "body": clean_text}
            requests.post("https://api.pushbullet.com/v2/pushes", 
                          json=payload, headers={"Access-Token": token}, timeout=5)
    except Exception as e: print(f"Push error: {e}")

# --- INITIALIZE STATE ---
default_accounts = {
    "macro": {"balance": 100000.0, "daily_trades": 0},
    "nifty": {"balance": 100000.0, "daily_trades": 0},
    "ny_session": {"balance": 100000.0, "daily_trades": 0},
    "last_reset_date": datetime.now(IST).strftime('%Y-%m-%d')
}
accounts = load_json(ACCOUNTS_FILE, default_accounts)
active_trades = load_json(ACTIVE_TRADES_FILE, [])
trade_history = load_json(HISTORY_FILE, [])

# --- AUTO-MIGRATION: SELF-RESET IF OLD FILES DETECTED ---
if "ny_session" not in accounts:
    print("Old data format detected. Auto-resetting to 3 fresh accounts...")
    for f in [ACCOUNTS_FILE, ACTIVE_TRADES_FILE, HISTORY_FILE]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass
    accounts = default_accounts.copy()
    active_trades = []
    trade_history = []
# ---------------------------------------------------

MONITORED_ASSETS = [
    ("BTC-USD", "Crypto", "macro"),
    ("GC=F", "Gold", "macro"),
    ("EURUSD=X", "Forex", "macro"),
    ("GBPUSD=X", "Forex", "macro"),
    ("USDJPY=X", "Forex", "macro"),
    ("^NSEI", "NIFTY 50", "nifty"),
    ("^NSEBANK", "BANK NIFTY", "nifty")
]

# --- NY SESSION DETECTOR ---
def is_ny_session():
    now = datetime.now(IST)
    hour = now.hour
    minute = now.minute
    is_evening = hour >= 18 
    is_early_morning = (hour <= 1) or (hour == 1 and minute <= 30)
    return is_evening or is_early_morning

# --- FLASK WEBSERVER ---
@app.route("/")
def home(): return "Trading Bot Running OK", 200

# --- UI MARKUP ---
def get_main_menu_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📊 P&L Stats", callback_data="cmd_stats"))
    markup.add(InlineKeyboardButton("🏦 Balances", callback_data="cmd_balance"))
    return markup

# --- TECHNICAL ANALYSIS CORE ---
def calculate_atr(df, period=1):
    high_low = df['High'] - df['Low']
    high_cp = np.abs(df['High'] - df['Close'].shift(1))
    low_cp = np.abs(df['Low'] - df['Close'].shift(1))
    df_tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return df_tr.ewm(alpha=1/period, adjust=False).mean()

def calculate_sl_tp(signal_type, price, atr):
    if "BULLISH" in signal_type:
        sl = price - (atr * 1.5)
        tp = price + (atr * 3.0)
    else:
        sl = price + (atr * 1.5)
        tp = price - (atr * 3.0)
    return float(sl), float(tp)

def calculate_position_size(account_type, symbol, entry, sl):
    risk_amount = accounts[account_type]["balance"] * 0.02 
    sl_distance = abs(entry - sl)
    if sl_distance == 0: return 0.0
    
    if account_type == "nifty":
        lot_size = 25 if "NSEI" in symbol else 15
        risk_per_lot = sl_distance * lot_size
        if risk_per_lot == 0: return 0.0
        fractional_lots = risk_amount / risk_per_lot
        return float(fractional_lots * lot_size) 
    else:
        return float(risk_amount / sl_distance)

# --- STRATEGY 1: SWEEP + ENGULFING ---
def check_sweep_engulfing_strategy(ticker):
    try:
        df_1h = yf.download(ticker, period="1mo", interval="1h", progress=False)
        if df_1h.empty or len(df_1h) < 30: return None
        if isinstance(df_1h.columns, pd.MultiIndex): df_1h.columns = df_1h.columns.get_level_values(0)

        df_4h = df_1h.resample('4h').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}).dropna()
        if len(df_4h) < 5: return None

        df_4h['ATR'] = calculate_atr(df_4h, 10) 
        c1, c2, c3 = df_4h.iloc[-2], df_4h.iloc[-3], df_4h.iloc[-4]
        atr_val = float(df_4h['ATR'].iloc[-2])
        is_inside_bar = (c2['High'] <= c3['High']) and (c2['Low'] >= c3['Low'])
        
        if not is_inside_bar:
            if (c1['Low'] < c2['Low']) and (c1['Close'] > c2['High']): return ("BULLISH 4H Normal Sweep", float(c1['Close']), atr_val)
            if (c1['High'] > c2['High']) and (c1['Close'] < c2['Low']): return ("BEARISH 4H Normal Sweep", float(c1['Close']), atr_val)
        else:
            if (c1['Low'] < c3['Low']) and (c1['Close'] > c3['High']): return ("BULLISH 4H Mother-Child", float(c1['Close']), atr_val)
            if (c1['High'] > c3['High']) and (c1['Close'] < c3['Low']): return ("BEARISH 4H Mother-Child", float(c1['Close']), atr_val)
        return None
    except Exception as e: print(f"Sweep Error {ticker}: {e}")

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
        src, nLoss = df_15m['Close'].values, df_15m['nLoss'].values
        ts, pos = np.zeros(len(df_15m)), np.zeros(len(df_15m))
        
        for i in range(1, len(df_15m)):
            prev_ts, prev_src = ts[i-1], src[i-1]
            if src[i] > prev_ts and prev_src > prev_ts: ts[i] = max(prev_ts, src[i] - nLoss[i])
            elif src[i] < prev_ts and prev_src < prev_ts: ts[i] = min(prev_ts, src[i] + nLoss[i])
            elif src[i] > prev_ts: ts[i] = src[i] - nLoss[i]
            else: ts[i] = src[i] + nLoss[i]
            
            if prev_src < prev_ts and src[i] > ts[i]: pos[i] = 1
            elif prev_src > prev_ts and src[i] < ts[i]: pos[i] = -1
            else: pos[i] = pos[i-1]
                
        i = len(df_15m) - 2
        is_buy = (src[i] > ts[i]) and (src[i-1] <= ts[i-1])
        is_sell = (src[i] < ts[i]) and (src[i-1] >= ts[i-1])
        
        df_5m['EMA_50'] = df_5m['Close'].ewm(span=50, adjust=False).mean()
        m5_close, m5_ema = df_5m['Close'].iloc[-2], df_5m['EMA_50'].iloc[-2]

        if is_buy and m5_close > m5_ema: return ("BULLISH UT Bot", float(src[i]), float(df_15m['xATR'].iloc[i]))
        if is_sell and m5_close < m5_ema: return ("BEARISH UT Bot", float(src[i]), float(df_15m['xATR'].iloc[i]))
    except Exception as e: print(f"UT Error {ticker}: {e}")

# --- TRADE EXECUTION ENGINE ---
def execute_trade(symbol, market_type, account_type, strat_name, sig_type, price, atr):
    global accounts, active_trades
    sl, tp = calculate_sl_tp(sig_type, price, atr)
    qty = calculate_position_size(account_type, symbol, price, sl)
    
    if qty <= 0: return False
    if accounts[account_type]["daily_trades"] >= 3: return False
    if any(t['symbol'] == symbol and t['account'] == account_type for t in active_trades): return False

    trade = {
        "id": f"{symbol}_{int(time.time())}",
        "symbol": symbol, "market": market_type, "account": account_type,
        "strat": strat_name, "type": "LONG" if "BULLISH" in sig_type else "SHORT",
        "entry": float(price), "sl": float(sl), "tp": float(tp), "qty": float(qty),
        "time": datetime.now(IST).strftime('%Y-%m-%d %H:%M')
    }
    
    active_trades.append(trade)
    accounts[account_type]["daily_trades"] += 1
    save_json(ACTIVE_TRADES_FILE, active_trades)
    save_json(ACCOUNTS_FILE, accounts)
    
    risk_amt = abs(price - sl) * qty
    
    acc_emoji = "🇺🇸" if account_type == "ny_session" else ("🇮🇳" if account_type == "nifty" else "🌐")
    msg = (
        f"{acc_emoji} *TRADE OPENED*\n"
        f"{'🟢' if trade['type']=='LONG' else '🔴'} *{trade['type']} {symbol}*\n"
        f"Acc: *{account_type.upper()}*\n"
        f"Entry: `{price:,.2f}`\n"
        f"SL: `{sl:,.2f}` | TP: `{tp:,.2f}`\n"
        f"Risk: `₹{risk_amt:,.0f}`"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    send_phone_notification(msg) 
    return True

# --- MONITORING & P&L ENGINE (15s Loop) ---
def monitor_active_trades():
    global active_trades, accounts, trade_history
    while True:
        if not active_trades: time.sleep(15); continue
            
        trades_to_close = []
        for trade in active_trades:
            try:
                df = yf.download(trade['symbol'], period="1d", interval="1m", progress=False)
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                if df.empty: continue
                live_price = float(df['Close'].iloc[-1])
                
                is_long = trade['type'] == "LONG"
                hit_tp = (is_long and live_price >= trade['tp']) or (not is_long and live_price <= trade['tp'])
                hit_sl = (is_long and live_price <= trade['sl']) or (not is_long and live_price >= trade['sl'])
                
                if hit_tp or hit_sl:
                    if hit_tp: pnl = abs(trade['tp'] - trade['entry']) * trade['qty']
                    else: pnl = - (abs(trade['entry'] - trade['sl']) * trade['qty'])
                    
                    accounts[trade['account']]["balance"] += float(pnl)
                    trade['exit_price'] = live_price
                    trade['pnl'] = float(pnl)
                    trade['result'] = "WIN" if hit_tp else "LOSS"
                    trade['close_time'] = datetime.now(IST).strftime('%Y-%m-%d %H:%M')
                    
                    trade_history.append(trade)
                    trades_to_close.append(trade)
                    
                    emoji = "✅" if hit_tp else "❌"
                    msg = (
                        f"{emoji} *TRADE CLOSED*\n"
                        f"{'🟢' if is_long else '🔴'} {trade['symbol']}\n"
                        f"Acc: *{trade['account'].upper()}*\n"
                        f"Result: *{trade['result']}*\n"
                        f"P&L: `₹{pnl:,.2f}`"
                    )
                    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                    send_phone_notification(msg) 
            except Exception as e: print(f"Monitor error {trade['symbol']}: {e}")
        
        if trades_to_close:
            for t in trades_to_close: active_trades.remove(t)
            save_json(ACTIVE_TRADES_FILE, active_trades)
            save_json(ACCOUNTS_FILE, accounts)
            save_json(HISTORY_FILE, trade_history)
        time.sleep(15)

# --- DAILY RESET & REPORTING LOOP ---
def daily_reset_loop():
    global accounts
    while True:
        now_ist = datetime.now(IST)
        today_str = now_ist.strftime('%Y-%m-%d')
        
        if accounts["last_reset_date"] != today_str:
            yesterday_str = accounts["last_reset_date"]
            daily_pnl = sum(float(t['pnl']) for t in trade_history if t.get('close_time') and yesterday_str in t['close_time'])
            
            msg = (
                f"🌙 *MIDNIGHT RESET*\n"
                f"📊 *Yesterday P&L:* `₹{daily_pnl:,.2f}`\n"
                f"🌐 Macro: `₹{accounts['macro']['balance']:,.2f}`\n"
                f"🇮🇳 Nifty: `₹{accounts['nifty']['balance']:,.2f}`\n"
                f"🇺🇸 NY Bot: `₹{accounts['ny_session']['balance']:,.2f}`"
            )
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
            send_phone_notification(msg) 
            
            for acc in ['macro', 'nifty', 'ny_session']:
                accounts[acc]['daily_trades'] = 0
            accounts['last_reset_date'] = today_str
            save_json(ACCOUNTS_FILE, accounts)
            
        time.sleep(60)

# --- SCANNER LOOP (60s Loop) ---
def background_strategy_loop():
    print("Scanner initialized...")
    while True:
        try:
            if CHAT_ID:
                ny_active = is_ny_session()
                
                for symbol, market_type, account_type in MONITORED_ASSETS:
                    ut = check_ut_bot_strategy(symbol, key_value=2, atr_period=1)
                    sweep = check_sweep_engulfing_strategy(symbol)
                    
                    if account_type == "macro":
                        if ut:
                            if ny_active:
                                execute_trade(symbol, market_type, "ny_session", "NY UT Bot", ut[0], ut[1], ut[2])
                            else:
                                execute_trade(symbol, market_type, "macro", "UT Bot", ut[0], ut[1], ut[2])
                        if sweep:
                            execute_trade(symbol, market_type, "macro", "Sweep", sweep[0], sweep[1], sweep[2])
                            
                    elif account_type == "nifty":
                        if ut: execute_trade(symbol, market_type, "nifty", "UT Bot", ut[0], ut[1], ut[2])
                        if sweep: execute_trade(symbol, market_type, "nifty", "Sweep", sweep[0], sweep[1], sweep[2])
                        
                    time.sleep(0.5)
        except Exception as e: print(f"Scanner error: {e}")
        time.sleep(60)

# --- TELEGRAM COMMANDS ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "💼 *Virtual Fund Manager Active*\n\n📱 Pushbullet Linked.", parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['stats'])
def handle_stats_command(message):
    if not trade_history:
        bot.reply_to(message, "📊 *No trades closed yet.*", parse_mode="Markdown"); return
        
    def calc_stats(acc_name):
        trades = [t for t in trade_history if t['account'] == acc_name]
        wins = sum(1 for t in trades if t['result'] == "WIN")
        losses = sum(1 for t in trades if t['result'] == "LOSS")
        pnl = sum(float(t['pnl']) for t in trades)
        wr = (wins/(wins+losses)*100) if (wins+losses) > 0 else 0
        return wins, losses, pnl, wr

    m_w, m_l, m_p, m_wr = calc_stats("macro")
    n_w, n_l, n_p, n_wr = calc_stats("nifty")
    ny_w, ny_l, ny_p, ny_wr = calc_stats("ny_session")
    
    text = (
        f"📊 *Performance*\n\n"
        f"🌐 Macro: {m_w}W/{m_l}L ({m_wr:.0f}%) ➔ `₹{m_p:,.0f}`\n"
        f"🇮🇳 Nifty: {n_w}W/{n_l}L ({n_wr:.0f}%) ➔ `₹{n_p:,.0f}`\n"
        f"🇺🇸 NY Bot: {ny_w}W/{ny_l}L ({ny_wr:.0f}%) ➔ `₹{ny_p:,.0f}`"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['balance'])
def handle_balance_command(message):
    text = (
        f"🏦 *Accounts*\n\n"
        f"🌐 Macro: `₹{accounts['macro']['balance']:,.2f}` ({accounts['macro']['daily_trades']}/3)\n"
        f"🇮🇳 Nifty: `₹{accounts['nifty']['balance']:,.2f}` ({accounts['nifty']['daily_trades']}/3)\n"
        f"🇺🇸 NY Bot: `₹{accounts['ny_session']['balance']:,.2f}` ({accounts['ny_session']['daily_trades']}/3)\n\n"
        f"⏰ _NY: 6PM to 1:30AM IST_"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['clear'])
def handle_clear_command(message):
    global trade_history, accounts, active_trades
    trade_history, active_trades = [], []
    for acc in ['macro', 'nifty', 'ny_session']:
        accounts[acc]['balance'] = 100000.0
        accounts[acc]['daily_trades'] = 0
    save_json(HISTORY_FILE, trade_history)
    save_json(ACTIVE_TRADES_FILE, active_trades)
    save_json(ACCOUNTS_FILE, accounts)
    bot.reply_to(message, "🗑 *Accounts reset to ₹1,00,000.*", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: True)
def handle_all_other_messages(message):
    bot.reply_to(message, "Use the menu buttons.", reply_markup=get_main_menu_markup())

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data == "cmd_stats": handle_stats_command(call.message)
    elif call.data == "cmd_balance": handle_balance_command(call.message)
    bot.answer_callback_query(call.id)

# --- START THREADS AND FLASK SERVER ---
if __name__ == "__main__":
    threading.Thread(target=background_strategy_loop, daemon=True).start()
    threading.Thread(target=monitor_active_trades, daemon=True).start()
    threading.Thread(target=daily_reset_loop, daemon=True).start()
    threading.Thread(target=lambda: bot.infinity_polling(timeout=20, long_polling_timeout=10), daemon=True).start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
