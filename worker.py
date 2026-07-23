import os
import time
import json
import threading
import requests
import numpy as np
import pandas as pd
import yfinance as yf
import telebot
from datetime import datetime
import pytz
import logging

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

telebot_logger = logging.getLogger("TeleBot")
telebot_logger.setLevel(logging.CRITICAL)

bot = telebot.TeleBot(TOKEN)
IST = pytz.timezone('Asia/Kolkata')

ACCOUNTS_FILE = "accounts.json"
ACTIVE_TRADES_FILE = "active_trades.json"
HISTORY_FILE = "trade_history.json"
MUTE_FILE = "muted_assets.json"

def load_json(filepath, default):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f: return json.load(f)
    except: pass
    return default

def save_json(filepath, data):
    try:
        with open(filepath, 'w') as f: json.dump(data, f, indent=4)
    except Exception as e: print(f"Error saving {filepath}: {e}")

def send_phone_notification(text):
    try:
        token = os.environ.get("PUSHBULLET_TOKEN")
        if token:
            clean_text = text.replace("*", "").replace("`", "").replace("━", "-").replace("▫️", "-").replace("🪙", "").replace("🟡", "").replace("💱", "").replace("📈", "").replace("⚡", "").replace("🟢", "").replace("🔴", "").replace("🔄", "").replace("💡", "").replace("🔘", "").replace("⏱️", "").replace("🎯", "").replace("🔥", "").replace("⚪", "").replace("💤", "").replace("⚙️", "").replace("💰", "").replace("💸", "").replace("🚨", "").replace("💼", "").replace("├", "|").replace("└", "|")
            requests.post("https://api.pushbullet.com/v2/pushes", json=payload, headers={"Access-Token": token}, timeout=5)
    except: pass

default_accounts = {
    "macro": {"balance": 100000.0, "daily_trades": 0},
    "nifty": {"balance": 100000.0, "daily_trades": 0},
    "ny_session": {"balance": 100000.0, "daily_trades": 0},
    "last_reset_date": datetime.now(IST).strftime('%Y-%m-%d')
}
accounts = load_json(ACCOUNTS_FILE, default_accounts)
active_trades = load_json(ACTIVE_TRADES_FILE, [])
trade_history = load_json(HISTORY_FILE, [])
muted_assets = set(load_json(MUTE_FILE, []))

if "ny_session" not in accounts:
    print("Auto-resetting old data format...")
    for f in [ACCOUNTS_FILE, ACTIVE_TRADES_FILE, HISTORY_FILE, MUTE_FILE]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass
    accounts = default_accounts.copy()
    active_trades, trade_history, muted_assets = [], [], []

MONITORED_ASSETS = [
    ("BTC-USD", "Crypto"), ("GC=F", "Gold"),
    ("EURUSD=X", "Forex"), ("GBPUSD=X", "Forex"), ("USDJPY=X", "Forex"),
    ("^NSEI", "NIFTY 50"), ("^NSEBANK", "BANK NIFTY")
]

def get_account_type(symbol):
    if "NSEI" in symbol or "BANK" in symbol: return "nifty"
    return "macro"

def is_ny_session():
    now = datetime.now(IST)
    return now.hour >= 18 or now.hour <= 1 or (now.hour == 1 and now.minute <= 30)

def calculate_atr(df, period=1):
    high_low = df['High'] - df['Low']
    high_cp = np.abs(df['High'] - df['Close'].shift(1))
    low_cp = np.abs(df['Low'] - df['Close'].shift(1))
    df_tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return df_tr.ewm(alpha=1/period, adjust=False).mean()

def calculate_sl_tp(signal_type, price, atr):
    if "BULLISH" in signal_type:
        return float(price - (atr * 1.5)), float(price + (atr * 3.0))
    else:
        return float(price + (atr * 1.5)), float(price - (atr * 3.0))

def calculate_position_size(account_type, symbol, entry, sl):
    risk_amount = accounts[account_type]["balance"] * 0.02 
    sl_distance = abs(entry - sl)
    if sl_distance == 0: return 0.0
    if account_type == "nifty":
        lot_size = 15 if "BANK" in symbol else 25
        risk_per_lot = sl_distance * lot_size
        if risk_per_lot == 0: return 0.0
        return float((risk_amount / risk_per_lot) * lot_size) 
    return float(risk_amount / sl_distance)

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
        is_inside = (c2['High'] <= c3['High']) and (c2['Low'] >= c3['Low'])
        if not is_inside:
            if (c1['Low'] < c2['Low']) and (c1['Close'] > c2['High']): return ("Bullish Sweep + Engulfing (4H)", float(c1['Close']), atr_val)
            if (c1['High'] > c2['High']) and (c1['Close'] < c2['Low']): return ("Bearish Sweep + Engulfing (4H)", float(c1['Close']), atr_val)
        else:
            if (c1['Low'] < c3['Low']) and (c1['Close'] > c3['High']): return ("Bullish Mother-Child Sweep (4H)", float(c1['Close']), atr_val)
            if (c1['High'] > c3['High']) and (c1['Close'] < c3['Low']): return ("Bearish Mother-Child Sweep (4H)", float(c1['Close']), atr_val)
        return None
    except Exception as e: print(f"Sweep Error {ticker}: {e}")

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
        if is_buy and m5_close > m5_ema: return ("Bullish UT Bot (15m + 5m)", float(src[i]), float(df_15m['xATR'].iloc[i]))
        if is_sell and m5_close < m5_ema: return ("Bearish UT Bot (15m + 5m)", float(src[i]), float(df_15m['xATR'].iloc[i]))
    except Exception as e: print(f"UT Error {ticker}: {e}")

def execute_trade(symbol, market_type, account_type, strat_name, sig_type, price, atr):
    global accounts, active_trades
    sl, tp = calculate_sl_tp(sig_type, price, atr)
    qty = calculate_position_size(account_type, symbol, price, sl)
    if qty <= 0: return False
    if accounts[account_type]["daily_trades"] >= 3: return False
    if any(t['symbol'] == symbol and t['account'] == account_type for t in active_trades): return False
    trade = {
        "id": f"{symbol}_{int(time.time())}", "symbol": symbol, "market": market_type, "account": account_type,
        "strat": strat_name, "type": "LONG" if "BULLISH" in sig_type.upper() else "SHORT",
        "entry": float(price), "sl": float(sl), "tp": float(tp), "qty": float(qty),
        "time": datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')
    }
    active_trades.append(trade)
    accounts[account_type]["daily_trades"] += 1
    save_json(ACTIVE_TRADES_FILE, active_trades)
    save_json(ACCOUNTS_FILE, accounts)
    risk_amt = abs(price - sl) * qty
    direction = "STRONG BULLISH" if "BULLISH" in sig_type.upper() else "STRONG BEARISH"
    tf = "4H" if "Sweep" in strat_name else "15m"
    msg = (
        f"🚨 *HIGH-CONFLUENCE SIGNAL ALERT*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *Asset:* `{symbol}` ({market_type})\n"
        f"⚡ *Strategy:* {strat_name}\n"
        f"🟢 *Direction:* {direction}\n"
        f"⏱️ *Timeframe:* {tf}\n"
        f"📈 *Trigger Price:* `${price:,.2f}`\n"
        f"🕒 *Time:* {trade['time']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 *PAPER TRADE EXECUTED:*\n"
        f"├ Account: `{account_type.upper()}`\n"
        f"├ Stop Loss: `${sl:,.2f}`\n"
        f"├ Take Profit: `${tp:,.2f}`\n"
        f"└ Risk Amount: `₹{risk_amt:,.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Tap below to generate a live candlestick snapshot or silence this ticker."
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"📈 View Chart", callback_data=f"chart_{symbol}"), InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}"))
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=markup)
    send_phone_notification(msg) 
    return True

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
                    status = "WIN" if hit_tp else "LOSS"
                    arrow = "📈" if hit_tp else "📉"
                    money_emoji = "💰" if hit_tp else "💸"
                    pnl_str = f"+₹{pnl:,.2f}" if hit_tp else f"-₹{abs(pnl):,.2f}"
                    current_balance = accounts[trade['account']]["balance"]
                    msg = (
                        f"{emoji} *TRADE CLOSED — {status}*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{'🟢' if is_long else '🔴'} `{trade['symbol']}` ({trade['strat']})\n"
                        f"💼 *Account:* `{trade['account'].upper()}`\n"
                        f"{arrow} *Exit Price:* `${live_price:,.2f}`\n"
                        f"{money_emoji} *P/L:* `{pnl_str}`\n"
                        f"🏦 *New Balance:* `₹{current_balance:,.2f}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                    send_phone_notification(msg) 
                time.sleep(0.5)
            except Exception as e: print(f"Monitor error {trade['symbol']}: {e}")
        if trades_to_close:
            for t in trades_to_close: active_trades.remove(t)
            save_json(ACTIVE_TRADES_FILE, active_trades)
            save_json(ACCOUNTS_FILE, accounts)
            save_json(HISTORY_FILE, trade_history)
        time.sleep(15)

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
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 *Yesterday P/L:* `₹{daily_pnl:,.2f}`\n"
                f"🏦 *Updated Balances:*\n"
                f"├ Macro: `₹{accounts['macro']['balance']:,.2f}`\n"
                f"├ Nifty: `₹{accounts['nifty']['balance']:,.2f}`\n"
                f"└ NY Bot: `₹{accounts['ny_session']['balance']:,.2f}`\n"
                f"🔄 Daily trade limits (3 per account) reset."
            )
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
            send_phone_notification(msg) 
            for acc in ['macro', 'nifty', 'ny_session']: accounts[acc]['daily_trades'] = 0
            accounts['last_reset_date'] = today_str
            save_json(ACCOUNTS_FILE, accounts)
        time.sleep(60)

def background_strategy_loop():
    print("Scanner initialized...")
    while True:
        try:
            if CHAT_ID:
                ny_active = is_ny_session()
                for symbol, market_type in MONITORED_ASSETS:
                    if symbol in muted_assets: time.sleep(0.5); continue
                    ut = check_ut_bot_strategy(symbol)
                    sweep = check_sweep_engulfing_strategy(symbol)
                    acc_type = get_account_type(symbol)
                    if acc_type == "macro":
                        if ut:
                            target_acc = "ny_session" if ny_active else "macro"
                            execute_trade(symbol, market_type, target_acc, "UT Bot Signals", ut[0], ut[1], ut[2])
                        if sweep:
                            execute_trade(symbol, market_type, "macro", "Sweep + Engulfing", sweep[0], sweep[1], sweep[2])
                    elif acc_type == "nifty":
                        if ut: execute_trade(symbol, market_type, "nifty", "UT Bot Signals", ut[0], ut[1], ut[2])
                        if sweep: execute_trade(symbol, market_type, "nifty", "Sweep + Engulfing", sweep[0], sweep[1], sweep[2])
                    time.sleep(0.5)
        except Exception as e: print(f"Scanner error: {e}")
        time.sleep(60)

if __name__ == "__main__":
    print("Starting background workers...")
    threading.Thread(target=background_strategy_loop, daemon=True).start()
    threading.Thread(target=monitor_active_trades, daemon=True).start()
    threading.Thread(target=daily_reset_loop, daemon=True).start()
    print("Worker polling started...")
    bot.infinity_polling(non_stop=True, timeout=60, long_polling_timeout=60)
