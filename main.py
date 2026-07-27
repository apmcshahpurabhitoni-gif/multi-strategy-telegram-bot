import os
import json
import time
import csv
import threading
import gc
from datetime import datetime
from io import BytesIO
from wsgiref.simple_server import make_server

import requests
import numpy as np
import pandas as pd
import yfinance as yf
import pytz
import telebot
import matplotlib
import matplotlib.pyplot as plt
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

matplotlib.use("Agg")
plt.style.use("dark_background")

# ============================================================
#  CONFIG
# ============================================================
TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID")
ATR_MULT_SL    = 1.5
ATR_MULT_TP    = 3.0
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")

# Files
ACCOUNTS_FILE      = "/workspace/accounts.json"
ACTIVE_TRADES_FILE = "/workspace/active_trades.json"
HISTORY_FILE       = "/workspace/trade_history.json"
MUTE_FILE          = "/workspace/muted_assets.json"
TRADE_LOG_CSV      = "/workspace/trade_log.csv"
SENT_SIGNALS_FILE  = "/workspace/sent_signals.json"

# Per-account max trades per day
# - macro: BTC/Gold/Forex UT Bot (during non-NY hours)
# - ny_session: everything during NY hours
# - nifty: NIFTY 50 / BANK NIFTY only
# - sweep_4h: dedicated 4H Sweep + Engulfing strategy
ACCOUNT_LIMITS = {
    "macro":      20,
    "nifty":      3,
    "ny_session": 3,
    "sweep_4h":   3,
}


# Globals
accounts      = {}
active_trades = []
muted_assets  = set()
sent_signals  = {}

_lock        = threading.RLock()
_chart_lock  = threading.RLock()
_price_cache = {}

IST = pytz.timezone("Asia/Kolkata")

def is_market_open(symbol):
    now = datetime.now(IST)
    w, total_min = now.weekday(), now.hour * 60 + now.minute
    if symbol in ("BTC-USD", "GC=F"): return True
    if symbol in ("EURUSD=X", "GBPUSD=X", "USDJPY=X"): return w < 5
    if symbol in ("^NSEI", "^NSEBANK"): return w < 5 and 555 <= total_min <= 930
    return False

# ============================================================
#  UNIFIED MESSAGE TEMPLATES
# ============================================================
BR = "━━━━━━━━━━━━━━━━━━━━━━"
BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

def msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account):
    arrow  = "🟢🟢🟢" if "BULLISH" in sig_type else "🔴🔴🔴"
    label  = "🚀 STRONG BULLISH" if "BULLISH" in sig_type else "💥 STRONG BEARISH"
    dir_   = "LONG 📈" if "BULLISH" in sig_type else "SHORT 📉"
    return (
        f"⚡ *ALERT — HIGH CONFLUENCE SIGNAL*\n"
        f"{BR}\n"
        f"{arrow}  *{label}*\n"
        f"{BR}\n"
        f"🪙 *Asset:*      `{symbol}`\n"
        f"🌐 *Market:*     {mtype}\n"
        f"🎯 *Strategy:*   {strat}\n"
        f"📊 *Direction:*  {dir_}\n"
        f"⏱  *Timeframe:*  {tf}\n"
        f"{BR}\n"
        f"💼 *PAPER TRADE EXECUTED*\n"
        f"{BR}\n"
        f"🏢 *Account:*   `{account.upper()}`\n"
        f"📍 *Entry:*     `${price:,.4f}`\n"
        f"🛑 *Stop Loss:* `${actual_sl:,.4f}`\n"
        f"🎯 *Take Profit:* `${actual_tp:,.4f}`\n"
        f"📦 *Quantity:*  `{qty:.4f}`\n"
        f"💸 *Risk:*      `₹{risk_amt:,.2f}`\n"
        f"{BR2}"
    )

def msg_trade_closed(trade, live, pnl, bal, is_long, hit_tp):
    result = "🎉 WIN" if hit_tp else "💀 LOSS"
    icon   = "✅" if hit_tp else "❌"
    arrow  = "📈" if hit_tp else "📉"
    money  = "💰" if hit_tp else "💸"
    dir_   = "LONG 🟢" if is_long else "SHORT 🔴"
    pnl_s  = f"+₹{pnl:,.2f}" if hit_tp else f"-₹{abs(pnl):,.2f}"
    return (
        f"{icon} *TRADE CLOSED — {result}*\n"
        f"{BR}\n"
        f"{'🟢' if is_long else '🔴'} *{trade['symbol']}*  |  {dir_}\n"
        f"🎯 *Strategy:*   {trade['strat']}\n"
        f"🏢 *Account:*   `{trade['account'].upper()}`\n"
        f"{BR}\n"
        f"📍 *Entry:*     `${trade['entry']:,.4f}`\n"
        f"{arrow} *Exit:*      `${live:,.4f}`\n"
        f"🛑 *SL Hit:*    `${trade['trail_sl']:,.4f}`\n"
        f"🎯 *TP Target:* `${trade['tp']:,.4f}`\n"
        f"{BR}\n"
        f"{money} *P/L:*       `{pnl_s}`\n"
        f"🏦 *Balance:*   `₹{bal:,.2f}`\n"
        f"{BR2}"
    )

def msg_active_trades(trades_list, total_unrealized_pnl):
    body = "\n".join(trades_list)
    return (
        f"📋 *ACTIVE POSITIONS*\n"
        f"{BR}\n"
        f"{body}\n"
        f"{BR}\n"
        f"💵 *Total Unrealized PnL:* `₹{total_unrealized_pnl:,.2f}`\n"
        f"{BR2}"
    )

def msg_no_active_trades():
    return (
        f"📋 *ACTIVE POSITIONS*\n"
        f"{BR}\n"
        f"⚪ No open positions.\n"
        f"{BR2}"
    )

def msg_export_ready(count):
    return (
        f"📁 *Trade Log Exported*\n"
        f"{BR}\n"
        f"Total rows: {count}\n"
        f"{BR2}"
    )

def msg_midnight_reset(day_pnl, macro_bal, nifty_bal, ny_bal, sweep_bal):
    pnl_icon = "📈" if day_pnl >= 0 else "📉"
    pnl_sign = "+" if day_pnl >= 0 else ""
    return (
        f"🌙 *MIDNIGHT RESET*\n"
        f"{BR}\n"
        f"{pnl_icon} *Yesterday P/L:*  `{pnl_sign}₹{day_pnl:,.2f}`\n"
        f"{BR}\n"
        f"🏦 *Account Balances:*\n"
        f"├ 🌐 *Macro:*      `₹{macro_bal:,.2f}`\n"
        f"├ 🇮🇳 *Nifty:*      `₹{nifty_bal:,.2f}`\n"
        f"├ 🇺🇸 *NY Session:* `₹{ny_bal:,.2f}`\n"
        f"└ 🔵 *Sweep 4H:*   `₹{sweep_bal:,.2f}`\n"
        f"{BR}\n"
        f"🔄 *Daily trade limits reset*\n"
        f"🧹 *Signal cache cleaned*\n"
        f"{BR2}"
    )

def msg_guide():
    return (
        f"🤖 *TRADING BOT — COMMAND CENTER*\n"
        f"{BR}\n"
        f"📘 *COMMANDS:*\n"
        f"├ `/check`    🔍  Scan all assets now\n"
        f"├ `/summary`  📊  Live prices & status\n"
        f"├ `/stats`    📈  Win rate & P/L report\n"
        f"├ `/balance`  🏦  Virtual account balances\n"
        f"├ `/active`   📋  View open positions & unrealized PnL\n"
        f"├ `/close`    ✋  Manually close a trade (e.g., `/close BTC-USD`)\n"
        f"├ `/export`   📁  Download trade_log.csv\n"
        f"├ `/clear`    🗑️  Reset all to ₹1,00,000\n"
        f"├ `/indi1`    🔵  Diagnose Strategy 1 (Sweep)\n"
        f"└ `/indi2`    🟣  Diagnose Strategy 2 (UT Bot)\n"
        f"{BR}\n"
        f"⚡ *ACTIVE STRATEGIES:*\n"
        f"├ 🔵 *Sweep + Engulfing*  (4H timeframe)\n"
        f"└ 🟣 *UT Bot Alerts*      (15m + 5m EMA)\n"
        f"{BR}\n"
        f"📊 *MONITORED MARKETS:*\n"
        f"├ 🪙 Crypto   — BTC-USD\n"
        f"├ 🟡 Gold     — GC=F\n"
        f"├ 💱 Forex    — EUR · GBP · JPY\n"
        f"└ 📈 NIFTY    — NIFTY 50 · BANK NIFTY\n"
        f"{BR2}"
    )

def msg_scanning():
    return (
        f"🔍 *SCANNING MARKETS...*\n"
        f"{BR}\n"
        f"⏳ Analyzing all assets across strategies...\n"
        f"🔵 Sweep + Reverse (4H / 1H)\n"
        f"🟣 UT Bot Signals (15m)\n"
        f"{BR}\n"
        f"⏱ Please wait ~15 seconds..."
    )

def msg_scan_results(signals, neutral):
    if signals:
        header = f"🔥 *{len(signals)} SIGNAL{'S' if len(signals)>1 else ''} FOUND*"
        body = "\n".join(signals)
    else:
        header = "⏳ *NO ACTIVE SETUPS*"
        body = "\n".join(neutral) if neutral else "No data available."
    return (
        f"🔍 *MARKET SCAN COMPLETE*\n"
        f"{BR}\n"
        f"{header}\n"
        f"{BR}\n"
        f"{body}\n"
        f"{BR2}"
    )

def msg_summary(lines):
    body = "\n".join(lines)
    return (
        f"📊 *LIVE MARKET SUMMARY*\n"
        f"{BR}\n"
        f"{body}\n"
        f"{BR}\n"
        f"🕐 *Updated:* `{datetime.now(IST).strftime('%H:%M:%S IST')}`\n"
        f"{BR2}"
    )

def msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr, sw, sl, sp, swr):
    def acc_line(emoji, name, w, l, p, wr):
        sign = "+" if p >= 0 else ""
        color = "🟢" if p >= 0 else "🔴"
        return f"{emoji} *{name}*\n" \
               f"   {color} `{w}W / {l}L`  ·  *WR:* `{wr:.0f}%`  ·  *P/L:* `{sign}₹{p:,.2f}`"
    return (
        f"📊 *PERFORMANCE REPORT*\n"
        f"{BR}\n"
        f"{acc_line('🌐','Macro',mw,ml,mp,mwr)}\n"
        f"{BR}\n"
        f"{acc_line('🇮🇳','Nifty',nw,nl,np_,nwr)}\n"
        f"{BR}\n"
        f"{acc_line('🇺🇸','NY Session',nyw,nyl,nyp,nywr)}\n"
        f"{BR}\n"
        f"{acc_line('🔵','Sweep 4H',sw,sl,sp,swr)}\n"
        f"{BR2}"
    )

def msg_balance(macro_bal, nifty_bal, ny_bal, sweep_bal, macro_d, nifty_d, ny_d, sweep_d, macro_lim, nifty_lim, ny_lim, sweep_lim, ny_active, u_pnl):
    ny_icon = "🟢" if ny_active else "🔴"
    ny_text = "ACTIVE" if ny_active else "INACTIVE"
    return (
        f"🏦 *VIRTUAL ACCOUNT BALANCES*\n"
        f"{BR}\n"
        f"🌐 *Macro Account*\n"
        f"   💰 Balance:  `₹{macro_bal:,.2f}`\n"
        f"   💸 Open PnL: `₹{u_pnl.get('macro', 0.0):,.2f}`\n"
        f"   📝 Trades:   `{macro_d}/{macro_lim}`\n"
        f"{BR}\n"
        f"🇮🇳 *Nifty Account*\n"
        f"   💰 Balance:  `₹{nifty_bal:,.2f}`\n"
        f"   💸 Open PnL: `₹{u_pnl.get('nifty', 0.0):,.2f}`\n"
        f"   📝 Trades:   `{nifty_d}/{nifty_lim}`\n"
        f"{BR}\n"
        f"🇺🇸 *NY Session Account*\n"
        f"   💰 Balance:  `₹{ny_bal:,.2f}`\n"
        f"   💸 Open PnL: `₹{u_pnl.get('ny_session', 0.0):,.2f}`\n"
        f"   📝 Trades:   `{ny_d}/{ny_lim}`\n"
        f"{BR}\n"
        f"🔵 *Sweep 4H Account*\n"
        f"   💰 Balance:  `₹{sweep_bal:,.2f}`\n"
        f"   💸 Open PnL: `₹{u_pnl.get('sweep_4h', 0.0):,.2f}`\n"
        f"   📝 Trades:   `{sweep_d}/{sweep_lim}`\n"
        f"{BR}\n"
        f"{ny_icon} *NY Session:* `{ny_text}`\n"
        f"🕐 *Time:* `{datetime.now(IST).strftime('%H:%M:%S IST')}`\n"
        f"{BR2}"
    )

def msg_cleared():
    return (
        f"🗑 *ACCOUNTS RESET*\n"
        f"{BR}\n"
        f"✅ All balances → `₹1,00,000`\n"
        f"✅ All active trades → *Closed*\n"
        f"✅ All trade history → *Wiped*\n"
        f"✅ Daily trade counters → *Reset*\n"
        f"{BR}\n"
        f"🆕 *Fresh start — good luck!* 🍀\n"
        f"{BR2}"
    )

def msg_indi_diagnosing(num):
    name = "Sweep + Engulfing (4H)" if num == 1 else "UT Bot (15m + 5m EMA)"
    color = "🔵" if num == 1 else "🟣"
    return (
        f"{color} *DIAGNOSING STRATEGY {num}*\n"
        f"{BR}\n"
        f"📋 *Strategy:* {name}\n"
        f"⏳ Running deep analysis on all assets...\n"
        f"⏱ Please wait ~20 seconds...\n"
        f"{BR2}"
    )

def msg_indi_debug_header(symbol, strategy_name):
    return (
        f"🔬 *DEBUG: {strategy_name}*\n"
        f"{BR}\n"
        f"🪙 *Asset:* `{symbol}`\n"
    )

def msg_indi_no_signals(num):
    color = "🔵" if num == 1 else "🟣"
    return (
        f"{color} *STRATEGY {num} — NO SIGNALS*\n"
        f"{BR}\n"
        f"⚪ No assets met conditions.\n"
        f"{BR2}"
    )

def msg_indi_executions(num, signals):
    color = "🔵" if num == 1 else "🟣"
    name = "Sweep + Engulfing" if num == 1 else "UT Bot"
    body = "\n".join(signals)
    return (
        f"{color} *STRATEGY {num} — EXECUTIONS*\n"
        f"{BR}\n"
        f"🎯 *{name}*: *{len(signals)} signal{'s' if len(signals)>1 else ''} triggered*\n"
        f"{BR}\n"
        f"{body}\n"
        f"{BR2}"
    )

def msg_error(context, error):
    return (
        f"⚠️ *ERROR — {context}*\n"
        f"{BR}\n"
        f"❌ `{error}`\n"
        f"{BR}\n"
        f"💡 If this persists, try `/clear` or restart the bot.\n"
        f"{BR2}"
    )

def msg_muted(symbol):
    return (
        f"🔇 *ASSET MUTED*\n"
        f"{BR}\n"
        f"🪙 `{symbol}` will *not* trigger new signals.\n"
        f"{BR}\n"
        f"💡 Use the button below to unmute.\n"
        f"{BR2}"
    )

def msg_unmuted(symbol):
    return (
        f"🔊 *ASSET UNMUTED*\n"
        f"{BR}\n"
        f"🪙 `{symbol}` is *back in the scanner*.\n"
        f"{BR}\n"
        f"💡 Signals will now be detected again.\n"
        f"{BR2}"
    )

def msg_chart_failed():
    return (
        f"❌ *CHART GENERATION FAILED*\n"
        f"{BR}\n"
        f"⚠️ Could not fetch or render chart data.\n"
        f"{BR}\n"
        f"💡 The asset may have insufficient data at this timeframe.\n"
        f"{BR2}"
    )

# ============================================================
#  WEB SERVER — keeps Render awake
# ============================================================
def run_web():
    def app(environ, start_response):
        if environ["PATH_INFO"] == "/ping":
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"pong"]
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"Trading Bot OK"]
    srv = make_server("0.0.0.0", 10000, app)
    srv.serve_forever()

threading.Thread(target=run_web, daemon=True).start()

# ============================================================
#  BOT — threaded=True so handlers run in separate threads
# ============================================================
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown", threaded=True)

# ============================================================
#  HELPERS
# ============================================================
def load_json(filepath, default):
    try:
        if os.path.exists(filepath):
            with open(filepath) as f:
                return json.load(f)
    except Exception as e:
        print(f"[ERR] load_json({filepath}): {e}")
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[ERR] save_json({filepath}): {e}")

def safe_send_message(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        print(f"[ERR] Failed to send message: {e}")
        try:
            clean = text.replace("*", "").replace("`", "").replace("_", "")
            bot.send_message(chat_id, f"⚠️ Message formatting error, raw output:\n{clean}", parse_mode=None)
        except Exception as fallback_e:
            print(f"[ERR] Fallback message also failed: {fallback_e}")

def init_accounts():
    global accounts
    defaults = {
        "macro":      {"balance": 100000.0, "daily_trades": 0},
        "nifty":      {"balance": 100000.0, "daily_trades": 0},
        "ny_session": {"balance": 100000.0, "daily_trades": 0},
        "sweep_4h":   {"balance": 100000.0, "daily_trades": 0},
    }
    accounts = load_json(ACCOUNTS_FILE, defaults)

    # Clean up old tracking accounts if they exist
    for key in ["sweep_novol", "utbot_novol"]:
        accounts.pop(key, None)

    for key, val in defaults.items():
        if key not in accounts:
            accounts[key] = val

    today = datetime.now(IST).strftime("%Y-%m-%d")
    if accounts.get("last_reset_date") != today:
        for acc in ["macro", "nifty", "ny_session"]:
            accounts[acc]["daily_trades"] = 0
    accounts["last_reset_date"] = today
    save_json(ACCOUNTS_FILE, accounts)

def is_ny_session():
    h, m = datetime.now(IST).hour, datetime.now(IST).minute
    return h >= 18 or (h == 1 and m <= 30) or h == 0

def is_nifty_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    total_min = now.hour * 60 + now.minute
    return 555 <= total_min <= 930

def get_price(symbol):
    now = time.time()
    if symbol in _price_cache:
        price, ts = _price_cache[symbol]
        if now - ts < 60:
            return price
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df.empty:
            return None
        price = float(df["Close"].iloc[-1])
        _price_cache[symbol] = (price, now)
        del df
        return price
    except Exception:
        return None

def pushbullet_notify(text):
    try:
        token = os.environ.get("PUSHBULLET_TOKEN")
        if not token:
            return
        clean = text.replace("*", "").replace("`", "").replace("_", "")
        requests.post(
            "https://api.pushbullet.com/v2/pushes",
            json={"type": "note", "title": "Trading Bot", "body": clean},
            headers={"Access-Token": token}, timeout=5
        )
    except Exception:
        pass

# ============================================================
#  INDICATORS
# ============================================================
def calculate_atr(df, period=10):
    high_low = df["High"] - df["Low"]
    high_cp  = np.abs(df["High"] - df["Close"].shift(1))
    low_cp   = np.abs(df["Low"]  - df["Close"].shift(1))
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

def normalise_cols(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def get_rsi(df, period=14):
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

# ============================================================
#  STRATEGY 1 — SWEEP + ENGULFING (4H)
# ============================================================
def check_sweep_engulfing(ticker):
    df_target = None
    try:
        df = yf.download(ticker, period="10d", interval="1h",
                         progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            del df
            return None

        is_nifty = "^NSEI" in ticker or "^NSEBANK" in ticker

        if is_nifty:
            df_target = df
        else:
            df_target = (
                df.resample("4h")
                .agg({"Open": "first", "High": "max",
                      "Low": "min", "Close": "last"})
                .dropna()
            )
            del df

        if len(df_target) < 4:
            return None

        curr   = df_target.iloc[-2]  # Candle 2
        mother = df_target.iloc[-3]  # Candle 1
        ts = int(df_target.index[-2].timestamp() * 1000)

        price = float(curr["Close"])

        # Bullish: 2nd candle breaks low of 1st, breaks high of 1st, closes above high of 1st
        if curr["Low"] < mother["Low"] and curr["High"] > mother["High"] and curr["Close"] > mother["High"]:
            sl = float(curr["Low"])
            risk = price - sl
            if risk <= 0: return None
            tp = price + (risk * 2.0)  # 1:2 RR
            if not is_nifty:
                del df_target; gc.collect()
            return ("BULLISH", price, sl, tp, ts)

        # Bearish: 2nd candle breaks high of 1st, breaks low of 1st, closes below low of 1st
        if curr["High"] > mother["High"] and curr["Low"] < mother["Low"] and curr["Close"] < mother["Low"]:
            sl = float(curr["High"])
            risk = sl - price
            if risk <= 0: return None
            tp = price - (risk * 2.0)  # 1:2 RR
            if not is_nifty:
                del df_target; gc.collect()
            return ("BEARISH", price, sl, tp, ts)

        if not is_nifty:
            del df_target; gc.collect()

    except Exception as e:
        print(f"[ERR] Sweep {ticker}: {e}")
    return None

# ============================================================
#  STRATEGY 2 — UT BOT (15m + 5m EMA)
# ============================================================
def check_ut_bot(ticker, kv=2):
    try:
        df_15 = yf.download(ticker, period="3d", interval="15m",
                            progress=False, auto_adjust=True)
        df_5  = yf.download(ticker, period="1d", interval="5m",
                            progress=False, auto_adjust=True)
        df_15 = normalise_cols(df_15)
        df_5  = normalise_cols(df_5)

        if df_15.empty or len(df_15) < 20 or df_5.empty or len(df_5) < 40:
            del df_15, df_5; gc.collect()
            return None



        df_15["xATR"]  = calculate_atr(df_15, 10)
        df_15["nLoss"] = kv * df_15["xATR"]

        src    = df_15["Close"].values
        nLoss  = df_15["nLoss"].values
        ts_arr = np.zeros(len(df_15))
        pos    = np.zeros(len(df_15))

        for i in range(1, len(df_15)):
            prev_ts, prev_src = ts_arr[i - 1], src[i - 1]
            if   src[i] > prev_ts and prev_src > prev_ts:
                ts_arr[i] = max(prev_ts, src[i] - nLoss[i])
            elif src[i] < prev_ts and prev_src < prev_ts:
                ts_arr[i] = min(prev_ts, src[i] + nLoss[i])
            elif src[i] > prev_ts:
                ts_arr[i] = src[i] - nLoss[i]
            else:
                ts_arr[i] = src[i] + nLoss[i]

            if   prev_src < prev_ts and src[i] > ts_arr[i]:
                pos[i] = 1
            elif prev_src > prev_ts and src[i] < ts_arr[i]:
                pos[i] = -1
            else:
                pos[i] = pos[i - 1]

        i = len(df_15) - 2
        is_buy  = (src[i] > ts_arr[i]) and (src[i - 1] <= ts_arr[i - 1])
        is_sell = (src[i] < ts_arr[i]) and (src[i - 1] >= ts_arr[i - 1])

        df_5["EMA50"] = df_5["Close"].ewm(span=50, adjust=False).mean()
        df_15["RSI"]  = get_rsi(df_15)

        m5_close = float(df_5["Close"].iloc[-2])
        m5_ema   = float(df_5["EMA50"].iloc[-2])
        rsi_15   = float(df_15["RSI"].iloc[-2])
        ts       = int(df_15.index[-2].timestamp() * 1000)
        atr_val  = float(df_15["xATR"].iloc[i])

        del df_15, df_5; gc.collect()

        if is_buy and m5_close > m5_ema and rsi_15 < 70:
            return ("BULLISH", float(src[i]), atr_val, ts)
        if is_sell and m5_close < m5_ema and rsi_15 > 30:
            return ("BEARISH", float(src[i]), atr_val, ts)

    except Exception as e:
        print(f"[ERR] UT Bot {ticker}: {e}")
    return None

# ============================================================
#  TRADE EXECUTION
# ============================================================

def calc_sl_tp(sig_type, entry, atr):
    if "BULLISH" in sig_type:
        return entry - (atr * ATR_MULT_SL), entry + (atr * ATR_MULT_TP)
    else:
        return entry + (atr * ATR_MULT_SL), entry - (atr * ATR_MULT_TP)

def calc_position_size(account, entry, sl):
    with _lock:
        balance = accounts[account]["balance"]
    risk = balance * 0.02
    sl_dist = abs(entry - sl)
    if sl_dist == 0:
        return 0.0
    return float(risk / sl_dist)

def execute_trade(symbol, mtype, account, strat, sig_type, price, arg1, arg2, arg3=None):
    global active_trades
    if symbol in muted_assets:
        return

    # Handle overloads:
    # UT Bot: execute_trade(symbol, mtype, account, strat, sig_type, price, atr, ts)
    # Sweep:  execute_trade(symbol, mtype, account, strat, sig_type, price, sl, tp, ts)
    if "Sweep" in strat:
        sl = float(arg1)
        tp = float(arg2)
        ts = arg3
    else:
        atr = float(arg1)
        ts = arg2
        sl, tp = calc_sl_tp(sig_type, price, atr)

    with _lock:
        key = f"{symbol}_{ts}_{sig_type}_{account}"
        if key in sent_signals:
            return
        sent_signals[key] = True
        save_json(SENT_SIGNALS_FILE, sent_signals)

        limit = ACCOUNT_LIMITS.get(account, 3)
        if accounts[account]["daily_trades"] >= limit:
            return
        if any(t["symbol"] == symbol and t["account"] == account for t in active_trades):
            return

        qty = calc_position_size(account, price, sl)
        if qty <= 0:
            return

        tf = "1H" if ("Sweep" in strat and "^NSE" in symbol) else ("4H" if "Sweep" in strat else "15m")

        trade = {
            "id":         f"{symbol}_{int(time.time())}",
            "symbol":     symbol,
            "market":     mtype,
            "account":    account,
            "strat":      strat,
            "type":       "LONG" if "BULLISH" in sig_type else "SHORT",
            "entry":      float(price),
            "sl":         float(sl),
            "tp":         float(tp),
            "qty":        float(qty),
            "trail_sl":   float(sl),
            "ts_trigger": ts,
            "time":       datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        }
        active_trades.append(trade)
        accounts[account]["daily_trades"] += 1
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, active_trades)

    risk_amt = abs(price - sl) * qty

    msg = msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, sl, tp, qty, risk_amt, account)

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📈 Chart", callback_data=f"chart_{symbol}"),
        InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}")
    )
    safe_send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=markup)
    pushbullet_notify(msg)
    direction = "LONG" if "BULLISH" in sig_type else "SHORT"
    print(f"[TRADE] {direction} {symbol} @ {price}")

# ============================================================
#  MONITOR TRADES
# ============================================================
def monitor_trades():
    global active_trades

    while True:
        if not active_trades:
            time.sleep(15)
            continue

        to_close = []

        with _lock:
            trades_copy = list(active_trades)

        for trade in trades_copy:
            try:
                df = yf.download(trade["symbol"], period="1d",
                                 interval="1m", progress=False, auto_adjust=True)
                df = normalise_cols(df)
                if df.empty:
                    del df
                    continue

                live    = float(df["Close"].iloc[-1])
                is_long = trade["type"] == "LONG"
                del df

                with _lock:
                    if trade not in active_trades:
                        continue # ensure trade hasn't been closed by another thread/command
                    if is_long:
                        profit_pct = (live - trade["entry"]) / trade["entry"] * 100
                    else:
                        profit_pct = (trade["entry"] - live) / trade["entry"] * 100

                    # Dynamic trailing stop — once profit >= 1%, lock in 50% of unrealized gain.
                    # The max()/min() guard ensures SL only ever ratchets in the profitable direction,
                    # so existing positions with the old static trail keep their floor.
                    if profit_pct >= 1.0:
                        old_trail = trade["trail_sl"]
                        if is_long:
                            new_sl = trade["entry"] + (live - trade["entry"]) * 0.5
                            trade["trail_sl"] = max(trade["trail_sl"], new_sl)
                        else:
                            new_sl = trade["entry"] - (trade["entry"] - live) * 0.5
                            trade["trail_sl"] = min(trade["trail_sl"], new_sl)

                        if trade["trail_sl"] != old_trail:
                            save_json(ACTIVE_TRADES_FILE, active_trades)

                    hit_tp = (is_long and live >= trade["tp"]) or (not is_long and live <= trade["tp"])
                    hit_sl = (is_long and live <= trade["trail_sl"]) or (not is_long and live >= trade["trail_sl"])

                    if not (hit_tp or hit_sl):
                        continue

                    pnl = abs(trade["tp"] - trade["entry"]) * trade["qty"] if hit_tp \
                        else -(abs(trade["entry"] - trade["trail_sl"]) * trade["qty"])

                    accounts[trade["account"]]["balance"] += pnl
                    trade["exit_price"] = live
                    trade["pnl"]        = float(pnl)
                    trade["result"]     = "WIN" if hit_tp else "LOSS"
                    trade["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
                    to_close.append(trade)
                    save_json(ACCOUNTS_FILE, accounts)

                    try:
                        history = load_json(HISTORY_FILE, [])
                        history.append(trade)
                        save_json(HISTORY_FILE, history)

                        import csv
                        import os
                        file_exists = os.path.isfile(TRADE_LOG_CSV)
                        with open(TRADE_LOG_CSV, 'a', newline='') as csvfile:
                            fieldnames = ['close_time', 'symbol', 'account', 'strategy', 'type', 'entry', 'exit_price', 'sl', 'tp', 'qty', 'pnl', 'result']
                            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                            if not file_exists:
                                writer.writeheader()
                            writer.writerow({
                                'close_time': trade['close_time'],
                                'symbol': trade['symbol'],
                                'account': trade['account'],
                                'strategy': trade['strat'],
                                'type': trade['type'],
                                'entry': trade['entry'],
                                'exit_price': trade['exit_price'],
                                'sl': trade['sl'],
                                'tp': trade['tp'],
                                'qty': trade['qty'],
                                'pnl': trade['pnl'],
                                'result': trade['result']
                            })
                    except Exception as e:
                        print(f"[ERR] Log trade: {e}")

                with _lock:
                    bal = accounts[trade["account"]]["balance"]

                msg = msg_trade_closed(trade, live, pnl, bal, is_long, hit_tp)
                safe_send_message(CHAT_ID, msg, parse_mode="Markdown")
                pushbullet_notify(msg)
                pnl_str = f"+₹{pnl:,.2f}" if hit_tp else f"-₹{abs(pnl):,.2f}"
                print(f"[CLOSE] {trade['symbol']} {trade['result']} {pnl_str}")
                time.sleep(0.3)

            except Exception as e:
                print(f"[ERR] Monitor {trade['symbol']}: {e}")
                safe_send_message(CHAT_ID, msg_error(f"Monitor {trade['symbol']}", str(e)), parse_mode="Markdown")

        if to_close:
            with _lock:
                for t in to_close:
                    try:
                        active_trades.remove(t)
                    except ValueError:
                        pass
                save_json(ACTIVE_TRADES_FILE, active_trades)

        time.sleep(15)

# ============================================================
#  SCANNER
# ============================================================
MONITORED = [
    ("BTC-USD",    "Crypto"),
    ("GC=F",       "Gold"),
    ("EURUSD=X",   "Forex"),
    ("GBPUSD=X",   "Forex"),
    ("USDJPY=X",   "Forex"),
    ("^NSEI",      "NIFTY 50"),
    ("^NSEBANK",   "BANK NIFTY"),
]

def get_account(symbol):
    return "nifty" if ("NSEI" in symbol or "BANK" in symbol) else "macro"

def scanner_loop():
    print("[SCANNER] Started")
    while True:
        try:
            ny_active = is_ny_session()

            for symbol, mtype in MONITORED:
                with _lock:
                    if symbol in muted_assets or not is_market_open(symbol):
                        continue

                account = get_account(symbol)
                if account == "nifty" and not is_nifty_market_open():
                    continue


                ut = check_ut_bot(symbol)
                if ut:
                    if account == "nifty":
                        target = "nifty"
                    else:
                        target = "ny_session" if is_ny_session() else "macro"
                    execute_trade(symbol, mtype, target, "UT Bot Signals", ut[0], ut[1], ut[2], ut[3])

                sweep = check_sweep_engulfing(symbol)
                if sweep:
                    execute_trade(symbol, mtype, "sweep_4h", "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])

                time.sleep(0.5)

            gc.collect()

        except Exception as e:
            print(f"[ERR] Scanner: {e}")
            safe_send_message(CHAT_ID, msg_error("Scanner Loop", str(e)), parse_mode="Markdown")

        time.sleep(60)

# ============================================================
#  DAILY RESET
# ============================================================
def daily_reset_loop():
    last_reset = datetime.now(IST).strftime('%Y-%m-%d')
    while True:
        now = datetime.now(IST)
        today_str = now.strftime("%Y-%m-%d")

        if last_reset != today_str:
            try:
                with _lock:
                    for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
                        if acc in accounts:
                            accounts[acc]["daily_trades"] = 0
                    accounts["last_reset_date"] = today_str
                    save_json(ACCOUNTS_FILE, accounts)

                    global sent_signals
                    if len(sent_signals) > 500:
                        keys = list(sent_signals.keys())
                        sent_signals = {k: sent_signals[k] for k in keys[-500:]}
                        save_json(SENT_SIGNALS_FILE, sent_signals)

                    history = load_json(HISTORY_FILE, [])
                    day_trades = [t for t in history if t.get("close_time", "").startswith(last_reset)] if last_reset else []
                    day_pnl = sum(float(t["pnl"]) for t in day_trades)

                    if len(history) > 500:
                        history = history[-500:]
                        save_json(HISTORY_FILE, history)

                    msg = msg_midnight_reset(
                        day_pnl,
                        accounts["macro"]["balance"],
                        accounts["nifty"]["balance"],
                        accounts["ny_session"]["balance"],
                        accounts.get("sweep_4h", {"balance": 100000.0})["balance"]
                    )
                safe_send_message(CHAT_ID, msg, parse_mode="Markdown")
            except Exception as e:
                print(f"[ERR] Daily reset: {e}")

            last_reset = today_str
            gc.collect()

        time.sleep(60)

# ============================================================
#  TELEGRAM HANDLERS
# ============================================================
def menu_markup():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🔍 Check Markets",  callback_data="cmd_check"))
    m.add(InlineKeyboardButton("📊 Asset Summary",   callback_data="cmd_summary"))
    return m

@bot.message_handler(commands=["start", "help"])
def cmd_start(m):
    safe_send_message(m.chat.id, msg_guide(), parse_mode="Markdown", reply_markup=menu_markup())

@bot.message_handler(commands=["check"])
def cmd_check(m):
    chat_id = m.chat.id
    safe_send_message(chat_id, msg_scanning())

    def run_scan():
        try:
            signals, neutral = [], []
            for symbol, mtype in MONITORED:
                ut    = check_ut_bot(symbol)
                sweep = check_sweep_engulfing(symbol)
                if ut:
                    signals.append(f"🟢 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}*  `${ut[1]:,.4f}`")
                if sweep:
                    signals.append(f"🟢 `{symbol}` ➔ 🔵 Sweep *{sweep[0]}*  `${sweep[1]:,.4f}`")
                else:
                    neutral.append(f"⚪ `{symbol}` — No Setup")
                time.sleep(0.3)
                gc.collect()

            safe_send_message(chat_id, msg_scan_results(signals, neutral), parse_mode="Markdown")
        except Exception as e:
            safe_send_message(chat_id, msg_error("Market Scan", str(e)), parse_mode="Markdown")

    threading.Thread(target=run_scan, daemon=True).start()

@bot.message_handler(commands=["summary"])
def cmd_summary(m):
    try:
        lines = []
        for symbol, mtype in MONITORED:
            is_muted = symbol in muted_assets
            status = "🔇 Muted" if is_muted else "🟢 Active"
            price = get_price(symbol)
            if price:
                lines.append(f"{'🔴' if is_muted else '🟢'} `{symbol}`  ·  {mtype}  ·  `${price:,.4f}`  ·  {status}")
            else:
                lines.append(f"{'🔴' if is_muted else '🟢'} `{symbol}`  ·  {mtype}  ·  {status}")
            time.sleep(0.3)

        safe_send_message(m.chat.id, msg_summary(lines), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Asset Summary", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    try:
        history = load_json(HISTORY_FILE, [])

        def stats(acc):
            ts = [x for x in history if x["account"] == acc]
            w  = [x for x in ts if x["result"] == "WIN"]
            l  = [x for x in ts if x["result"] == "LOSS"]
            p  = sum(float(x["pnl"]) for x in ts)
            wr = len(w) / (len(w) + len(l)) * 100 if (w or l) else 0
            return len(w), len(l), p, wr

        mw, ml, mp, mwr   = stats("macro")
        nw, nl, np_, nwr  = stats("nifty")
        nyw, nyl, nyp, nywr = stats("ny_session")
        sw, sl, sp, swr   = stats("sweep_4h")

        safe_send_message(m.chat.id,
            msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr, sw, sl, sp, swr),
            parse_mode="Markdown", reply_markup=menu_markup())
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Performance Stats", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["active"])
def cmd_active(m):
    try:
        with _lock:
            trades = list(active_trades)

        if not trades:
            safe_send_message(m.chat.id, msg_no_active_trades(), parse_mode="Markdown")
            return

        trades_list = []
        total_pnl = 0.0
        prices = {}

        for t in trades:
            symbol = t["symbol"]
            if symbol not in prices:
                prices[symbol] = get_price(symbol)
                time.sleep(0.3)

            live = prices[symbol]
            if not live:
                continue

            is_long = t["type"] == "LONG"
            if is_long:
                pnl = (live - t["entry"]) * t["qty"]
            else:
                pnl = (t["entry"] - live) * t["qty"]

            total_pnl += pnl

            arrow = "📈" if is_long else "📉"
            trades_list.append(
                f"🪙 `{symbol}` | `{t['account']}` | {t['type']} {arrow}\n"
                f"   📍 Entry: `₹{t['entry']:,.4f}` | 🛑 SL: `₹{t['trail_sl']:,.4f}` | 🎯 TP: `₹{t['tp']:,.4f}`\n"
                f"   📦 Qty: `{t['qty']:.4f}` | 💰 U.PnL: `₹{pnl:,.2f}`\n"
            )

        safe_send_message(m.chat.id, msg_active_trades(trades_list, total_pnl), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Active Trades", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["close"])
def cmd_close(m):
    try:
        parts = m.text.split()
        if len(parts) < 2:
            safe_send_message(m.chat.id, msg_error("Manual Close", "Provide a symbol. Example: /close BTC-USD"), parse_mode="Markdown")
            return

        target_symbol = parts[1].upper()

        with _lock:
            trade_to_close = next((t for t in active_trades if t["symbol"].upper() == target_symbol), None)

            if not trade_to_close:
                safe_send_message(m.chat.id, msg_error("Manual Close", f"No active trade found for {target_symbol}"), parse_mode="Markdown")
                return

        live = get_price(target_symbol)
        if not live:
            safe_send_message(m.chat.id, msg_error("Manual Close", f"Could not fetch current price for {target_symbol}"), parse_mode="Markdown")
            return

        is_long = trade_to_close["type"] == "LONG"
        pnl = (live - trade_to_close["entry"]) * trade_to_close["qty"] if is_long else (trade_to_close["entry"] - live) * trade_to_close["qty"]
        hit_tp = pnl > 0

        with _lock:
            if trade_to_close not in active_trades:
                return # Already closed
            active_trades.remove(trade_to_close)
            accounts[trade_to_close["account"]]["balance"] += pnl
            trade_to_close["exit_price"] = live
            trade_to_close["pnl"] = float(pnl)
            trade_to_close["result"] = "MANUAL_CLOSE"
            trade_to_close["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

            save_json(ACCOUNTS_FILE, accounts)
            save_json(ACTIVE_TRADES_FILE, active_trades)

            history = load_json(HISTORY_FILE, [])
            history.append(trade_to_close)
            save_json(HISTORY_FILE, history)

            import csv
            import os
            file_exists = os.path.isfile(TRADE_LOG_CSV)
            with open(TRADE_LOG_CSV, 'a', newline='') as csvfile:
                fieldnames = ['close_time', 'symbol', 'account', 'strategy', 'type', 'entry', 'exit_price', 'sl', 'tp', 'qty', 'pnl', 'result']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    'close_time': trade_to_close['close_time'],
                    'symbol': trade_to_close['symbol'],
                    'account': trade_to_close['account'],
                    'strategy': trade_to_close['strat'],
                    'type': trade_to_close['type'],
                    'entry': trade_to_close['entry'],
                    'exit_price': trade_to_close['exit_price'],
                    'sl': trade_to_close['sl'],
                    'tp': trade_to_close['tp'],
                    'qty': trade_to_close['qty'],
                    'pnl': trade_to_close['pnl'],
                    'result': trade_to_close['result']
                })

        msg = msg_trade_closed(trade_to_close, live, float(pnl), accounts[trade_to_close["account"]]["balance"], is_long, hit_tp)
        safe_send_message(m.chat.id, msg, parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Manual Close", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["export"])
def cmd_export(m):
    try:
        import os
        import csv
        if not os.path.exists(TRADE_LOG_CSV) or os.path.getsize(TRADE_LOG_CSV) == 0:
            safe_send_message(m.chat.id, msg_error("Export", "No trade log available yet."), parse_mode="Markdown")
            return

        with open(TRADE_LOG_CSV, 'r') as f:
            count = sum(1 for row in f) - 1 # exclude header

        with open(TRADE_LOG_CSV, 'rb') as doc:
            bot.send_document(m.chat.id, doc, caption=msg_export_ready(count), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Export", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["balance"])
def cmd_balance(m):
    try:
        with _lock:
            macro_bal  = accounts["macro"]["balance"]
            nifty_bal  = accounts["nifty"]["balance"]
            ny_bal     = accounts["ny_session"]["balance"]
            sweep_bal  = accounts.get("sweep_4h", {"balance": 100000.0})["balance"]
            macro_d    = accounts["macro"]["daily_trades"]
            nifty_d    = accounts["nifty"]["daily_trades"]
            ny_d       = accounts["ny_session"]["daily_trades"]
            sweep_d    = accounts.get("sweep_4h", {"daily_trades": 0})["daily_trades"]
            ny_active  = is_ny_session()
            trades = list(active_trades)

        prices = {}
        u_pnl = {"macro": 0.0, "nifty": 0.0, "ny_session": 0.0, "sweep_4h": 0.0}

        for t in trades:
            sym = t["symbol"]
            if sym not in prices:
                prices[sym] = get_price(sym)
                time.sleep(0.3)

            live = prices[sym]
            if live:
                if t["type"] == "LONG":
                    u_pnl[t["account"]] += (live - t["entry"]) * t["qty"]
                else:
                    u_pnl[t["account"]] += (t["entry"] - live) * t["qty"]

        safe_send_message(m.chat.id,
            msg_balance(
                macro_bal, nifty_bal, ny_bal, sweep_bal,
                macro_d, nifty_d, ny_d, sweep_d,
                ACCOUNT_LIMITS["macro"], ACCOUNT_LIMITS["nifty"],
                ACCOUNT_LIMITS["ny_session"], ACCOUNT_LIMITS["sweep_4h"],
                ny_active, u_pnl
            ),
            parse_mode="Markdown", reply_markup=menu_markup())
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Balance Query", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["clear"])
def cmd_clear(m):
    global active_trades
    try:
        with _lock:
            active_trades = []
            for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
                accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
            save_json(ACCOUNTS_FILE, accounts)
            save_json(ACTIVE_TRADES_FILE, [])
            save_json(HISTORY_FILE, [])
            global sent_signals
            sent_signals = {}
            save_json(SENT_SIGNALS_FILE, sent_signals)

        safe_send_message(m.chat.id, msg_cleared(), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Account Clear", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["indi1"])
def cmd_indi1(m):
    chat_id = m.chat.id
    safe_send_message(chat_id, msg_indi_diagnosing(1))
    def run_diag():
        try:
            results = []
            for symbol, mtype in MONITORED:
                if not is_market_open(symbol): continue
                res = check_sweep_engulfing(symbol)
                if res:
                    sig = res[0]
                    price = res[1]
                    icon = "🟢" if "BULLISH" in sig else "🔴"
                    results.append(f"{icon} `{symbol}`  →  {sig}  @ {price:.2f}")
                else:
                    results.append(f"⚪ `{symbol}`  →  No Setup")
                time.sleep(0.5)

            has_signals = any("BULLISH" in r or "BEARISH" in r for r in results)

            if has_signals:
                full_text = "\n".join(results)
                for i in range(0, len(full_text), 4000):
                    safe_send_message(chat_id, full_text[i:i+4000], parse_mode="Markdown")
            else:
                safe_send_message(chat_id, msg_indi_no_signals(1), parse_mode="Markdown")
        except Exception as e:
            safe_send_message(chat_id, msg_error("Strategy 1 Diagnosis", str(e)), parse_mode="Markdown")
    threading.Thread(target=run_diag, daemon=True).start()

@bot.message_handler(commands=["indi2"])
def cmd_indi2(m):
    chat_id = m.chat.id
    safe_send_message(chat_id, msg_indi_diagnosing(2))
    def run_diag():
        try:
            results = []
            for symbol, mtype in MONITORED:
                if not is_market_open(symbol): continue
                res = check_ut_bot(symbol)
                if res:
                    sig = res[0]
                    price = res[1]
                    icon = "🟢" if "BULLISH" in sig else "🔴"
                    results.append(f"{icon} `{symbol}`  →  {sig}  @ {price:.2f}")
                else:
                    results.append(f"⚪ `{symbol}`  →  No Setup")
                time.sleep(0.5)

            has_signals = any("BULLISH" in r or "BEARISH" in r for r in results)

            if has_signals:
                full_text = "\n".join(results)
                for i in range(0, len(full_text), 4000):
                    safe_send_message(chat_id, full_text[i:i+4000], parse_mode="Markdown")
            else:
                safe_send_message(chat_id, msg_indi_no_signals(2), parse_mode="Markdown")
        except Exception as e:
            safe_send_message(chat_id, msg_error("Strategy 2 Diagnosis", str(e)), parse_mode="Markdown")
    threading.Thread(target=run_diag, daemon=True).start()

@bot.message_handler(func=lambda m: True)
def cmd_fallback(m):
    if m.text.startswith("/"):
        return
    safe_send_message(m.chat.id, msg_guide(), parse_mode="Markdown", reply_markup=menu_markup())

# ============================================================
#  CALLBACK HANDLERS
# ============================================================
@bot.callback_query_handler(func=lambda c: True)
def handle_cb(c):
    try:
        if c.data == "cmd_check":
            cmd_check(c.message)
        elif c.data == "cmd_summary":
            cmd_summary(c.message)




        elif c.data.startswith("chart_"):
            sym = c.data.split("_", 1)[1]
            bot.answer_callback_query(c.id, text="Generating chart...")
            buf = generate_chart(sym)
            if buf:
                bot.send_photo(c.message.chat.id, buf, caption=f"📈 `{sym}` | 1H Chart")
            else:
                safe_send_message(c.message.chat.id, msg_chart_failed())
        elif c.data.startswith("mute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.add(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(
                InlineKeyboardButton(f"🔊 Unmute {sym}", callback_data=f"unmute_{sym}"))
            bot.edit_message_text(
                msg_muted(sym), c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=m)
        elif c.data.startswith("unmute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.discard(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(
                InlineKeyboardButton(f"🔇 Mute {sym}", callback_data=f"mute_{sym}"))
            bot.edit_message_text(
                msg_unmuted(sym), c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=m)
    except Exception as e:
        print(f"[ERR] Callback: {e}")
    bot.answer_callback_query(c.id)

# ============================================================
#  CHART GENERATION
# ============================================================
def generate_chart(symbol, tf="1h"):
    with _chart_lock:
        try:
            df = yf.download(symbol, period="3d", interval=tf,
                              progress=False, auto_adjust=True)
            df = normalise_cols(df)
            if df.empty:
                return None

            fig, ax = plt.subplots(figsize=(10, 5), facecolor="#0d1117", dpi=50)
            ax.set_facecolor("#0d1117")

            # Vectorized candlestick drawing — replaces the O(n) iterrows loop
            # with O(1) vlines + bar calls, so the chart is fast even on
            # higher-resolution frames.
            x       = np.arange(len(df))
            close   = df["Close"].to_numpy()
            open_   = df["Open"].to_numpy()
            high    = df["High"].to_numpy()
            low     = df["Low"].to_numpy()
            colors  = np.where(close >= open_, "#00ff88", "#ff4444")

            # Wicks (high-low)
            ax.vlines(x, low, high, color=colors, linewidth=1)

            # Bodies (open-close)
            body_h  = np.abs(close - open_) + 1e-8
            body_b  = np.minimum(open_, close)
            ax.bar(x, body_h, bottom=body_b, width=0.6, color=colors, linewidth=0)

            ax.set_title(f"{symbol} | {tf.upper()}", color="white", fontsize=12, fontweight="bold")
            ax.tick_params(colors="gray", labelsize=6)
            for spine in ax.spines.values():
                spine.set_color("#30363d")
            ax.grid(True, color="#21262d", linestyle="--", linewidth=0.5)
            plt.tight_layout()

            buf = BytesIO()
            plt.savefig(buf, format="png", facecolor="#0d1117")
            buf.seek(0)
            plt.close(fig)
            del df
            return buf

        except Exception as e:
            print(f"[ERR] Chart {symbol}: {e}")
            plt.close()
            return None

# ============================================================
#  BOOT
# ============================================================
if __name__ == "__main__":
    if not CHAT_ID:
        print("FATAL: CHAT_ID not set!")
        exit(1)

    init_accounts()

    muted_assets.update(load_json(MUTE_FILE, []))
    active_trades = load_json(ACTIVE_TRADES_FILE, [])
    sent_signals = load_json(SENT_SIGNALS_FILE, {})

    print("=" * 50)
    print("  Trading Bot Starting...")
    print(f"  Macro:      ₹{accounts['macro']['balance']:,.2f}")
    print(f"  Nifty:      ₹{accounts['nifty']['balance']:,.2f}")
    print(f"  NY Session: ₹{accounts['ny_session']['balance']:,.2f}")
    print(f"  Web server: :10000/ping")
    print("=" * 50)

    threading.Thread(target=scanner_loop,       daemon=True).start()
    threading.Thread(target=monitor_trades,      daemon=True).start()
    threading.Thread(target=daily_reset_loop,  daemon=True).start()

    print("[BOT] Connecting to Telegram...")
    # Exponential backoff on polling crash — fixed retry was 5s flat which
    # would tight-loop on a real outage. Now we back off up to 5 minutes.
    backoff = 5
    while True:
        try:
            bot.polling(timeout=60, long_polling_timeout=10)
            backoff = 5  # reset on clean exit
        except Exception as e:
            print(f"[ERR] Polling crashed: {e}")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
