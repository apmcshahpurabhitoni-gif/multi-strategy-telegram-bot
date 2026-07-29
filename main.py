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
                    hit_tp = True
            else:
                if live >= t["trail_sl"]:
                    hit_sl = True
                elif live <= t["tp"]:
                    hit_tp = True

            if hit_sl or hit_tp:
                with _lock:
                    if t not in active_trades:
                        continue
                    active_trades.remove(t)
                    accounts[t["account"]]["balance"] += pnl
                    t["exit_price"] = live
                    t["pnl"] = float(pnl)
                    t["result"] = "WIN" if pnl > 0 else "LOSS"
                    t["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
                    bal = accounts[t["account"]]["balance"]
                    save_json(ACCOUNTS_FILE, accounts)
                    save_json(ACTIVE_TRADES_FILE, active_trades)

                    history = load_json(HISTORY_FILE, [])
                    history.append(t)
                    save_json(HISTORY_FILE, history)

                    try:
                        file_exists = os.path.isfile(TRADE_LOG_CSV)
                        with open(TRADE_LOG_CSV, "a", newline="", encoding="utf-8") as csvfile:
                            fieldnames = ["close_time", "symbol", "account", "strategy", "type", "entry", "exit_price", "sl", "tp", "qty", "pnl", "result"]
                            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                            if not file_exists:
                                writer.writeheader()
                            writer.writerow({
                                "close_time": t["close_time"],
                                "symbol": t["symbol"],
                                "account": t["account"],
                                "strategy": t["strat"],
                                "type": t["type"],
                                "entry": t["entry"],
                                "exit_price": t["exit_price"],
                                "sl": t["sl"],
                                "tp": t["tp"],
                                "qty": t["qty"],
                                "pnl": t["pnl"],
                                "result": t["result"],
                            })
                    except Exception as e:
                        print("[ERR] Log trade: " + str(e))

                    msg = msg_trade_closed(t, live, float(pnl), bal, is_long, pnl > 0)
                    safe_send_message(CHAT_ID, msg, parse_mode="Markdown")

def daily_reset_loop():
    while True:
        now = datetime.now(IST)
        target = now.replace(hour=0, minute=5, second=0, microsecond=0)
        if now > target:
            target += timedelta(days=1)
        sleep_seconds = (target - now).total_seconds()
        time.sleep(sleep_seconds)
        with _lock:
            for acc in accounts:
                accounts[acc]["daily_trades"] = 0
            accounts["last_reset_date"] = datetime.now(IST).strftime("%Y-%m-%d")
            save_json(ACCOUNTS_FILE, accounts)
            print("[RESET] Daily trade counters reset")

# ============================================================
#  FLASK APP
# ============================================================
flask_app = Flask(__name__)

@flask_app.route("/ping")
def ping():
    return "pong"

@flask_app.route("/")
def home():
    return "Trading Bot OK"

@flask_app.route("/api/balance")
def api_balance():
    with _lock:
        return jsonify({
            "macro": accounts.get("macro", {"balance": 100000, "daily_trades": 0}),
            "nifty": accounts.get("nifty", {"balance": 100000, "daily_trades": 0}),
            "ny_session": accounts.get("ny_session", {"balance": 100000, "daily_trades": 0}),
            "sweep_4h": accounts.get("sweep_4h", {"balance": 100000, "daily_trades": 0}),
        })

@flask_app.route("/api/active")
def api_active():
    with _lock:
        return jsonify({"trades": list(active_trades), "count": len(active_trades)})

@flask_app.route("/api/history")
def api_history():
    hist = load_json(HISTORY_FILE, [])
    return jsonify({"trades": hist[-50:]})

@flask_app.route("/api/summary")
def api_summary():
    hist = load_json(HISTORY_FILE, [])
    total_wins = sum(1 for t in hist if t.get("result") == "WIN")
    total_loss = sum(1 for t in hist if t.get("result") == "LOSS")
    total_pnl = sum(float(t.get("pnl", 0)) for t in hist)
    return jsonify({
        "total_trades": len(hist),
        "wins": total_wins,
        "losses": total_loss,
        "win_rate": (total_wins / (total_wins + total_loss) * 100) if (total_wins + total_loss) > 0 else 0,
        "total_pnl": total_pnl,
        "active_count": len(active_trades),
    })

@flask_app.route("/api/export")
def api_export():
    if not os.path.exists(TRADE_LOG_CSV) or os.path.getsize(TRADE_LOG_CSV) == 0:
        return "No trade log available yet.", 404
    return send_file(TRADE_LOG_CSV, as_attachment=True, download_name="trade_log.csv")

@flask_app.route("/api/clear", methods=["POST"])
def api_clear():
    global active_trades, sent_signals
    with _lock:
        active_trades = []
        for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
            accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, [])
        save_json(HISTORY_FILE, [])
        sent_signals = {}
        save_json(SENT_SIGNALS_FILE, sent_signals)
    return jsonify({"success": True})

@flask_app.route("/api/close/<symbol>", methods=["POST"])
def api_close_symbol(symbol):
    target_symbol = symbol.upper()
    with _lock:
        trade_to_close = next((t for t in active_trades if t["symbol"].upper() == target_symbol), None)
        if not trade_to_close:
            return jsonify({"success": False, "error": "No active trade found"}), 404

    live = get_price(target_symbol)
    if not live:
        return jsonify({"success": False, "error": "Price fetch failed"}), 500

    is_long = trade_to_close["type"] == "LONG"
    pnl = (live - trade_to_close["entry"]) * trade_to_close["qty"] if is_long else (trade_to_close["entry"] - live) * trade_to_close["qty"]

    with _lock:
        if trade_to_close not in active_trades:
            return jsonify({"success": False, "error": "Trade already closed"}), 409
        active_trades.remove(trade_to_close)
        accounts[trade_to_close["account"]]["balance"] += pnl
        trade_to_close["exit_price"] = live
        trade_to_close["pnl"] = float(pnl)
        trade_to_close["result"] = "WIN" if pnl > 0 else "LOSS"
        trade_to_close["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        bal = accounts[trade_to_close["account"]]["balance"]
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, active_trades)
        history = load_json(HISTORY_FILE, [])
        history.append(trade_to_close)
        save_json(HISTORY_FILE, history)

        try:
            file_exists = os.path.isfile(TRADE_LOG_CSV)
            with open(TRADE_LOG_CSV, "a", newline="", encoding="utf-8") as csvfile:
                fieldnames = ["close_time", "symbol", "account", "strategy", "type", "entry", "exit_price", "sl", "tp", "qty", "pnl", "result"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    "close_time": trade_to_close["close_time"],
                    "symbol": trade_to_close["symbol"],
                    "account": trade_to_close["account"],
                    "strategy": trade_to_close["strat"],
                    "type": trade_to_close["type"],
                    "entry": trade_to_close["entry"],
                    "exit_price": trade_to_close["exit_price"],
                    "sl": trade_to_close["sl"],
                    "tp": trade_to_close["tp"],
                    "qty": trade_to_close["qty"],
                    "pnl": trade_to_close["pnl"],
                    "result": trade_to_close["result"],
                })
        except Exception as e:
            print("[ERR] Log trade: " + str(e))

    msg = msg_trade_closed(trade_to_close, live, float(pnl), bal, is_long, pnl > 0)
    safe_send_message(CHAT_ID, msg, parse_mode="Markdown")
    return jsonify({"success": True, "pnl": float(pnl), "balance": bal, "result": trade_to_close["result"]})

@flask_app.route("/dashboard")
def dashboard():
    return DASHBOARD_HTML

# ============================================================
#  TELEGRAM BOT
# ============================================================
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

def menu_markup():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🔍 Check Markets", callback_data="cmd_check"))
    m.add(InlineKeyboardButton("📊 Asset Summary", callback_data="cmd_summary"))
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
                ut = check_ut_bot(symbol)
                sweep = check_sweep_engulfing(symbol)
                if ut:
                    signals.append("🟢 `" + symbol + "` ➔ 🟣 UT Bot *" + ut[0] + "* `$" + f"{ut[1]:,.4f}" + "`")
                if sweep:
                    signals.append("🟢 `" + symbol + "` ➔ 🔵 Sweep *" + sweep[0] + "* `$" + f"{sweep[1]:,.4f}" + "`")
                if not ut and not sweep:
                    neutral.append("⚪ `" + symbol + "` — No Setup")
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
                lines.append(("🔴" if is_muted else "🟢") + " `" + symbol + "` · " + mtype + " · `$" + f"{price:,.4f}" + "` · " + status)
            else:
                lines.append(("🔴" if is_muted else "🟢") + " `" + symbol + "` · " + mtype + " · " + status)
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
            w = [x for x in ts if x["result"] == "WIN"]
            l = [x for x in ts if x["result"] == "LOSS"]
            p = sum(float(x["pnl"]) for x in ts)
            wr = len(w) / (len(w) + len(l)) * 100 if (w or l) else 0
            return len(w), len(l), p, wr
        mw, ml, mp, mwr = stats("macro")
        nw, nl, np_, nwr = stats("nifty")
        nyw, nyl, nyp, nywr = stats("ny_session")
        sw, sl, sp, swr = stats("sweep_4h")
        safe_send_message(m.chat.id, msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr, sw, sl, sp, swr), parse_mode="Markdown", reply_markup=menu_markup())
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
            is_long = t["type"] == "LONG"
            if live:
                if is_long:
                    pnl = (live - t["entry"]) * t["qty"]
                else:
                    pnl = (t["entry"] - live) * t["qty"]
                total_pnl += pnl
                pnl_str = "₹" + f"{pnl:,.2f}"
                arrow = "📈" if is_long else "📉"
            else:
                pnl_str = "⏳ Fetching..."
                arrow = "⏳"
            trades_list.append(
                "🪙 `" + symbol + "` | `" + t["account"] + "` | " + t["type"] + " " + arrow + "\n"
                + " 📍 Entry: `₹" + f"{t['entry']:,.4f}" + "` | 🛑 SL: `₹" + f"{t['trail_sl']:,.4f}" + "` | 🎯 TP: `₹" + f"{t['tp']:,.4f}" + "`\n"
                + " 📦 Qty: `" + f"{t['qty']:.4f}" + "` | 💰 U.PnL: `" + pnl_str + "`\n"
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
            safe_send_message(m.chat.id, msg_error("Manual Close", "No active trade found for " + target_symbol), parse_mode="Markdown")
            return
        live = get_price(target_symbol)
        if not live:
            safe_send_message(m.chat.id, msg_error("Manual Close", "Could not fetch current price for " + target_symbol), parse_mode="Markdown")
            return
        is_long = trade_to_close["type"] == "LONG"
        pnl = (live - trade_to_close["entry"]) * trade_to_close["qty"] if is_long else (trade_to_close["entry"] - live) * trade_to_close["qty"]
        hit_tp = pnl > 0
        with _lock:
            if trade_to_close not in active_trades:
                return
            active_trades.remove(trade_to_close)
            accounts[trade_to_close["account"]]["balance"] += pnl
            trade_to_close["exit_price"] = live
            trade_to_close["pnl"] = float(pnl)
            trade_to_close["result"] = "WIN" if pnl > 0 else "LOSS"
            trade_to_close["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
            bal = accounts[trade_to_close["account"]]["balance"]
            save_json(ACCOUNTS_FILE, accounts)
            save_json(ACTIVE_TRADES_FILE, active_trades)
            history = load_json(HISTORY_FILE, [])
            history.append(trade_to_close)
            save_json(HISTORY_FILE, history)
            try:
                file_exists = os.path.isfile(TRADE_LOG_CSV)
                with open(TRADE_LOG_CSV, "a", newline="", encoding="utf-8") as csvfile:
                    fieldnames = ["close_time", "symbol", "account", "strategy", "type", "entry", "exit_price", "sl", "tp", "qty", "pnl", "result"]
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow({
                        "close_time": trade_to_close["close_time"],
                        "symbol": trade_to_close["symbol"],
                        "account": trade_to_close["account"],
                        "strategy": trade_to_close["strat"],
                        "type": trade_to_close["type"],
                        "entry": trade_to_close["entry"],
                        "exit_price": trade_to_close["exit_price"],
                        "sl": trade_to_close["sl"],
                        "tp": trade_to_close["tp"],
                        "qty": trade_to_close["qty"],
                        "pnl": trade_to_close["pnl"],
                        "result": trade_to_close["result"],
                    })
            except Exception as e:
                print("[ERR] Log trade: " + str(e))
        msg = msg_trade_closed(trade_to_close, live, float(pnl), bal, is_long, hit_tp)
        safe_send_message(m.chat.id, msg, parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Manual Close", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["export"])
def cmd_export(m):
    try:
        if not os.path.exists(TRADE_LOG_CSV) or os.path.getsize(TRADE_LOG_CSV) == 0:
            safe_send_message(m.chat.id, msg_error("Export", "No trade log available yet."), parse_mode="Markdown")
            return
        with open(TRADE_LOG_CSV, "r", encoding="utf-8") as f:
            count = max(0, sum(1 for row in f) - 1)
        with open(TRADE_LOG_CSV, "rb") as doc:
            bot.send_document(m.chat.id, doc, caption=msg_export_ready(count), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Export", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["balance"])
def cmd_balance(m):
    try:
        with _lock:
            macro_bal = accounts["macro"]["balance"]
            nifty_bal = accounts["nifty"]["balance"]
            ny_bal = accounts["ny_session"]["balance"]
            sweep_bal = accounts.get("sweep_4h", {"balance": 100000.0})["balance"]
            macro_d = accounts["macro"]["daily_trades"]
            nifty_d = accounts["nifty"]["daily_trades"]
            ny_d = accounts["ny_session"]["daily_trades"]
            sweep_d = accounts.get("sweep_4h", {"daily_trades": 0})["daily_trades"]
            ny_active = is_ny_session()
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
            msg_balance(macro_bal, nifty_bal, ny_bal, sweep_bal, macro_d, nifty_d, ny_d, sweep_d,
                        ACCOUNT_LIMITS["macro"], ACCOUNT_LIMITS["nifty"], ACCOUNT_LIMITS["ny_session"], ACCOUNT_LIMITS["sweep_4h"],
                        ny_active, u_pnl),
            parse_mode="Markdown", reply_markup=menu_markup())
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Balance Query", str(e)), parse_mode="Markdown")

def msg_balance(macro_bal, nifty_bal, ny_bal, sweep_bal, macro_d, nifty_d, ny_d, sweep_d, macro_l, nifty_l, ny_l, sweep_l, ny_active, u_pnl):
    return (
        "*💰 ACCOUNT BALANCES*\n" + BR2 + "\n\n"
        + "🏢 *Macro:*      `₹" + f"{macro_bal:,.2f}" + "` | Trades: `" + str(macro_d) + "/" + str(macro_l) + "`\n"
        + "🇮🇳 *Nifty:*     `₹" + f"{nifty_bal:,.2f}" + "` | Trades: `" + str(nifty_d) + "/" + str(nifty_l) + "`\n"
        + "🗽 *NY Session:* `₹" + f"{ny_bal:,.2f}" + "` | Trades: `" + str(ny_d) + "/" + str(ny_l) + "` | " + ("🟢 OPEN" if ny_active else "🔴 CLOSED") + "\n"
        + "🌊 *Sweep 4H:*  `₹" + f"{sweep_bal:,.2f}" + "` | Trades: `" + str(sweep_d) + "/" + str(sweep_l) + "`\n\n"
        + "*Unrealized PnL:*\n"
        + "Macro: `₹" + f"{u_pnl['macro']:,.2f}" + "`\n"
        + "Nifty: `₹" + f"{u_pnl['nifty']:,.2f}" + "`\n"
        + "NY:    `₹" + f"{u_pnl['ny_session']:,.2f}" + "`\n"
        + "Sweep: `₹" + f"{u_pnl['sweep_4h']:,.2f}" + "`"
    )

@bot.message_handler(commands=["clear"])
def cmd_clear(m):
    global active_trades, sent_signals
    try:
        with _lock:
            active_trades = []
            for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
                accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
            save_json(ACCOUNTS_FILE, accounts)
            save_json(ACTIVE_TRADES_FILE, [])
            save_json(HISTORY_FILE, [])
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
                    results.append(icon + " `" + symbol + "` → " + sig + " @ " + f"{price:.2f}")
                else:
                    results.append("⚪ `" + symbol + "` → No Setup")
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
                    results.append(icon + " `" + symbol + "` → " + sig + " @ " + f"{price:.2f}")
                else:
                    results.append("⚪ `" + symbol + "` → No Setup")
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
                bot.send_photo(c.message.chat.id, buf, caption="📈 `" + sym + "` | 1H Chart")
            else:
                safe_send_message(c.message.chat.id, msg_chart_failed())
        elif c.data.startswith("mute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.add(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔊 Unmute " + sym, callback_data="unmute_" + sym))
            bot.edit_message_text(
                msg_muted(sym), c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=m)
        elif c.data.startswith("unmute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.discard(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔇 Mute " + sym, callback_data="mute_" + sym))
            bot.edit_message_text(
                msg_unmuted(sym), c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=m)
    except Exception as e:
        print("[ERR] Callback: " + str(e))
        try:
            bot.answer_callback_query(c.id)
        except Exception as e:
            print("[ERR] Callback answer: " + str(e))

# ============================================================
#  CHART GENERATION
# ============================================================
def generate_chart(symbol, tf="1h"):
    with _chart_lock:
        try:
            df = yf.download(symbol, period="3d", interval=tf,
                             progress=False, auto_adjust=True,
                             session=_YF_SESSION)
            df = normalise_cols(df)
            if df.empty:
                return None

            fig, ax = plt.subplots(figsize=(10, 5), facecolor="#0d1117", dpi=50)
            ax.set_facecolor("#0d1117")

            x = np.arange(len(df))
            close = df["Close"].to_numpy()
            open_ = df["Open"].to_numpy()
            high = df["High"].to_numpy()
            low = df["Low"].to_numpy()
            colors = np.where(close >= open_, "#00ff88", "#ff4444")

            ax.vlines(x, low, high, color=colors, linewidth=1)

            body_h = np.abs(close - open_) + 1e-8
            body_b = np.minimum(open_, close)
            ax.bar(x, body_h, bottom=body_b, width=0.6, color=colors, linewidth=0)

            ax.set_title(symbol + " | " + tf.upper(), color="white", fontsize=12, fontweight="bold")
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
            print("[ERR] Chart " + symbol + ": " + str(e))
            plt.close()
            return None

# ============================================================
#  DASHBOARD HTML
# ============================================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Bot Dashboard</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,Cantarell,sans-serif;background:#0d1117;color:#c9d1d9;padding:20px;max-width:900px;margin:0 auto}
  h1{color:#58a6ff;margin-bottom:8px;font-size:24px}
  .subtitle{color:#8b949e;font-size:12px;margin-bottom:20px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
  .card h3{font-size:14px;color:#8b949e;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px}
  .value{font-size:22px;font-weight:700;color:#e6edf3}
  .value.positive{color:#3fb950}.value.negative{color:#f85149}.value.neutral{color:#8b949e}
  .btn{background:#238636;color:#fff;border:none;padding:8px 14px;border-radius:6px;cursor:pointer;font-size:13px;margin-right:6px;margin-top:6px}
  .btn:hover{background:#2ea043}.btn.secondary{background:#21262d;border:1px solid #30363d;color:#c9d1d9}
  .btn.secondary:hover{background:#30363d}
  .section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
  .section h2{font-size:16px;margin-bottom:12px;color:#e6edf3}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;color:#8b949e;padding:8px;border-bottom:1px solid #30363d;font-weight:600}
  td{padding:8px;border-bottom:1px solid #21262d}
  .badge{font-size:11px;padding:2px 8px;border-radius:12px;background:#30363d;color:#c9d1d9}
  .badge.long{background:#23863633;color:#3fb950}.badge.short{background:#f8514933;color:#f85149}
  .empty{text-align:center;padding:24px;color:#8b949e}
  .toast{position:fixed;bottom:20px;right:20px;background:#238636;color:#fff;padding:10px 16px;border-radius:6px;font-size:13px;opacity:0;transition:opacity .3s}
  .toast.show{opacity:1}.toast.error{background:#f85149}
</style>
</head>
<body>
<h1>⚡ Trading Bot Dashboard</h1>
<div class="subtitle">Status: <span id="connStatus" class="value neutral">Loading...</span> | Auto-refresh: 15s</div>

<div class="grid">
  <div class="card"><h3>Macro Balance</h3><div class="value" id="balMacro">--</div></div>
  <div class="card"><h3>Nifty Balance</h3><div class="value" id="balNifty">--</div></div>
  <div class="card"><h3>NY Session</h3><div class="value" id="balNY">--</div></div>
  <div class="card"><h3>Sweep 4H</h3><div class="value" id="balSweep">--</div></div>
</div>

<div class="section">
  <h2>📋 Open Positions (<span id="activeCount">0</span>)</h2>
  <div id="activeContainer"><div class="empty">Loading...</div></div>
</div>

<div class="section">
  <h2>📈 Recent History</h2>
  <div id="historyContainer"><div class="empty">Loading...</div></div>
</div>

<div class="section">
  <h2>🔔 Actions</h2>
  <button class="btn" onclick="loadAll()">🔄 Refresh</button>
  <button class="btn secondary" onclick="exportCSV()">📥 Export CSV</button>
  <button class="btn secondary" onclick="clearAll()">🗑 Reset All</button>
</div>

<div id="toast" class="toast"></div>

<script>
async function fetchJSON(url, opts={}) {
  try {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
    return await r.json();
  } catch (e) {
    console.error('API Error:', e);
    showToast('API Error: ' + e.message, true);
    return null;
  }
}

function showToast(msg, isErr) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (isErr ? ' error' : '') + ' show';
  setTimeout(() => t.className = 'toast' + (isErr ? ' error' : ''), 2500);
}

async function loadBalances() {
  const d = await fetchJSON('/api/balance');
  if (!d) return;
  document.getElementById('balMacro').textContent = '₹' + (d.macro?.balance || 0).toLocaleString('en-IN', {maximumFractionDigits:2});
  document.getElementById('balNifty').textContent = '₹' + (d.nifty?.balance || 0).toLocaleString('en-IN', {maximumFractionDigits:2});
  document.getElementById('balNY').textContent = '₹' + (d.ny_session?.balance || 0).toLocaleString('en-IN', {maximumFractionDigits:2});
  document.getElementById('balSweep').textContent = '₹' + (d.sweep_4h?.balance || 0).toLocaleString('en-IN', {maximumFractionDigits:2});
}

async function loadActive() {
  const d = await fetchJSON('/api/active');
  if (!d) return;
  const el = document.getElementById('activeContainer');
  document.getElementById('activeCount').textContent = d.count || 0;
  if (!d.trades || d.trades.length === 0) {
    el.innerHTML = '<div class="empty">No open positions</div>';
    return;
  }
  let html = '<table><tr><th>Symbol</th><th>Account</th><th>Type</th><th>Entry</th><th>SL</th><th>TP</th><th>Qty</th></tr>';
  for (const t of d.trades) {
    const badge = t.type === 'LONG' ? 'long' : 'short';
    html += `<tr>
      <td><b>${t.symbol}</b></td>
      <td>${t.account}</td>
      <td><span class="badge ${badge}">${t.type}</span></td>
      <td>₹${t.entry?.toLocaleString?.() || t.entry}</td>
      <td>₹${t.sl?.toLocaleString?.() || t.sl}</td>
      <td>₹${t.tp?.toLocaleString?.() || t.tp}</td>
      <td>${t.qty}</td>
    </tr>`;
  }
  html += '</table>';
  el.innerHTML = html;
}

async function loadHistory() {
  const d = await fetchJSON('/api/history');
  if (!d) return;
  const el = document.getElementById('historyContainer');
  if (!d.trades || d.trades.length === 0) {
    el.innerHTML = '<div class="empty">No history yet</div>';
    return;
  }
  let html = '<table><tr><th>Time</th><th>Symbol</th><th>Account</th><th>Type</th><th>PnL</th><th>Result</th></tr>';
  for (const t of (d.trades || []).slice().reverse()) {
    const pnlClass = t.pnl > 0 ? 'positive' : (t.pnl < 0 ? 'negative' : 'neutral');
    html += `<tr>
      <td>${t.close_time || '-'}</td>
      <td>${t.symbol}</td>
      <td>${t.account}</td>
      <td>${t.type}</td>
      <td class="${pnlClass}">₹${Number(t.pnl).toLocaleString('en-IN', {maximumFractionDigits:2})}</td>
      <td><span class="badge ${t.result==='WIN'?'long':'short'}">${t.result}</span></td>
    </tr>`;
  }
  html += '</table>';
  el.innerHTML = html;
}

function exportCSV() {
  window.location.href = '/api/export';
}

async function clearAll() {
  if (!confirm('Reset ALL accounts to ₹1,00,000? This wipes history and active trades.')) return;
  showToast('Resetting...');
  const r = await fetchJSON('/api/clear', {method:'POST'});
  if (r && r.success) {
    showToast('All accounts reset');
    loadAll();
  } else {
    showToast('Reset failed', true);
  }
}

async function loadAll() {
  await Promise.all([loadBalances(), loadActive(), loadHistory()]);
  document.getElementById('connStatus').textContent = 'Live';
  document.getElementById('connStatus').className = 'value positive';
}

loadAll();
setInterval(loadAll, 15000);
</script>
</body>
</html>"""

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

    # CRITICAL: Prevent 409 conflicts on Render redeploys
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(1)
    except Exception as e:
        print(f"[WARN] Webhook cleanup: {e}")

    print("=" * 50)
    print("  Trading Bot Starting...")
    print("  Macro:      ₹" + f"{accounts['macro']['balance']:,.2f}")
    print("  Nifty:      ₹" + f"{accounts['nifty']['balance']:,.2f}")
    print("  NY Session: ₹" + f"{accounts['ny_session']['balance']:,.2f}")
    print("  Dashboard:  /dashboard")
    print("  Web server: :10000/ping")
    print("=" * 50)

    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=monitor_trades, daemon=True).start()
    threading.Thread(target=daily_reset_loop, daemon=True).start()

    def run_flask():
        flask_app.run(host="0.0.0.0", port=10000, threaded=True)

    threading.Thread(target=run_flask, daemon=True).start()

    print("[BOT] Connecting to Telegram...")
    backoff = 5
    while True:
        try:
            bot.polling(skip_pending=True, timeout=60, long_polling_timeout=10)
            backoff = 5
        except Exception as e:
            print("[ERR] Polling crashed: " + str(e))
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
