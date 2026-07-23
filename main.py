import os
import json
import time
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
import pytz
import logging

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
if not TOKEN: raise ValueError("TELEGRAM_BOT_TOKEN not set!")

telebot_logger = logging.getLogger("TeleBot")
telebot_logger.setLevel(logging.CRITICAL)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

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
            payload = {"type": "note", "title": "Trading Bot Alert", "body": clean_text}
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

@app.route("/")
def home(): return "Trading Bot Running OK", 200

@app.route("/ping")
def ping(): return "pong", 200

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
    except Exception as e: print(f"Chart error: {e}")

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

def get_main_menu_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔍 Check Markets Now", callback_data="cmd_check"))
    markup.add(InlineKeyboardButton("📊 Asset Summary", callback_data="cmd_summary"))
    return markup

def get_guide_text():
    return (
        "🤖 *4H TRADING BOT — CONTROL CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Welcome! I monitor multi-asset markets 24/7, execute virtual paper trades with strict 2% risk management, and deliver real-time technical analysis alerts directly to your chat.\n\n"
        "📘 *USER GUIDE — HOW TO USE ME:*\n"
        "▫️ *Auto-Trading:* Sit back! When a setup forms, I automatically execute a paper trade, track P/L, and push an alert here.\n"
        "▫️ `/check` — Instantly scans all 7 assets across both strategies right now.\n"
        "▫️ `/summary` — Opens an overview of tracked assets, live prices, and alert status.\n"
        "▫️ `/stats` — Views the Win Rate and P/L of your virtual accounts.\n"
        "▫️ `/balance` — Views your virtual account balances (Macro, Nifty, NY Session).\n"
        "▫️ *Interactive Buttons:* Tap [ 📈 View Chart ] under any signal to generate a 1-Hour candlestick snapshot!\n"
        "▫️ *Mute Control:* Tap [ 🔇 Mute ] to pause alerts AND paper-trading for noisy assets.\n\n"
        "⚡ *ACTIVE STRATEGIES:*\n"
        "🔵 *Strategy 1:* Sweep + Engulfing (4H Normal & Mother-Child)\n"
        "🟣 *Strategy 2:* UT Bot Signals (15m + 5m Filter | KV:2 | ATR:1)\n\n"
        "📊 *COVERED MARKETS:*\n"
        "🪙 Crypto • 🟡 Gold • 💱 Forex • 📈 Indices (NIFTY/BANK NIFTY)"
    )

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, get_guide_text(), parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['check'])
def handle_check_command(message):
    bot.send_message(message.chat.id, "🔍 *Scanning markets...*", parse_mode="Markdown")
    signals_found = []
    all_assets_text = []
    for symbol, mtype in MONITORED_ASSETS:
        ut = check_ut_bot_strategy(symbol)
        sweep = check_sweep_engulfing_strategy(symbol)
        if ut: signals_found.append((symbol, f"🟢 `{symbol}` ➔ {ut[0]} (`${ut[1]:,.2f}`)"))
        if sweep: signals_found.append((symbol, f"🟢 `{symbol}` ➔ {sweep[0]} (`${sweep[1]:,.2f}`)"))
        if not ut and not sweep: all_assets_text.append(f"⚪ `{symbol}` ({mtype}) ➔ Neutral / No Setup")
        time.sleep(0.5)
    markup = InlineKeyboardMarkup()
    if signals_found:
        body = "\n".join([sig[1] for sig in signals_found]) + "\n" + "\n".join(all_assets_text)
        text = (
            f"🔍 *MARKET SCAN RESULTS*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ *Status:* Scan Completed Successfully\n"
            f"🎯 *Total Analyzed:* 7 Assets\n"
            f"🔥 *Active Signals Found:* {len(signals_found)}\n\n"
            f"{body}"
        )
        markup.add(InlineKeyboardButton(f"📈 View {signals_found[0][0]} Chart", callback_data=f"chart_{signals_found[0][0]}"))
        markup.add(InlineKeyboardButton("📊 Full Asset Summary", callback_data="cmd_summary"))
    else:
        body = "\n".join(all_assets_text)
        text = (
            f"⏳ *MARKET SCAN RESULTS*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚪ *Status:* No Active Setups\n"
            f"🎯 *Analyzed:* All 7 Assets\n\n"
            f"💤 Markets are currently consolidating in neutral zones. No Sweep + Engulfing or UT Bot conditions were triggered."
        )
        markup.add(InlineKeyboardButton("📊 Asset Summary", callback_data="cmd_summary"), InlineKeyboardButton("🔄 Scan Again", callback_data="cmd_check"))
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['summary'])
def handle_summary_command(message):
    summary_lines = []
    for symbol, mtype in MONITORED_ASSETS:
        status = "🔇 Muted" if symbol in muted_assets else "🟢 Active"
        try:
            price = yf.Ticker(symbol).fast_info['lastPrice']
            summary_lines.append(f"{'🪙' if 'Crypto' in mtype else '🟡' if 'Gold' in mtype else '💱' if 'Forex' in mtype else '📈'} `{symbol}` ({mtype}) ➔ {status} | `${price:,.2f}`")
        except:
            summary_lines.append(f"📈 `{symbol}` ({mtype}) ➔ {status}")
        time.sleep(0.5)
    text = (
        f"📊 *LIVE MARKET SUMMARY & MONITORING*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n" +
        "\n".join(summary_lines) +
        f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ All systems operational and monitoring 24/7."
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔍 Run Instant Scan", callback_data="cmd_check"))
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['stats'])
def handle_stats_command(message):
    if not trade_history:
        bot.reply_to(message, "📊 *No closed trades yet to calculate performance.*", parse_mode="Markdown"); return
    def calc(acc):
        t = [x for x in trade_history if x['account'] == acc]
        w = sum(1 for x in t if x['result'] == "WIN")
        l = sum(1 for x in t if x['result'] == "LOSS")
        p = sum(float(x['pnl']) for x in t)
        wr = (w/(w+l)*100) if (w+l) > 0 else 0
        return w, l, p, wr
    mw, ml, mp, mwr = calc("macro")
    nw, nl, np_, nwr = calc("nifty")
    nyw, nyl, nyp, nywr = calc("ny_session")
    text = (
        f"📊 *STRATEGY PERFORMANCE REPORT*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 *Macro (24/7):*\n"
        f"├ {mw}W / {ml}L ({mwr:.0f}% Win Rate)\n"
        f"└ Total P/L: `{'+' if mp>0 else ''}₹{mp:,.2f}`\n\n"
        f"🇮🇳 *Nifty (24/7):*\n"
        f"├ {nw}W / {nl}L ({nwr:.0f}% Win Rate)\n"
        f"└ Total P/L: `{'+' if np_>0 else ''}₹{np_:,.2f}`\n\n"
        f"🇺🇸 *NY Session (UT Bot Only):*\n"
        f"├ {nyw}W / {nyl}L ({nywr:.0f}% Win Rate)\n"
        f"└ Total P/L: `{'+' if nyp>0 else ''}₹{nyp:,.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=get_main_menu_markup())

@bot.message_handler(commands=['balance'])
def handle_balance_command(message):
    text = (
        f"🏦 *VIRTUAL ACCOUNT BALANCES*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 *Macro (Crypto/Forex):*\n"
        f"├ Balance: `₹{accounts['macro']['balance']:,.2f}`\n"
        f"└ Trades Today: `{accounts['macro']['daily_trades']}/3`\n\n"
        f"🇮🇳 *Indices (Nifty):*\n"
        f"├ Balance: `₹{accounts['nifty']['balance']:,.2f}`\n"
        f"└ Trades Today: `{accounts['nifty']['daily_trades']}/3`\n\n"
        f"🇺🇸 *NY Session (UT Bot):*\n"
        f"├ Balance: `₹{accounts['ny_session']['balance']:,.2f}`\n"
        f"└ Trades Today: `{accounts['ny_session']['daily_trades']}/3`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ NY Session Active: 6:00 PM to 1:30 AM IST"
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
    bot.reply_to(message, "🗑 *All virtual accounts reset to ₹1,00,000.*", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: "🚨" not in msg.text and "✅" not in msg.text and "❌" not in msg.text)
def handle_all_other_messages(message):
    try:
        bot.reply_to(message, get_guide_text(), parse_mode="Markdown", reply_markup=get_main_menu_markup())
    except:
        # If Python 3.14 fails to parse the markdown, send it as plain text
        plain_text = get_guide_text().replace("*", "").replace("━━━━━━━━━━━━━━━━━━━━━━", "======================")
        bot.reply_to(message, plain_text, reply_markup=get_main_menu_markup())

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data == "cmd_check": handle_check_command(call.message)
    elif call.data == "cmd_summary": handle_summary_command(call.message)
    elif call.data.startswith("chart_"):
        symbol = call.data.split("_")[1]
        bot.answer_callback_query(call.id, text="Generating dark-mode chart...")
        chart_buf = generate_chart(symbol)
        if chart_buf:
            bot.send_photo(call.message.chat.id, chart_buf, caption=f"📈 `{symbol}` | 1H Dark-Mode Candlestick Snapshot", parse_mode="Markdown")
        else:
            bot.send_message(call.message.chat.id, "❌ Failed to generate chart. Try again later.", parse_mode="Markdown")
    elif call.data.startswith("mute_"):
        symbol = call.data.split("_")[1]
        muted_assets.add(symbol)
        save_json(MUTE_FILE, list(muted_assets))
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"🔊 Unmute {symbol}", callback_data=f"unmute_{symbol}"))
        text = (
            f"🔇 *ALERT STATUS UPDATED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Notifications and paper-trading for `{symbol}` have been paused. You will no longer receive signal alerts or execute virtual trades for this ticker during automated scans."
        )
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=markup)
    elif call.data.startswith("unmute_"):
        symbol = call.data.split("_")[1]
        muted_assets.discard(symbol)
        save_json(MUTE_FILE, list(muted_assets))
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}"))
        text = (
            f"🔊 *ALERT STATUS UPDATED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Notifications and paper-trading for `{symbol}` have been resumed."
        )
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id)

if __name__ == "__main__":
    import threading
    print("Starting background workers...")
    threading.Thread(target=background_strategy_loop, daemon=True).start()
    threading.Thread(target=monitor_active_trades, daemon=True).start()
    threading.Thread(target=daily_reset_loop, daemon=True).start()
    
    print("Starting Web Server and Telegram Bot...")
    app.run(host="0.0.0.0", port=10000, threaded=True)
