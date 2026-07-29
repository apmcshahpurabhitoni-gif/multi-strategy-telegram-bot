import os
import json
import time
import csv
import threading
import gc
from datetime import datetime, timedelta
from io import BytesIO

import requests
import numpy as np
import pandas as pd
import yfinance as yf
import pytz
import telebot
import matplotlib
import matplotlib.pyplot as plt
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, jsonify, send_file

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

# Ensure workspace exists (Render ephemeral disk)
os.makedirs("/workspace", exist_ok=True)

# Files
ACCOUNTS_FILE      = "/workspace/accounts.json"
ACTIVE_TRADES_FILE = "/workspace/active_trades.json"
HISTORY_FILE       = "/workspace/trade_history.json"
MUTE_FILE          = "/workspace/muted_assets.json"
TRADE_LOG_CSV      = "/workspace/trade_log.csv"
SENT_SIGNALS_FILE  = "/workspace/sent_signals.json"

# Per-account max trades per day
ACCOUNT_LIMITS = {
    "macro":      20,
    "nifty":      3,
    "ny_session": 3,
    "sweep_4h":   3,
}

# Monitored assets
MONITORED = [
    ("BTC-USD",  "Crypto"),
    ("GC=F",     "Commodity"),
    ("^NSEI",    "Index"),
    ("^NSEBANK", "Index"),
    ("EURUSD=X", "Forex"),
    ("GBPUSD=X", "Forex"),
    ("USDJPY=X", "Forex"),
]

# Globals
accounts      = {}
active_trades = []
muted_assets  = set()
sent_signals  = {}

_lock        = threading.RLock()
_chart_lock  = threading.RLock()
_price_cache = {}
_price_ttl   = 120
_last_scan_time = 0

IST = pytz.timezone("Asia/Kolkata")

# Shared yfinance session to reduce rate-limit hits
_YF_SESSION = requests.Session()
_YF_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

# ============================================================
#  HELPERS
# ============================================================
def is_market_open(symbol):
    now = datetime.now(IST)
    w, total_min = now.weekday(), now.hour * 60 + now.minute
    if symbol in ("BTC-USD", "GC=F"): 
        return True
    if symbol in ("EURUSD=X", "GBPUSD=X", "USDJPY=X"): 
        return w < 5
    if symbol in ("^NSEI", "^NSEBANK"): 
        return w < 5 and 555 <= total_min <= 930
    return False

def is_ny_session():
    now = datetime.now(IST)
    w = now.weekday()
    total_min = now.hour * 60 + now.minute
    return w < 5 and (total_min >= 1200 or total_min <= 150)

# ============================================================
#  MESSAGE TEMPLATES
# ============================================================
BR  = "━━━━━━━━━━━━━━━━━━━━━━"
BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

def msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account):
    arrow  = "🟢🟢🟢" if "BULLISH" in sig_type else "🔴🔴🔴"
    label  = "🚀 STRONG BULLISH" if "BULLISH" in sig_type else "💥 STRONG BEARISH"
    dir_   = "LONG 📈" if "BULLISH" in sig_type else "SHORT 📉"
    return (
        "⚡ *ALERT — HIGH CONFLUENCE SIGNAL*\n"
        + BR + "\n"
        + arrow + "  *" + label + "*\n"
        + BR + "\n"
        + "🪙 *Asset:*      `" + symbol + "`\n"
        + "🌐 *Market:*     " + mtype + "\n"
        + "🎯 *Strategy:*   " + strat + "\n"
        + "📊 *Direction:*  " + dir_ + "\n"
        + "⏱  *Timeframe:*  " + tf + "\n"
        + BR + "\n"
        + "💼 *PAPER TRADE EXECUTED*\n"
        + BR + "\n"
        + "🏢 *Account:*   `" + account.upper() + "`\n"
        + "📍 *Entry:*     `$" + f"{price:,.4f}" + "`\n"
        + "🛑 *Stop Loss:* `$" + f"{actual_sl:,.4f}" + "`\n"
        + "🎯 *Take Profit:* `$" + f"{actual_tp:,.4f}" + "`\n"
        + "📦 *Qty:*       `" + f"{qty:.4f}" + "`\n"
        + "💰 *Risk:*      `₹" + f"{risk_amt:,.2f}" + "`"
    )

def msg_scanning():
    return "🔍 Scanning markets... please wait."

def msg_scan_results(signals, neutral):
    text = "*📊 MARKET SCAN RESULTS*\n" + BR2 + "\n\n"
    if signals:
        text += "*🟢 ACTIVE SETUPS*\n" + "\n".join(signals) + "\n\n"
    if neutral:
        text += "*⚪ NEUTRAL*\n" + "\n".join(neutral) + "\n"
    return text

def msg_summary(lines):
    return "*📈 ASSET SUMMARY*\n" + BR2 + "\n\n" + "\n".join(lines)

def msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr, sw, sl, sp, swr):
    def fmt(w, l, p, wr):
        return f"W:{w} L:{l} PnL:₹{p:,.2f} WR:{wr:.1f}%"
    return (
        "*📊 PERFORMANCE STATS*\n" + BR2 + "\n\n"
        + "🏢 *Macro:*      " + fmt(mw, ml, mp, mwr) + "\n"
        + "🇮🇳 *Nifty:*     " + fmt(nw, nl, np_, nwr) + "\n"
        + "🗽 *NY Session:* " + fmt(nyw, nyl, nyp, nywr) + "\n"
        + "🌊 *Sweep 4H:*  " + fmt(sw, sl, sp, swr)
    )

def msg_active_trades(trades_list, total_pnl):
    header = "*📋 ACTIVE POSITIONS*\n" + BR2 + "\n\n"
    body = "\n".join(trades_list)
    footer = "\n" + BR + "\n*Total U.PnL:* `₹" + f"{total_pnl:,.2f}" + "`"
    return header + body + footer

def msg_trade_closed(trade, live, pnl, bal, is_long, hit_tp):
    emoji = "🟢" if pnl > 0 else "🔴"
    result = "WIN ✅" if pnl > 0 else "LOSS ❌"
    return (
        emoji + " *TRADE CLOSED*\n" + BR + "\n"
        + "🪙 `" + trade["symbol"] + "` | " + trade["type"] + "\n"
        + "📍 Entry: `₹" + f"{trade['entry']:,.4f}" + "`\n"
        + "🏁 Exit:  `₹" + f"{live:,.4f}" + "`\n"
        + "💰 PnL:  `₹" + f"{pnl:,.2f}" + "` | " + result + "\n"
        + "🏦 Balance: `₹" + f"{bal:,.2f}" + "`"
    )

def msg_error(context, error):
    return "❌ *Error in " + context + "*\n`" + str(error) + "`"

def msg_guide():
    return (
        "*🤖 Trading Bot Commands*\n" + BR2 + "\n\n"
        + "`/check` — Scan markets now\n"
        + "`/summary` — Asset prices & status\n"
        + "`/active` — Open positions\n"
        + "`/balance` — Account balances\n"
        + "`/stats` — Performance stats\n"
        + "`/close SYMBOL` — Close a trade\n"
        + "`/export` — Download CSV log\n"
        + "`/clear` — Reset all accounts\n"
        + "`/indi1` / `/indi2` — Strategy diagnostics"
    )

def msg_no_active_trades():
    return "📭 No active trades at the moment."

def msg_cleared():
    return "✅ *All accounts reset to ₹1,00,000*\nHistory and trades cleared."

def msg_indi_diagnosing(n):
    return f"🔬 Running Strategy {n} diagnosis..."

def msg_indi_no_signals(n):
    return f"😴 Strategy {n}: No signals found."

def msg_export_ready(count):
    return f"📥 Export ready — {count} trade(s) logged."

def msg_chart_failed():
    return "❌ Chart generation failed."

def msg_muted(sym):
    return f"🔇 `{sym}` muted."

def msg_unmuted(sym):
    return f"🔊 `{sym}` unmuted."

# ============================================================
#  JSON / IO
# ============================================================
def load_json(filepath, default):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print("[ERR] load_json(" + filepath + "): " + str(e))
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print("[ERR] save_json(" + filepath + "): " + str(e))

def safe_send_message(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        print("[ERR] Failed to send message: " + str(e))
        try:
            clean = text.replace("*", "").replace("`", "").replace("_", "")
            bot.send_message(chat_id, "⚠️ Message formatting error, raw output:\n" + clean, parse_mode=None)
        except Exception as fallback_e:
            print("[ERR] Fallback message also failed: " + str(fallback_e))

def init_accounts():
    global accounts
    defaults = {
        "macro":      {"balance": 100000.0, "daily_trades": 0},
        "nifty":      {"balance": 100000.0, "daily_trades": 0},
        "ny_session": {"balance": 100000.0, "daily_trades": 0},
        "sweep_4h":   {"balance": 100000.0, "daily_trades": 0},
    }
    accounts = load_json(ACCOUNTS_FILE, defaults)
    for key in ["sweep_novol", "utbot_novol"]:
        accounts.pop(key, None)
    for key, val in defaults.items():
        if key not in accounts:
            accounts[key] = val
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if accounts.get("last_reset_date") != today:
        for key in defaults:
            accounts[key]["daily_trades"] = 0
        accounts["last_reset_date"] = today
        save_json(ACCOUNTS_FILE, accounts)

# ============================================================
#  PRICE & DATA
# ============================================================
def get_price(symbol):
    now = time.time()
    if symbol in _price_cache:
        price, ts = _price_cache[symbol]
        if now - ts < _price_ttl:
            return price
    try:
        df = yf.download(
            symbol, period="5d", interval="15m",
            progress=False, auto_adjust=True,
            session=_YF_SESSION
        )
        df = normalise_cols(df)
        if df.empty:
            return None
        price = float(df["Close"].iloc[-1])
        _price_cache[symbol] = (price, now)
        del df
        return price
    except Exception as e:
        print(f"[ERR] get_price {symbol}: {e}")
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
    return tr.rolling(period).mean()

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
#  STRATEGY 1 — SWEEP + ENGULFING
# ============================================================
def check_sweep_engulfing(ticker):
    df_target = None
    try:
        df = yf.download(
            ticker, period="10d", interval="1h",
            progress=False, auto_adjust=True,
            session=_YF_SESSION
        )
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
                .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
                .dropna()
            )
            del df

        if len(df_target) < 4:
            return None

        curr   = df_target.iloc[-2]
        mother = df_target.iloc[-3]
        ts = int(df_target.index[-2].timestamp() * 1000)
        price = float(curr["Close"])

        if curr["Low"] < mother["Low"] and curr["High"] > mother["High"] and curr["Close"] > mother["High"]:
            sl = float(curr["Low"])
            risk = price - sl
            if risk <= 0: 
                return None
            tp = price + (risk * 2.0)
            if not is_nifty:
                del df_target; gc.collect()
            return ("BULLISH", price, sl, tp, ts)

        if curr["High"] > mother["High"] and curr["Low"] < mother["Low"] and curr["Close"] < mother["Low"]:
            sl = float(curr["High"])
            risk = sl - price
            if risk <= 0: 
                return None
            tp = price - (risk * 2.0)
            if not is_nifty:
                del df_target; gc.collect()
            return ("BEARISH", price, sl, tp, ts)

        if not is_nifty:
            del df_target; gc.collect()
    except Exception as e:
        print("[ERR] Sweep " + ticker + ": " + str(e))
    return None

# ============================================================
#  STRATEGY 2 — UT BOT
# ============================================================
def check_ut_bot(ticker, kv=2):
    try:
        df_15 = yf.download(
            ticker, period="3d", interval="15m",
            progress=False, auto_adjust=True,
            session=_YF_SESSION
        )
        df_5  = yf.download(
            ticker, period="1d", interval="5m",
            progress=False, auto_adjust=True,
            session=_YF_SESSION
        )
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

        if is_buy and m5_close > m5_ema and rsi_15 > 50:
            sl = m5_close - (atr_val * ATR_MULT_SL)
            tp = m5_close + (atr_val * ATR_MULT_TP)
            del df_15, df_5; gc.collect()
            return ("BULLISH", m5_close, sl, tp, ts)

        if is_sell and m5_close < m5_ema and rsi_15 < 50:
            sl = m5_close + (atr_val * ATR_MULT_SL)
            tp = m5_close - (atr_val * ATR_MULT_TP)
            del df_15, df_5; gc.collect()
            return ("BEARISH", m5_close, sl, tp, ts)

        del df_15, df_5; gc.collect()
        return None
    except Exception as e:
        print("[ERR] UT Bot " + ticker + ": " + str(e))
        return None

# ============================================================
#  SCANNER & MONITOR
# ============================================================
def scanner_loop():
    global _last_scan_time
    while True:
        now = time.time()
        if now - _last_scan_time < 90:
            time.sleep(10)
            continue
        _last_scan_time = now

        for symbol, mtype in MONITORED:
            if not is_market_open(symbol):
                continue
            try:
                time.sleep(3)
                ut = check_ut_bot(symbol)
                time.sleep(1)
                sweep = check_sweep_engulfing(symbol)

                signals_found = []
                if ut:
                    signals_found.append(("UT Bot", ut))
                if sweep:
                    signals_found.append(("Sweep", sweep))

                for strat_name, sig in signals_found:
                    sig_type, price, sl, tp, ts = sig
                    key = symbol + "_" + strat_name + "_" + str(ts)

                    with _lock:
                        if key in sent_signals:
                            continue
                        sent_signals[key] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
                        save_json(SENT_SIGNALS_FILE, sent_signals)

                        if symbol in muted_assets:
                            continue

                        account = "macro"
                        if "^NSE" in symbol:
                            account = "nifty"
                        elif strat_name == "UT Bot":
                            account = "ny_session"
                        elif strat_name == "Sweep":
                            account = "sweep_4h"

                        if accounts[account]["daily_trades"] >= ACCOUNT_LIMITS[account]:
                            continue

                        risk_amt = accounts[account]["balance"] * 0.01
                        risk = abs(price - sl)
                        if risk <= 0:
                            continue
                        qty = risk_amt / risk

                        trade = {
                            "symbol": symbol,
                            "account": account,
                            "strat": strat_name,
                            "type": "LONG" if "BULLISH" in sig_type else "SHORT",
                            "entry": price,
                            "sl": sl,
                            "tp": tp,
                            "trail_sl": sl,
                            "qty": qty,
                            "open_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M"),
                        }
                        active_trades.append(trade)
                        accounts[account]["daily_trades"] += 1
                        save_json(ACCOUNTS_FILE, accounts)
                        save_json(ACTIVE_TRADES_FILE, active_trades)

                        tf = "15m" if strat_name == "UT Bot" else "4H"
                        msg = msg_trade_signal(symbol, mtype, strat_name, sig_type, tf, price, sl, tp, qty, risk_amt, account)
                        safe_send_message(CHAT_ID, msg, parse_mode="Markdown")
                        pushbullet_notify(msg)

                gc.collect()
            except Exception as e:
                print(f"[ERR] Scanner {symbol}: {e}")

        time.sleep(60)

def monitor_trades():
    while True:
        time.sleep(30)
        with _lock:
            trades = list(active_trades)
        if not trades:
            continue
        prices = {}
        for t in trades:
            sym = t["symbol"]
            if sym not in prices:
                prices[sym] = get_price(sym)
                time.sleep(0.5)
            live = prices[sym]
            if not live:
                continue
            is_long = t["type"] == "LONG"
            pnl = (live - t["entry"]) * t["qty"] if is_long else (t["entry"] - live) * t["qty"]

            hit_sl = False
            hit_tp = False
            if is_long:
                if live <= t["trail_sl"]:
                    hit_sl = True
                elif live >= t["tp"]:
                