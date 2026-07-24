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
MIN_VOLATILITY = 0.3

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")

# Files
ACCOUNTS_FILE      = "accounts.json"
ACTIVE_TRADES_FILE = "active_trades.json"
HISTORY_FILE       = "trade_history.json"
MUTE_FILE          = "muted_assets.json"
TRADE_LOG_CSV      = "trade_log.csv"
SENT_SIGNALS_FILE  = "sent_signals.json"
SETTINGS_FILE      = "settings.json"

# Globals
accounts      = {}
active_trades = []
muted_assets  = set()
sent_signals  = {}

_lock        = threading.Lock()
_chart_lock  = threading.Lock()
_price_cache = {}

IST = pytz.timezone("Asia/Kolkata")

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

def msg_midnight_reset(day_pnl, macro_bal, nifty_bal, ny_bal):
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
        f"└ 🇺🇸 *NY Session:* `₹{ny_bal:,.2f}`\n"
        f"{BR}\n"
        f"🔄 *Daily trade limits reset to 0/3*\n"
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
        f"├ `/clear`    🗑️  Reset all to ₹1,00,000\n"
        f"├ `/vol`      ⚙️  Toggle Volatility Filter\n"
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


def msg_volatility(is_enabled):
    status = "🟢 ON" if is_enabled else "🔴 OFF"
    desc = "Signals failing the volatility check will only go to NO-VOL accounts." if is_enabled else "ALL signals will go to main accounts regardless of volatility."
    return (
        f"⚙️ *VOLATILITY FILTER SETTINGS*\n"
        f"{BR}\n"
        f"📊 *Current Status:* `{status}`\n"
        f"{BR}\n"
        f"💡 {desc}\n"
        f"{BR2}"
    )

def msg_scanning():
    return (
        f"🔍 *SCANNING MARKETS...*\n"
        f"{BR}\n"
        f"⏳ Analyzing all assets across strategies...\n"
        f"🔵 Sweep + Engulfing (4H)\n"
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

def msg_summary(lines, vol_filter_on):
    body = "\n".join(lines)
    vol_status = "🟢 ON" if vol_filter_on else "🔴 OFF"
    return (
        f"📊 *LIVE MARKET SUMMARY*\n"
        f"{BR}\n"
        f"{body}\n"
        f"{BR}\n"
        f"⚙️ *Volatility Filter:* `{vol_status}`\n"
        f"🕐 *Updated:* `{datetime.now(IST).strftime('%H:%M:%S IST')}`\n"
        f"{BR2}"
    )

def msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr):
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
        f"{BR2}"
    )

def msg_balance(macro_bal, nifty_bal, ny_bal, macro_d, nifty_d, ny_d, ny_active, vol_filter_on):
    ny_icon = "🟢" if ny_active else "🔴"
    ny_text = "ACTIVE" if ny_active else "INACTIVE"
    return (
        f"🏦 *VIRTUAL ACCOUNT BALANCES*\n"
        f"{BR}\n"
        f"🌐 *Macro Account*\n"
        f"   💰 Balance:  `₹{macro_bal:,.2f}`\n"
        f"   📝 Trades:   `{macro_d}/3`\n"
        f"{BR}\n"
        f"🇮🇳 *Nifty Account*\n"
        f"   💰 Balance:  `₹{nifty_bal:,.2f}`\n"
        f"   📝 Trades:   `{nifty_d}/3`\n"
        f"{BR}\n"
        f"🇺🇸 *NY Session Account*\n"
        f"   💰 Balance:  `₹{ny_bal:,.2f}`\n"
        f"   📝 Trades:   `{ny_d}/3`\n"
        f"{BR}\n"
        f"{ny_icon} *NY Session:* `{ny_text}`\n"
        f"⚙️ *Volatility Filter:* `{'🟢 ON' if vol_filter_on else '🔴 OFF'}`\n"
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
    name = "Sweep + Engulfing" if num == 1 else "UT Bot"
    return (
        f"{color} *STRATEGY {num} — NO SIGNALS*\n"
        f"{BR}\n"
        f"⏳ *{name}*: No assets met trigger conditions.\n"
        f"{BR}\n"
        f"💡 *Possible reasons:*\n"
        f"├ ⚪ Volatility below `{MIN_VOLATILITY}%` threshold\n"
        f"├ ⚪ No sweep/engulfing pattern detected\n"
        f"├ ⚪ UT Bot crossover not aligned with EMA/RSI\n"
        f"└ ⚪ Signal already sent (dedup active)\n"
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
    except Exception:
        pass
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

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


def init_settings():
    global bot_settings
    defaults = {"volatility_filter": True}
    bot_settings = load_json(SETTINGS_FILE, defaults)
    save_json(SETTINGS_FILE, bot_settings)

def init_accounts():
    global accounts
    defaults = {
        "macro":      {"balance": 100000.0, "daily_trades": 0},
        "nifty":      {"balance": 100000.0, "daily_trades": 0},
        "ny_session": {"balance": 100000.0, "daily_trades": 0},
        "sweep_novol": {"balance": 100000.0, "daily_trades": 0},
        "utbot_novol": {"balance": 100000.0, "daily_trades": 0},
    }
    accounts = load_json(ACCOUNTS_FILE, defaults)
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if accounts.get("last_reset_date") != today:
        for acc in ["macro", "nifty", "ny_session", "sweep_novol", "utbot_novol"]:
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
        del df; gc.collect()
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
    try:
        df = yf.download(ticker, period="10d", interval="1h",
                         progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            del df; gc.collect()
            return None

        vol_ok = True
        try:
            atr   = float(calculate_atr(df, 10).iloc[-2])
            price = float(df["Close"].iloc[-1])
            if (atr / price * 100) < MIN_VOLATILITY:
                vol_ok = False
        except Exception:
            pass

        df_4h = (
            df.resample("4h")
            .agg({"Open": "first", "High": "max",
                  "Low": "min", "Close": "last"})
            .dropna()
        )
        del df; gc.collect()

        if len(df_4h) < 4:
            return None

        df_4h["ATR"] = calculate_atr(df_4h, 10)
        atr = float(df_4h["ATR"].iloc[-2])

        curr   = df_4h.iloc[-2]
        mother = df_4h.iloc[-3]
        ts = int(df_4h.index[-2].timestamp() * 1000)

        del df_4h; gc.collect()

        if curr["Low"] < mother["Low"] and curr["Close"] > mother["High"]:
            return ("BULLISH", float(curr["Close"]), atr, ts, vol_ok)
        if curr["High"] > mother["High"] and curr["Close"] < mother["Low"]:
            return ("BEARISH", float(curr["Close"]), atr, ts, vol_ok)

    except Exception as e:
        print(f"[ERR] Sweep {ticker}: {e}")
    return None

def debug_sweep(ticker):
    try:
        df = yf.download(ticker, period="10d", interval="1h", progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 30:
            return msg_indi_debug_header(ticker, "Sweep + Engulfing") + \
                   f"├ ⚠️ Not enough 1H data (`{len(df)}` candles, need 30)\n" + BR2

        atr = float(calculate_atr(df, 10).iloc[-2])
        price = float(df["Close"].iloc[-1])
        vol = (atr / price * 100)
        vol_icon = "🟢" if vol >= MIN_VOLATILITY else "🔴"

        df_4h = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        if len(df_4h) < 4:
            return msg_indi_debug_header(ticker, "Sweep + Engulfing") + \
                   f"├ ⚠️ Not enough 4H data\n" + BR2

        df_4h["ATR"] = calculate_atr(df_4h, 10)
        curr = df_4h.iloc[-2]
        mother = df_4h.iloc[-3]

        sweep_low  = curr["Low"] < mother["Low"]
        sweep_high = curr["High"] > mother["High"]
        engulf_up  = curr["Close"] > mother["High"]
        engulf_dn  = curr["Close"] < mother["Low"]

        low_icon  = "🟢" if sweep_low else "⚪"
        high_icon = "🟢" if sweep_high else "⚪"
        up_icon   = "🟢" if engulf_up else "⚪"
        dn_icon   = "🟢" if engulf_dn else "⚪"

        res = (
            f"{msg_indi_debug_header(ticker, 'Sweep + Engulfing')}"
            f"├ {vol_icon} *Volatility:* `{vol:.2f}%` (min `{MIN_VOLATILITY}%`)\n"
            f"├ 📊 *Current 4H:*  H=`{curr['High']:.2f}`  L=`{curr['Low']:.2f}`  C=`{curr['Close']:.2f}`\n"
            f"├ 📊 *Mother 4H:*   H=`{mother['High']:.2f}`  L=`{mother['Low']:.2f}`  C=`{mother['Close']:.2f}`\n"
            f"{BR}\n"
            f"├ {low_icon}  Sweep Low:  Curr L `{curr['Low']:.2f}` {'<' if sweep_low else '>='} Mother L `{mother['Low']:.2f}`\n"
            f"├ {high_icon} Sweep High: Curr H `{curr['High']:.2f}` {'>' if sweep_high else '<='} Mother H `{mother['High']:.2f}`\n"
            f"├ {up_icon}   Engulf Up:  Curr C `{curr['Close']:.2f}` {'>' if engulf_up else '<='} Mother H `{mother['High']:.2f}`\n"
            f"└ {dn_icon}   Engulf Dn:  Curr C `{curr['Close']:.2f}` {'<' if engulf_dn else '>='} Mother L `{mother['Low']:.2f}`\n"
            f"{BR}\n"
        )

        if vol < MIN_VOLATILITY:
            res += "⛔ *RESULT:* Failed Volatility Check\n"
        elif sweep_low and engulf_up:
            res += "✅ *RESULT:* 🟢 BULLISH Sweep + Engulfing Triggered\n"
        elif sweep_high and engulf_dn:
            res += "✅ *RESULT:* 🔴 BEARISH Sweep + Engulfing Triggered\n"
        else:
            res += "⚪ *RESULT:* No Sweep + Engulfing Condition Met\n"

        res += BR2
        return res
    except Exception as e:
        return msg_error(f"Debug Sweep {ticker}", str(e))


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

        vol_ok = True
        try:
            atr = float(calculate_atr(df_15, 1).iloc[-2])
            price = float(df_15["Close"].iloc[-1])
            if (atr / price * 100) < MIN_VOLATILITY:
                vol_ok = False
        except Exception:
            pass

        df_15["xATR"]  = calculate_atr(df_15, 1)
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
            return ("BULLISH", float(src[i]), atr_val, ts, vol_ok)
        if is_sell and m5_close < m5_ema and rsi_15 > 30:
            return ("BEARISH", float(src[i]), atr_val, ts, vol_ok)

    except Exception as e:
        print(f"[ERR] UT Bot {ticker}: {e}")
    return None

def debug_ut(ticker, kv=2):
    try:
        df_15 = yf.download(ticker, period="3d", interval="15m", progress=False, auto_adjust=True)
        df_5  = yf.download(ticker, period="1d", interval="5m", progress=False, auto_adjust=True)
        df_15 = normalise_cols(df_15)
        df_5  = normalise_cols(df_5)
        if df_15.empty or len(df_15) < 20 or df_5.empty or len(df_5) < 40:
            return msg_indi_debug_header(ticker, "UT Bot") + \
                   f"├ ⚠️ Not enough data (15m: `{len(df_15)}`, 5m: `{len(df_5)}`)\n" + BR2

        atr = float(calculate_atr(df_15, 1).iloc[-2])
        price = float(df_15["Close"].iloc[-1])
        vol = (atr / price * 100)
        vol_icon = "🟢" if vol >= MIN_VOLATILITY else "🔴"

        df_15["xATR"] = calculate_atr(df_15, 1)
        df_15["nLoss"] = kv * df_15["xATR"]
        src = df_15["Close"].values
        nLoss = df_15["nLoss"].values
        ts_arr = np.zeros(len(df_15))
        pos = np.zeros(len(df_15))
        for i in range(1, len(df_15)):
            prev_ts, prev_src = ts_arr[i-1], src[i-1]
            if src[i] > prev_ts and prev_src > prev_ts: ts_arr[i] = max(prev_ts, src[i] - nLoss[i])
            elif src[i] < prev_ts and prev_src < prev_ts: ts_arr[i] = min(prev_ts, src[i] + nLoss[i])
            elif src[i] > prev_ts: ts_arr[i] = src[i] - nLoss[i]
            else: ts_arr[i] = src[i] + nLoss[i]
            if prev_src < prev_ts and src[i] > ts_arr[i]: pos[i] = 1
            elif prev_src > prev_ts and src[i] < ts_arr[i]: pos[i] = -1
            else: pos[i] = pos[i-1]

        i = len(df_15) - 2
        is_buy  = (src[i] > ts_arr[i]) and (src[i-1] <= ts_arr[i-1])
        is_sell = (src[i] < ts_arr[i]) and (src[i-1] >= ts_arr[i-1])

        df_5["EMA50"] = df_5["Close"].ewm(span=50, adjust=False).mean()
        df_15["RSI"]  = get_rsi(df_15)
        m5_close = float(df_5["Close"].iloc[-2])
        m5_ema   = float(df_5["EMA50"].iloc[-2])
        rsi_15   = float(df_15["RSI"].iloc[-2])

        buy_icon  = "🟢" if is_buy else "⚪"
        sell_icon = "🟢" if is_sell else "⚪"
        ema_above = m5_close > m5_ema
        ema_icon  = "🟢" if ema_above else "🔴"
        rsi_ok_buy  = rsi_15 < 70
        rsi_ok_sell = rsi_15 > 30
        rsi_icon = "🟢" if (rsi_ok_buy or rsi_ok_sell) else "🔴"

        res = (
            f"{msg_indi_debug_header(ticker, 'UT Bot')}"
            f"├ {vol_icon} *Volatility:* `{vol:.2f}%` (min `{MIN_VOLATILITY}%`)\n"
            f"{BR}\n"
            f"├ {buy_icon}  *UT Buy Crossover:*  Close `{src[i]:.2f}` {'>' if is_buy else '<='} TrailingStop `{ts_arr[i]:.2f}`\n"
            f"├ {sell_icon} *UT Sell Crossover:* Close `{src[i]:.2f}` {'<' if is_sell else '>='} TrailingStop `{ts_arr[i]:.2f}`\n"
            f"{BR}\n"
            f"├ {ema_icon}  *5m EMA Filter:*     Close `{m5_close:.2f}` {'>' if ema_above else '<'} EMA50 `{m5_ema:.2f}`\n"
            f"├ {rsi_icon}  *15m RSI Filter:*    `{rsi_15:.1f}` (Buy need `<70` · Sell need `>30`)\n"
            f"{BR}\n"
        )

        if vol < MIN_VOLATILITY:
            res += "⛔ *RESULT:* Failed Volatility Check\n"
        elif is_buy and ema_above and rsi_ok_buy:
            res += "✅ *RESULT:* 🟢 BULLISH UT Bot Triggered\n"
        elif is_sell and (not ema_above) and rsi_ok_sell:
            res += "✅ *RESULT:* 🔴 BEARISH UT Bot Triggered\n"
        else:
            reasons = []
            if not is_buy and not is_sell: reasons.append("No UT crossover")
            if is_buy and not ema_above: reasons.append("5m Close below EMA50")
            if is_buy and not rsi_ok_buy: reasons.append(f"RSI {rsi_15:.1f} >= 70")
            if is_sell and ema_above: reasons.append("5m Close above EMA50")
            if is_sell and not rsi_ok_sell: reasons.append(f"RSI {rsi_15:.1f} <= 30")
            res += f"⚪ *RESULT:* No Condition Met → {'; '.join(reasons)}\n"

        res += BR2
        return res
    except Exception as e:
        return msg_error(f"Debug UT Bot {ticker}", str(e))


# ============================================================
#  TRADE EXECUTION
# ============================================================
def calc_sl_tp(sig_type, entry, atr):
    if "BULLISH" in sig_type:
        return float(entry - atr * ATR_MULT_SL), float(entry + atr * ATR_MULT_TP)
    return float(entry + atr * ATR_MULT_SL), float(entry - atr * ATR_MULT_TP)

def calc_position_size(account, entry, sl):
    with _lock:
        balance = accounts[account]["balance"]
    risk = balance * 0.02
    sl_dist = abs(entry - sl)
    if sl_dist == 0:
        return 0.0
    return float(risk / sl_dist)

def execute_trade(symbol, mtype, account, strat, sig_type, price, atr, ts):
    global active_trades

    with _lock:
        key = f"{symbol}_{ts}_{sig_type}_{account}"
        if key in sent_signals:
            return
        sent_signals[key] = True
        save_json(SENT_SIGNALS_FILE, sent_signals)

        if accounts[account]["daily_trades"] >= 3:
            return
        if any(t["symbol"] == symbol and t["account"] == account for t in active_trades):
            return

        sl = calc_sl_tp(sig_type, price, atr)[0]
        qty = calc_position_size(account, price, sl)
        if qty <= 0:
            return

        actual_sl, actual_tp = calc_sl_tp(sig_type, price, atr)
        tf = "4H" if "Sweep" in strat else "15m"

        trade = {
            "id":         f"{symbol}_{int(time.time())}",
            "symbol":     symbol,
            "market":     mtype,
            "account":    account,
            "strat":      strat,
            "type":       "LONG" if "BULLISH" in sig_type else "SHORT",
            "entry":      float(price),
            "sl":         actual_sl,
            "tp":         actual_tp,
            "qty":        float(qty),
            "trail_sl":   actual_sl,
            "ts_trigger": ts,
            "time":       datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        }

        active_trades.append(trade)
        accounts[account]["daily_trades"] += 1
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, active_trades)

    risk_amt = abs(price - actual_sl) * qty

    msg = msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account)

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

        for trade in active_trades:
            try:
                df = yf.download(trade["symbol"], period="1d",
                                 interval="1m", progress=False, auto_adjust=True)
                df = normalise_cols(df)
                if df.empty:
                    del df; gc.collect()
                    continue

                live    = float(df["Close"].iloc[-1])
                is_long = trade["type"] == "LONG"
                del df; gc.collect()

                if is_long:
                    profit_pct = (live - trade["entry"]) / trade["entry"] * 100
                else:
                    profit_pct = (trade["entry"] - live) / trade["entry"] * 100

                if profit_pct >= 1.5:
                    if is_long:
                        new_sl = trade["entry"] + (trade["entry"] * 0.005)
                        trade["trail_sl"] = max(trade["trail_sl"], new_sl)
                    else:
                        new_sl = trade["entry"] - (trade["entry"] * 0.005)
                        trade["trail_sl"] = min(trade["trail_sl"], new_sl)

                hit_tp = (is_long and live >= trade["tp"]) or (not is_long and live <= trade["tp"])
                hit_sl = (is_long and live <= trade["trail_sl"]) or (not is_long and live >= trade["trail_sl"])

                if not (hit_tp or hit_sl):
                    continue

                pnl = abs(trade["tp"] - trade["entry"]) * trade["qty"] if hit_tp \
                    else -(abs(trade["entry"] - trade["trail_sl"]) * trade["qty"])

                with _lock:
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
                except Exception:
                    pass

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
                    if symbol in muted_assets:
                        continue

                account = get_account(symbol)
                if account == "nifty" and not is_nifty_market_open():
                    continue

                vol_filter_on = bot_settings.get("volatility_filter", True)

                ut = check_ut_bot(symbol)
                if ut:
                    ny_active = is_ny_session()
                    # Execute on novol tracker
                    execute_trade(symbol, mtype, "utbot_novol", "UT Bot (No-Vol)", ut[0], ut[1], ut[2], ut[3])

                    if not vol_filter_on or ut[4]:
                        target = "ny_session" if ny_active else "macro"
                        execute_trade(symbol, mtype, target, "UT Bot Signals", ut[0], ut[1], ut[2], ut[3])

                sweep = check_sweep_engulfing(symbol)
                if sweep:
                    # Execute on novol tracker
                    execute_trade(symbol, mtype, "sweep_novol", "Sweep (No-Vol)", sweep[0], sweep[1], sweep[2], sweep[3])

                    if not vol_filter_on or sweep[4]:
                        execute_trade(symbol, mtype, account, "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3])

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
            with _lock:
                for acc in ["macro", "nifty", "ny_session", "sweep_novol", "utbot_novol"]:
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

            msg = msg_midnight_reset(
                day_pnl,
                accounts["macro"]["balance"],
                accounts["nifty"]["balance"],
                accounts["ny_session"]["balance"]
            )
            safe_send_message(CHAT_ID, msg, parse_mode="Markdown")

            if len(history) > 500:
                history = history[-500:]
                save_json(HISTORY_FILE, history)

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
                elif sweep:
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

        vol_filter_on = bot_settings.get("volatility_filter", True)
        safe_send_message(m.chat.id, msg_summary(lines, vol_filter_on), parse_mode="Markdown")
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

        mw, ml, mp, mwr = stats("macro")
        nw, nl, np_, nwr = stats("nifty")
        nyw, nyl, nyp, nywr = stats("ny_session")

        safe_send_message(m.chat.id, msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr), parse_mode="Markdown", reply_markup=menu_markup())
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Performance Stats", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["balance"])
def cmd_balance(m):
    try:
        with _lock:
            macro_bal = accounts["macro"]["balance"]
            nifty_bal = accounts["nifty"]["balance"]
            ny_bal    = accounts["ny_session"]["balance"]
            macro_d   = accounts["macro"]["daily_trades"]
            nifty_d   = accounts["nifty"]["daily_trades"]
            ny_d      = accounts["ny_session"]["daily_trades"]
            ny_active = is_ny_session()

        vol_filter_on = bot_settings.get("volatility_filter", True)
        safe_send_message(m.chat.id, msg_balance(macro_bal, nifty_bal, ny_bal, macro_d, nifty_d, ny_d, ny_active, vol_filter_on), parse_mode="Markdown", reply_markup=menu_markup())
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Balance Query", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["clear"])
def cmd_clear(m):
    global active_trades
    try:
        with _lock:
            active_trades = []
            for acc in ["macro", "nifty", "ny_session", "sweep_novol", "utbot_novol"]:
                accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
            save_json(ACCOUNTS_FILE, accounts)
            save_json(ACTIVE_TRADES_FILE, [])
            save_json(HISTORY_FILE, [])

        safe_send_message(m.chat.id, msg_cleared(), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Account Clear", str(e)), parse_mode="Markdown")


@bot.message_handler(commands=["vol"])
def cmd_vol(m):
    try:
        is_enabled = bot_settings.get("volatility_filter", True)
        markup = InlineKeyboardMarkup()
        if is_enabled:
            markup.add(InlineKeyboardButton("🔴 Turn OFF Volatility Filter", callback_data="vol_off"))
        else:
            markup.add(InlineKeyboardButton("🟢 Turn ON Volatility Filter", callback_data="vol_on"))

        safe_send_message(m.chat.id, msg_volatility(is_enabled), parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Volatility Command", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["indi1"])
def cmd_indi1(m):
    chat_id = m.chat.id
    safe_send_message(chat_id, msg_indi_diagnosing(1))
    def run_diag():
        try:
            results = []
            for symbol, mtype in MONITORED:
                results.append(debug_sweep(symbol))
                time.sleep(0.5)
                gc.collect()

            full_text = "\n\n".join(results)
            for i in range(0, len(full_text), 4000):
                safe_send_message(chat_id, full_text[i:i+4000], parse_mode="Markdown")

            signals = []
            for symbol, mtype in MONITORED:
                sweep = check_sweep_engulfing(symbol)
                if sweep:
                    execute_trade(symbol, mtype, "sweep_novol", "Sweep (No-Vol)", sweep[0], sweep[1], sweep[2], sweep[3])
                    if sweep[4]:
                        signals.append(f"🟢 `{symbol}` ➔ 🔵 Sweep *{sweep[0]}*  `${sweep[1]:,.4f}`\n   └ 🏢 Executed on *ALL* accounts")
                        execute_trade(symbol, mtype, get_account(symbol), "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3])
                    else:
                        signals.append(f"🟡 `{symbol}` ➔ 🔵 Sweep *{sweep[0]}*  `${sweep[1]:,.4f}`\n   └ ⚠️ Low volatility → NO-VOL account only")
                time.sleep(0.5)
                gc.collect()

            if signals:
                safe_send_message(chat_id, msg_indi_executions(1, signals), parse_mode="Markdown")
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
                results.append(debug_ut(symbol))
                time.sleep(0.5)
                gc.collect()

            full_text = "\n\n".join(results)
            for i in range(0, len(full_text), 4000):
                safe_send_message(chat_id, full_text[i:i+4000], parse_mode="Markdown")

            signals = []
            for symbol, mtype in MONITORED:
                ut = check_ut_bot(symbol)
                if ut:
                    ny_active = is_ny_session()
                    execute_trade(symbol, mtype, "utbot_novol", "UT Bot (No-Vol)", ut[0], ut[1], ut[2], ut[3])
                    if ut[4]:
                        signals.append(f"🟢 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}*  `${ut[1]:,.4f}`\n   └ 🏢 Executed on *ALL* accounts")
                        target = "ny_session" if ny_active else "macro"
                        execute_trade(symbol, mtype, target, "UT Bot Signals", ut[0], ut[1], ut[2], ut[3])
                    else:
                        signals.append(f"🟡 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}*  `${ut[1]:,.4f}`\n   └ ⚠️ Low volatility → NO-VOL account only")
                time.sleep(0.5)
                gc.collect()

            if signals:
                safe_send_message(chat_id, msg_indi_executions(2, signals), parse_mode="Markdown")
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
        elif c.data == "vol_on":
            with _lock:
                bot_settings["volatility_filter"] = True
                save_json(SETTINGS_FILE, bot_settings)

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔴 Turn OFF Volatility Filter", callback_data="vol_off"))
            bot.edit_message_text(
                msg_volatility(True), c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=markup)

        elif c.data == "vol_off":
            with _lock:
                bot_settings["volatility_filter"] = False
                save_json(SETTINGS_FILE, bot_settings)

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🟢 Turn ON Volatility Filter", callback_data="vol_on"))
            bot.edit_message_text(
                msg_volatility(False), c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=markup)

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

            for _, row in df.iterrows():
                color = "#00ff88" if row["Close"] >= row["Open"] else "#ff4444"
                ax.plot([df.index.get_loc(_) + 1]*2,
                        [row["Low"], row["High"]], color=color, linewidth=1)
                ax.bar(df.index.get_loc(_) + 1,
                       abs(row["Close"] - row["Open"]) + 1e-8,
                       bottom=min(row["Open"], row["Close"]),
                       width=0.3, color=color, linewidth=1)

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
            del df; gc.collect()
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
    init_settings()
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
    while True:
        try:
            bot.polling(timeout=60, long_polling_timeout=10)
        except Exception as e:
            print(f"[ERR] Polling crashed: {e}")
            time.sleep(5)
